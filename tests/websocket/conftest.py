"""Pytest fixtures for WebSocket tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class MockWebSocket:
    """Mock WebSocket connection for testing."""

    def __init__(self) -> None:
        """Initialize mock WebSocket."""
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str = ""
        self._messages: asyncio.Queue[str] = asyncio.Queue()
        self._on_close: asyncio.Event = asyncio.Event()

    async def send(self, message: str) -> None:
        """Mock send method."""
        if self.closed:
            from websockets.exceptions import ConnectionClosed

            raise ConnectionClosed(None, None)

    async def recv(self) -> str:
        """Mock recv method."""
        from websockets.exceptions import ConnectionClosed

        while True:
            if self.closed:
                raise ConnectionClosed(None, None)

            try:
                # Wait for message with timeout
                msg = await asyncio.wait_for(self._messages.get(), timeout=0.1)
                return msg
            except asyncio.TimeoutError:
                # Loop continues to check if closed
                pass

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Mock close method."""
        self.closed = True
        self.close_code = code
        self.close_reason = reason
        self._on_close.set()

    def add_message(self, message: str) -> None:
        """Add a message to be received."""
        self._messages.put_nowait(message)

    async def __aiter__(self) -> AsyncIterator[str]:
        """Iterate over messages."""
        while not self.closed:
            try:
                yield await self.recv()
            except Exception:
                break


@pytest.fixture
def mock_websocket() -> MockWebSocket:
    """Create a mock WebSocket connection."""
    return MockWebSocket()


@pytest.fixture
def mock_connect(mock_websocket: MockWebSocket) -> MagicMock:
    """Create a mock connect function."""

    async def _connect(*args: Any, **kwargs: Any) -> MockWebSocket:
        return mock_websocket

    return AsyncMock(side_effect=_connect)


@pytest.fixture
def websockets_installed() -> bool:
    """Check if websockets is installed."""
    try:
        import websockets  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture
def skip_without_websockets(websockets_installed: bool) -> None:
    """Skip test if websockets is not installed."""
    if not websockets_installed:
        pytest.skip("websockets not installed")
