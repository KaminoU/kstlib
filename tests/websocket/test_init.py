"""Tests for kstlib.websocket package initialization."""

from __future__ import annotations

import pytest

from kstlib import websocket


class TestWebSocketInit:
    """Tests for websocket package __init__.py."""

    def test_lazy_import_websocket_manager(self) -> None:
        """WebSocketManager should be accessible via lazy import."""
        assert hasattr(websocket, "WebSocketManager")
        # Access triggers lazy import
        manager_class = websocket.WebSocketManager
        assert manager_class.__name__ == "WebSocketManager"

    def test_invalid_attribute_raises_error(self) -> None:
        """Accessing invalid attribute should raise AttributeError."""
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = websocket.invalid_attribute_name

    def test_all_exports_accessible(self) -> None:
        """All __all__ exports should be accessible."""
        expected = [
            "ConnectionState",
            "DisconnectReason",
            "ReconnectStrategy",
            "WebSocketClosedError",
            "WebSocketConnectionError",
            "WebSocketError",
            "WebSocketManager",
            "WebSocketProtocolError",
            "WebSocketQueueFullError",
            "WebSocketReconnectError",
            "WebSocketStats",
            "WebSocketTimeoutError",
        ]
        for name in expected:
            assert hasattr(websocket, name), f"Missing export: {name}"
