"""
DB2-based session implementation for OpenAI Agents SDK
Based on the SQLite session pattern from openai-agents-python

Direct ibm_db implementation with async-to-sync conversion using ThreadPoolExecutor.
Implements the OpenAI Agents SDK session interface for persistent conversation history.

Reference: https://github.com/openai/openai-agents-python/blob/main/src/agents/memory/sqlite_session.py
Threading approach: https://knrdl.github.io/posts/db2-async-python/
"""

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Dict, Any

import ibm_db
from agents.memory import SessionABC
from agents.items import TResponseInputItem

from src.common.db2_config import DB2Config

logger = logging.getLogger(__name__)

# Global single-threaded executor for DB2 operations (thread-safety requirement)
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db2")


class DB2Session(SessionABC):
    """
    DB2-based session implementation for OpenAI Agents SDK

    Direct ibm_db implementation following SQLite session patterns with async-to-sync conversion.
    Uses a global single-threaded ThreadPoolExecutor to handle DB2's thread-safety limitations.

    Reference: https://github.com/openai/openai-agents-python/blob/main/src/agents/memory/sqlite_session.py
    Threading approach: https://knrdl.github.io/posts/db2-async-python/
    """

    def __init__(
        self,
        session_id: str,
        config: Optional[DB2Config] = None,
        sessions_table: str = "agent_sessions",
        messages_table: str = "agent_messages",
    ):
        """
        Initialize DB2 session

        Args:
            session_id: Unique identifier for this session
            config: DB2 connection configuration (uses defaults if None)
            sessions_table: Name of the sessions table (default: agent_sessions)
            messages_table: Name of the messages table (default: agent_messages)
        """
        self.session_id = session_id
        self.config = config or DB2Config()
        self.sessions_table = sessions_table
        self.messages_table = messages_table
        self._connection = None
        self._connection_initialized = False

    def _get_connection(self):
        """Get or create DB2 connection (persistent per instance)."""
        if self._connection is None:
            try:
                conn_str = self.config.get_connection_string()
                self._connection = ibm_db.connect(conn_str, "", "")
                if not self._connection:
                    raise ConnectionError("Failed to establish DB2 connection")

                # Initialize database schema if not done yet
                if not self._connection_initialized:
                    self._init_db_for_connection()
                    self._connection_initialized = True

                logger.info(f"Established DB2 connection for session {self.session_id}")

            except Exception as e:
                logger.error(f"Failed to connect to DB2: {e}")
                raise ConnectionError(f"DB2 connection failed: {e}")

        return self._connection

    def _init_db_for_connection(self):
        """Initialize database schema (tables and indexes)."""
        conn = self._connection

        try:
            # Create sessions table
            sessions_ddl = f"""
                CREATE TABLE IF NOT EXISTS {self.sessions_table} (
                    session_id VARCHAR(255) PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT TIMESTAMP
                )
            """
            ibm_db.exec_immediate(conn, sessions_ddl)

            # Create messages table
            messages_ddl = f"""
                CREATE TABLE IF NOT EXISTS {self.messages_table} (
                    id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL,
                    message_data CLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES {self.sessions_table} (session_id) ON DELETE CASCADE
                )
            """
            ibm_db.exec_immediate(conn, messages_ddl)

            # Create index for efficient queries
            index_ddl = f"""
                CREATE INDEX IF NOT EXISTS idx_{self.messages_table}_session_id 
                ON {self.messages_table} (session_id, created_at)
            """
            try:
                ibm_db.exec_immediate(conn, index_ddl)
            except Exception as e:
                # Index creation might fail if it already exists, log but don't fail
                logger.debug(f"Index creation skipped (may already exist): {e}")

            ibm_db.commit(conn)
            logger.info("Database schema initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize database schema: {e}")
            ibm_db.rollback(conn)
            raise

    def _ensure_session_exists_sync(self):
        """Ensure the session record exists in the database (synchronous)."""
        conn = self._get_connection()

        try:
            # Check if session exists
            check_sql = (
                f"SELECT session_id FROM {self.sessions_table} WHERE session_id = ?"
            )
            stmt = ibm_db.prepare(conn, check_sql)
            ibm_db.bind_param(stmt, 1, self.session_id)
            ibm_db.execute(stmt)

            result = ibm_db.fetch_tuple(stmt)

            if not result:
                # Create session record
                insert_sql = f"""
                    INSERT INTO {self.sessions_table} (session_id) 
                    VALUES (?)
                """
                stmt = ibm_db.prepare(conn, insert_sql)
                ibm_db.bind_param(stmt, 1, self.session_id)
                ibm_db.execute(stmt)
                ibm_db.commit(conn)
                logger.info(f"Created session record for {self.session_id}")

        except Exception as e:
            logger.error(f"Failed to ensure session exists: {e}")
            ibm_db.rollback(conn)
            raise

    def _get_items_sync(self, limit: Optional[int] = None) -> List[TResponseInputItem]:
        """Retrieve conversation items (synchronous implementation)."""
        conn = self._get_connection()

        try:
            if limit is None:
                # Fetch all items in chronological order
                query = f"""
                    SELECT message_data FROM {self.messages_table}
                    WHERE session_id = ?
                    ORDER BY created_at ASC
                """
                stmt = ibm_db.prepare(conn, query)
                ibm_db.bind_param(stmt, 1, self.session_id)
            else:
                # Fetch latest N items in reverse chronological order, then reverse
                query = f"""
                    SELECT message_data FROM {self.messages_table}
                    WHERE session_id = ?
                    ORDER BY created_at DESC
                    FETCH FIRST {limit} ROWS ONLY
                """
                stmt = ibm_db.prepare(conn, query)
                ibm_db.bind_param(stmt, 1, self.session_id)

            ibm_db.execute(stmt)

            items = []
            result = ibm_db.fetch_tuple(stmt)
            while result:
                try:
                    message_data = result[0]
                    item = json.loads(message_data)
                    items.append(item)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse message data: {e}")
                    # Skip invalid JSON entries
                result = ibm_db.fetch_tuple(stmt)

            # Reverse to get chronological order when using DESC with limit
            if limit is not None:
                items = list(reversed(items))

            logger.debug(f"Retrieved {len(items)} items for session {self.session_id}")
            return items

        except Exception as e:
            logger.error(f"Failed to get items: {e}")
            return []

    def _add_items_sync(self, items: List[TResponseInputItem]) -> None:
        """Add conversation items (synchronous implementation)."""
        if not items:
            return

        conn = self._get_connection()

        try:
            # Ensure session exists
            self._ensure_session_exists_sync()

            # Add items
            insert_sql = f"""
                INSERT INTO {self.messages_table} (id, session_id, message_data)
                VALUES (?, ?, ?)
            """

            for item in items:
                try:
                    message_id = str(uuid.uuid4())
                    message_json = json.dumps(item)

                    stmt = ibm_db.prepare(conn, insert_sql)
                    ibm_db.bind_param(stmt, 1, message_id)
                    ibm_db.bind_param(stmt, 2, self.session_id)
                    ibm_db.bind_param(stmt, 3, message_json)
                    ibm_db.execute(stmt)

                except Exception as e:
                    logger.error(f"Failed to add item {item}: {e}")
                    continue

            # Update session timestamp
            update_sql = f"""
                UPDATE {self.sessions_table} 
                SET updated_at = CURRENT TIMESTAMP 
                WHERE session_id = ?
            """
            stmt = ibm_db.prepare(conn, update_sql)
            ibm_db.bind_param(stmt, 1, self.session_id)
            ibm_db.execute(stmt)

            ibm_db.commit(conn)
            logger.debug(f"Added {len(items)} items to session {self.session_id}")

        except Exception as e:
            logger.error(f"Failed to add items: {e}")
            ibm_db.rollback(conn)
            raise

    def _pop_item_sync(self) -> Optional[TResponseInputItem]:
        """Remove and return most recent item (synchronous implementation)."""
        conn = self._get_connection()

        try:
            # Get the most recent item first
            select_sql = f"""
                SELECT id, message_data FROM {self.messages_table}
                WHERE session_id = ?
                ORDER BY created_at DESC
                FETCH FIRST 1 ROWS ONLY
            """
            stmt = ibm_db.prepare(conn, select_sql)
            ibm_db.bind_param(stmt, 1, self.session_id)
            ibm_db.execute(stmt)

            result = ibm_db.fetch_tuple(stmt)
            if not result:
                return None

            message_id, message_data = result

            # Parse the message data
            try:
                item = json.loads(message_data)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse message data for pop: {e}")
                return None

            # Delete the item
            delete_sql = f"DELETE FROM {self.messages_table} WHERE id = ?"
            stmt = ibm_db.prepare(conn, delete_sql)
            ibm_db.bind_param(stmt, 1, message_id)
            ibm_db.execute(stmt)

            # Update session timestamp
            update_sql = f"""
                UPDATE {self.sessions_table} 
                SET updated_at = CURRENT TIMESTAMP 
                WHERE session_id = ?
            """
            stmt = ibm_db.prepare(conn, update_sql)
            ibm_db.bind_param(stmt, 1, self.session_id)
            ibm_db.execute(stmt)

            ibm_db.commit(conn)
            logger.debug(f"Popped item from session {self.session_id}")
            return item

        except Exception as e:
            logger.error(f"Failed to pop item: {e}")
            ibm_db.rollback(conn)
            return None

    def _clear_session_sync(self) -> None:
        """Clear all items from session (synchronous implementation)."""
        conn = self._get_connection()

        try:
            # Delete all messages for this session
            delete_messages_sql = (
                f"DELETE FROM {self.messages_table} WHERE session_id = ?"
            )
            stmt = ibm_db.prepare(conn, delete_messages_sql)
            ibm_db.bind_param(stmt, 1, self.session_id)
            ibm_db.execute(stmt)

            # Delete session record
            delete_session_sql = (
                f"DELETE FROM {self.sessions_table} WHERE session_id = ?"
            )
            stmt = ibm_db.prepare(conn, delete_session_sql)
            ibm_db.bind_param(stmt, 1, self.session_id)
            ibm_db.execute(stmt)

            ibm_db.commit(conn)
            logger.info(f"Cleared all items from session {self.session_id}")

        except Exception as e:
            logger.error(f"Failed to clear session: {e}")
            ibm_db.rollback(conn)
            raise

    # Async interface methods (following SQLite session pattern)
    async def get_items(self, limit: Optional[int] = None) -> List[TResponseInputItem]:
        """
        Retrieve conversation items from the session (async)

        Args:
            limit: Maximum number of items to retrieve (None for all)

        Returns:
            List of conversation items (messages)
        """
        return await asyncio.get_event_loop().run_in_executor(
            _executor, self._get_items_sync, limit
        )

    async def add_items(self, items: List[TResponseInputItem]) -> None:
        """
        Add conversation items to the session (async)

        Args:
            items: List of conversation items to add
        """
        await asyncio.get_event_loop().run_in_executor(
            _executor, self._add_items_sync, items
        )

    async def pop_item(self) -> Optional[TResponseInputItem]:
        """
        Remove and return the most recent item from the session (async)

        Returns:
            The most recent conversation item, or None if session is empty
        """
        return await asyncio.get_event_loop().run_in_executor(
            _executor, self._pop_item_sync
        )

    async def clear_session(self) -> None:
        """Clear all items from the session (async)"""
        await asyncio.get_event_loop().run_in_executor(
            _executor, self._clear_session_sync
        )

    def close(self) -> None:
        """Close the database connection."""
        try:
            if self._connection:
                ibm_db.close(self._connection)
                self._connection = None
                self._connection_initialized = False
                logger.info(f"Closed DB2 connection for session {self.session_id}")
        except Exception as e:
            logger.error(f"Error closing DB2 connection: {e}")

    # Backward compatibility methods (for existing code that expects sync methods)
    def get_items_sync(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Synchronous version for backward compatibility."""
        return self._get_items_sync(limit)

    def add_items_sync(self, items: List[Dict[str, Any]]) -> None:
        """Synchronous version for backward compatibility."""
        self._add_items_sync(items)

    def pop_item_sync(self) -> Optional[Dict[str, Any]]:
        """Synchronous version for backward compatibility."""
        return self._pop_item_sync()

    def clear_sync(self) -> None:
        """Synchronous version for backward compatibility."""
        self._clear_session_sync()

    # Context manager support
    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close()
