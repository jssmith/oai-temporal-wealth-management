"""
DB2 Session Activities for Temporal Workflows

Provides activity wrappers for DB2Session operations, allowing workflows
to persist conversation history without blocking on database operations.
"""

from typing import List, Optional, Dict, Any
from temporalio import activity

from src.common.db2_session import DB2Session
from src.common.db2_config import DB2Config


class DB2SessionActivities:
    """
    Activity class for DB2 session operations.
    
    Each activity creates a DB2Session instance, performs the operation,
    and closes the connection. This ensures database operations are
    properly isolated in activities per Temporal best practices.
    """

    @staticmethod
    @activity.defn
    async def get_items(
        session_id: str,
        config: Optional[DB2Config] = None,
        limit: Optional[int] = None,
        sessions_table: str = "agent_sessions",
        messages_table: str = "agent_messages"
    ) -> List[Dict[str, Any]]:
        """
        Retrieve conversation items from DB2 session.
        
        Args:
            session_id: Unique session identifier
            config: DB2 connection configuration (None to read from env vars)
            limit: Maximum number of items to retrieve (None for all)
            sessions_table: Name of the sessions table
            messages_table: Name of the messages table
            
        Returns:
            List of conversation items (messages)
        """
        activity.logger.info(f"get_items: Retrieving items for session {session_id} (limit={limit})")
        
        # Create config from environment variables if not provided
        # This allows activities to safely read environment variables
        db2_config = config or DB2Config()
        
        session = DB2Session(
            session_id=session_id,
            config=db2_config,
            sessions_table=sessions_table,
            messages_table=messages_table
        )
        
        try:
            items = await session.get_items(limit=limit)
            activity.logger.info(f"get_items: Retrieved {len(items)} items")
            return items
        finally:
            session.close()

    @staticmethod
    @activity.defn
    async def add_items(
        session_id: str,
        config: Optional[DB2Config] = None,
        items: List[Dict[str, Any]] = None,
        sessions_table: str = "agent_sessions",
        messages_table: str = "agent_messages"
    ) -> None:
        """
        Add conversation items to DB2 session.
        
        Args:
            session_id: Unique session identifier
            config: DB2 connection configuration (None to read from env vars)
            items: List of conversation items to add
            sessions_table: Name of the sessions table
            messages_table: Name of the messages table
        """
        if items is None:
            items = []
            
        activity.logger.info(f"add_items: Adding {len(items)} items to session {session_id}")
        
        # Create config from environment variables if not provided
        db2_config = config or DB2Config()
        
        session = DB2Session(
            session_id=session_id,
            config=db2_config,
            sessions_table=sessions_table,
            messages_table=messages_table
        )
        
        try:
            await session.add_items(items)
            activity.logger.info(f"add_items: Successfully added items")
        finally:
            session.close()

    @staticmethod
    @activity.defn
    async def pop_item(
        session_id: str,
        config: Optional[DB2Config] = None,
        sessions_table: str = "agent_sessions",
        messages_table: str = "agent_messages"
    ) -> Optional[Dict[str, Any]]:
        """
        Remove and return the most recent item from DB2 session.
        
        Args:
            session_id: Unique session identifier
            config: DB2 connection configuration (None to read from env vars)
            sessions_table: Name of the sessions table
            messages_table: Name of the messages table
            
        Returns:
            The most recent conversation item, or None if session is empty
        """
        activity.logger.info(f"pop_item: Popping item from session {session_id}")
        
        # Create config from environment variables if not provided
        db2_config = config or DB2Config()
        
        session = DB2Session(
            session_id=session_id,
            config=db2_config,
            sessions_table=sessions_table,
            messages_table=messages_table
        )
        
        try:
            item = await session.pop_item()
            activity.logger.info(f"pop_item: Popped item: {item is not None}")
            return item
        finally:
            session.close()

    @staticmethod
    @activity.defn
    async def clear_session(
        session_id: str,
        config: Optional[DB2Config] = None,
        sessions_table: str = "agent_sessions",
        messages_table: str = "agent_messages"
    ) -> None:
        """
        Clear all items from DB2 session.
        
        Args:
            session_id: Unique session identifier
            config: DB2 connection configuration (None to read from env vars)
            sessions_table: Name of the sessions table
            messages_table: Name of the messages table
        """
        activity.logger.info(f"clear_session: Clearing session {session_id}")
        
        # Create config from environment variables if not provided
        db2_config = config or DB2Config()
        
        session = DB2Session(
            session_id=session_id,
            config=db2_config,
            sessions_table=sessions_table,
            messages_table=messages_table
        )
        
        try:
            await session.clear_session()
            activity.logger.info(f"clear_session: Session cleared successfully")
        finally:
            session.close()




