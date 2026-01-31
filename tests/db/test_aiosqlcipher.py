"""Tests for async SQLCipher wrapper (aiosqlcipher module)."""

from __future__ import annotations

import builtins
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kstlib.db.aiosqlcipher import connect, is_sqlcipher_available
from kstlib.db.exceptions import EncryptionError


class TestIsSqlcipherAvailable:
    """Tests for is_sqlcipher_available function."""

    def test_returns_true_when_available(self) -> None:
        """Return True when sqlcipher3 can be imported."""
        mock_module = MagicMock()
        with patch.dict("sys.modules", {"sqlcipher3": mock_module}):
            # Force re-evaluation by importing fresh
            result = is_sqlcipher_available()
            assert result is True

    def test_returns_false_when_not_available(self) -> None:
        """Return False when sqlcipher3 import fails."""
        with patch.dict("sys.modules", {"sqlcipher3": None}):
            # Simulate ImportError by patching __import__
            original_import = builtins.__import__

            def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
                if name == "sqlcipher3":
                    raise ImportError("No module named 'sqlcipher3'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = is_sqlcipher_available()
                assert result is False


class TestConnect:
    """Tests for async connect function."""

    def test_empty_cipher_key_raises(self) -> None:
        """Raise EncryptionError when cipher_key is empty."""
        with pytest.raises(EncryptionError, match="cipher_key is required"):
            connect(":memory:", cipher_key="")

    def test_none_cipher_key_raises(self) -> None:
        """Raise EncryptionError when cipher_key is None-ish (empty string)."""
        # Note: Type hints require str, so we test empty string
        with pytest.raises(EncryptionError, match="cipher_key is required"):
            connect(":memory:", cipher_key="")

    def test_sqlcipher_not_installed_raises(self) -> None:
        """Raise EncryptionError when sqlcipher3 not installed."""
        # Simulate ImportError for sqlcipher3
        original_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "sqlcipher3":
                raise ImportError("No module named 'sqlcipher3'")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=mock_import),
            pytest.raises(EncryptionError, match="sqlcipher3 is not installed"),
        ):
            connect(":memory:", cipher_key="secret")

    def test_returns_connection_object(self) -> None:
        """Return aiosqlite Connection with custom connector."""
        # Mock both sqlcipher3 and aiosqlite.core.Connection
        mock_sqlcipher = MagicMock()
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="secret")

            # Connection class should be called with a connector function
            assert mock_connection_cls.called
            call_args = mock_connection_cls.call_args
            # First arg is the connector function, second is iter_chunk_size
            assert callable(call_args[0][0])  # connector
            assert call_args[0][1] == 64  # default iter_chunk_size

    def test_custom_iter_chunk_size(self) -> None:
        """Pass custom iter_chunk_size to Connection."""
        mock_sqlcipher = MagicMock()
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="secret", iter_chunk_size=128)

            call_args = mock_connection_cls.call_args
            assert call_args[0][1] == 128

    def test_connector_applies_cipher_key(self) -> None:
        """Connector function applies PRAGMA key with escaped quotes."""
        mock_conn = MagicMock()
        mock_conn.execute = MagicMock()
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="test'key")

            # Get the connector function and call it
            connector_fn = mock_connection_cls.call_args[0][0]
            result = connector_fn()

            # Verify PRAGMA key was called with escaped quotes
            execute_calls = [str(c) for c in mock_conn.execute.call_args_list]
            assert any("PRAGMA key" in c for c in execute_calls)
            assert any("test''key" in c for c in execute_calls)  # Escaped quote
            assert result is mock_conn

    def test_connector_verifies_key(self) -> None:
        """Connector verifies key by querying sqlite_master."""
        mock_conn = MagicMock()
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="secret")

            connector_fn = mock_connection_cls.call_args[0][0]
            connector_fn()

            # Verify sqlite_master query was executed
            execute_calls = [str(c) for c in mock_conn.execute.call_args_list]
            assert any("sqlite_master" in c for c in execute_calls)

    def test_connector_closes_on_invalid_key(self) -> None:
        """Connector closes connection and raises on invalid key."""
        mock_conn = MagicMock()
        # First call (PRAGMA key) succeeds, second (SELECT) fails
        mock_conn.execute.side_effect = [None, Exception("file is not a database")]
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="wrong-key")

            connector_fn = mock_connection_cls.call_args[0][0]

            with pytest.raises(EncryptionError, match="Invalid cipher key"):
                connector_fn()

            # Connection should be closed on failure
            assert mock_conn.close.called

    def test_connector_passes_kwargs_to_sqlcipher(self) -> None:
        """Connector passes kwargs to sqlcipher3.connect."""
        mock_conn = MagicMock()
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="secret", timeout=30.0, check_same_thread=False)

            connector_fn = mock_connection_cls.call_args[0][0]
            connector_fn()

            # Check kwargs were passed
            connect_kwargs = mock_sqlcipher.connect.call_args[1]
            assert connect_kwargs["timeout"] == 30.0
            assert connect_kwargs["check_same_thread"] is False

    def test_connector_sets_isolation_level_none_default(self) -> None:
        """Connector sets isolation_level=None by default for autocommit."""
        mock_conn = MagicMock()
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="secret")

            connector_fn = mock_connection_cls.call_args[0][0]
            connector_fn()

            connect_kwargs = mock_sqlcipher.connect.call_args[1]
            assert connect_kwargs["isolation_level"] is None

    def test_connector_allows_custom_isolation_level(self) -> None:
        """Connector allows overriding isolation_level."""
        mock_conn = MagicMock()
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(":memory:", cipher_key="secret", isolation_level="DEFERRED")

            connector_fn = mock_connection_cls.call_args[0][0]
            connector_fn()

            connect_kwargs = mock_sqlcipher.connect.call_args[1]
            assert connect_kwargs["isolation_level"] == "DEFERRED"

    def test_path_object_converted_to_string(self) -> None:
        """Path objects are converted to strings."""
        from pathlib import Path

        mock_conn = MagicMock()
        mock_sqlcipher = MagicMock()
        mock_sqlcipher.connect.return_value = mock_conn
        mock_connection_cls = MagicMock()

        test_path = Path("test_db_file.db")

        with (
            patch.dict("sys.modules", {"sqlcipher3": mock_sqlcipher}),
            patch("aiosqlite.core.Connection", mock_connection_cls),
        ):
            connect(test_path, cipher_key="secret")

            connector_fn = mock_connection_cls.call_args[0][0]
            connector_fn()

            # First positional arg to connect should be string
            connect_args = mock_sqlcipher.connect.call_args[0]
            assert connect_args[0] == str(test_path)
            assert isinstance(connect_args[0], str)
