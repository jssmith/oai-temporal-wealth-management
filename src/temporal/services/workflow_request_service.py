"""
Request service for handling async request/response coordination between
update handlers and the workflow run loop.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from temporalio import workflow

from common.user_message import ProcessUserMessageInput, ProcessUserMessageResponse


@dataclass
class PendingRequest:
    """Represents a pending request that's waiting for processing."""

    message: ProcessUserMessageInput
    _response_future: Optional[asyncio.Future] = None

    def __post_init__(self):
        """Initialize the response future."""
        self._response_future = asyncio.Future()

    async def wait_for_response(self) -> "ProcessUserMessageResponse":
        """Wait for the request to be completed and return the response."""
        return await self._response_future

    def complete(self, response: "ProcessUserMessageResponse"):
        """Complete the request with the given response."""
        if not self._response_future.done():
            self._response_future.set_result(response)

    def error(self, exception: Exception):
        """Complete the request with an error."""
        if not self._response_future.done():
            self._response_future.set_exception(exception)


class WorkflowRequestService:
    """
    Service for managing async request/response coordination between
    update handlers and the workflow run loop.

    Update handlers call do_request() to queue a request and wait for response.
    The workflow run loop calls next_request() to get requests to process.
    """

    def __init__(self):
        """Initialize the request service."""
        self._pending_requests: asyncio.Queue[PendingRequest] = asyncio.Queue()
        self._active_request: Optional[PendingRequest] = None

    async def do_request(
        self, message: ProcessUserMessageInput
    ) -> "ProcessUserMessageResponse":
        """
        Queue a request and wait for it to be processed.
        Called from update handlers.

        Args:
            message: The user message to process

        Returns:
            The response from processing the message
        """
        workflow.logger.info(f"Queueing request: {message.user_input}")
        request = PendingRequest(message=message)
        await self._pending_requests.put(request)
        workflow.logger.info("Request queued, waiting for response")
        return await request.wait_for_response()

    async def next_request(self) -> PendingRequest:
        """
        Get the next request to process.
        Called from the workflow run loop.

        Returns:
            The next pending request
        """
        workflow.logger.info("Waiting for next request from queue")
        self._active_request = await self._pending_requests.get()
        workflow.logger.info(f"Got request: {self._active_request.message.user_input}")
        return self._active_request

    def is_empty(self) -> bool:
        """Check if there are no pending requests."""
        return self._pending_requests.empty()

    def has_requests(self) -> bool:
        """Check if there are pending requests."""
        return not self._pending_requests.empty()
