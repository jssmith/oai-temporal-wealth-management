"""
Temporal-safe DB2 Session Wrapper

Provides a drop-in replacement for DB2Session that works in Temporal workflows
by delegating all database operations to activities.

This allows workflows to persist conversation history without blocking on
database operations, following Temporal best practices.
"""

from typing import List, Optional
from datetime import timedelta

from temporalio import workflow
from agents.memory import SessionABC
from agents.items import TResponseInputItem

from src.common.db2_config import DB2Config
from src.temporal.activities.db2_session_activities import DB2SessionActivities


class TemporalDB2Session(SessionABC):
    """
    Temporal-safe DB2 session implementation for OpenAI Agents SDK.

    Implements the SessionABC interface but delegates all operations to
    Temporal activities. This enables conversation history persistence
    in workflows without blocking on database operations.

    Usage:
        session = TemporalDB2Session(
            session_id="conversation_123",
            config=DB2Config(...)
        )

        result = await Runner.run(
            agent,
            "What is the weather?",
            session=session
        )
    """

    def __init__(
        self,
        session_id: str,
        config: Optional[DB2Config] = None,
        sessions_table: str = "agent_sessions",
        messages_table: str = "agent_messages",
        activity_timeout: timedelta = timedelta(seconds=10),
    ):
        """
        Initialize Temporal DB2 session.

        Args:
            session_id: Unique identifier for this session
            config: DB2 connection configuration (DEPRECATED: pass None to let activities read from env)
            sessions_table: Name of the sessions table (default: agent_sessions)
            messages_table: Name of the messages table (default: agent_messages)
            activity_timeout: Timeout for activity execution
        """
        self.session_id = session_id
        self.config = (
            config  # Will be None, activities will create config from env vars
        )
        self.sessions_table = sessions_table
        self.messages_table = messages_table
        self.activity_timeout = activity_timeout

    async def get_items(self, limit: Optional[int] = None) -> List[TResponseInputItem]:
        """
        Retrieve conversation items from the session.

        Args:
            limit: Maximum number of items to retrieve (None for all)

        Returns:
            List of conversation items (messages)
        """
        items = await workflow.execute_activity(
            DB2SessionActivities.get_items,
            args=[
                self.session_id,
                self.config,
                limit,
                self.sessions_table,
                self.messages_table,
            ],
            start_to_close_timeout=self.activity_timeout,
        )
        return items

    async def add_items(self, items: List[TResponseInputItem]) -> None:
        """
        Add conversation items to the session.

        Args:
            items: List of conversation items to add
        """
        if not items:
            return

        await workflow.execute_activity(
            DB2SessionActivities.add_items,
            args=[
                self.session_id,
                self.config,
                items,
                self.sessions_table,
                self.messages_table,
            ],
            start_to_close_timeout=self.activity_timeout,
        )

    async def pop_item(self) -> Optional[TResponseInputItem]:
        """
        Remove and return the most recent item from the session.

        Returns:
            The most recent conversation item, or None if session is empty
        """
        item = await workflow.execute_activity(
            DB2SessionActivities.pop_item,
            args=[
                self.session_id,
                self.config,
                self.sessions_table,
                self.messages_table,
            ],
            start_to_close_timeout=self.activity_timeout,
        )
        return item

    async def clear_session(self) -> None:
        """Clear all items from the session."""
        await workflow.execute_activity(
            DB2SessionActivities.clear_session,
            args=[
                self.session_id,
                self.config,
                self.sessions_table,
                self.messages_table,
            ],
            start_to_close_timeout=self.activity_timeout,
        )
