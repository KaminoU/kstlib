"""Tests for the ops data models."""

from __future__ import annotations

from kstlib.ops.models import BackendType, SessionState, SessionStatus


class TestSessionState:
    """Tests for SessionState enum."""

    def test_session_state_defined_value(self) -> None:
        """SessionState.DEFINED has value 'defined'."""
        assert SessionState.DEFINED.value == "defined"

    def test_session_state_defined_is_str(self) -> None:
        """SessionState.DEFINED is a string enum member."""
        assert isinstance(SessionState.DEFINED, str)
        # str(Enum) returns "ClassName.MEMBER" in Python 3.11+, .value is reliable
        assert SessionState.DEFINED.value == "defined"


class TestSessionStatusWithDefined:
    """Tests for SessionStatus with DEFINED state."""

    def test_session_status_with_defined_state(self) -> None:
        """SessionStatus accepts state DEFINED."""
        status = SessionStatus(
            name="myapp",
            state=SessionState.DEFINED,
            backend=BackendType.TMUX,
        )
        assert status.state == SessionState.DEFINED
        assert status.name == "myapp"
        assert status.pid is None

    def test_session_status_defined_with_image(self) -> None:
        """SessionStatus DEFINED can include image info."""
        status = SessionStatus(
            name="myapp",
            state=SessionState.DEFINED,
            backend=BackendType.CONTAINER,
            image="myapp:latest",
        )
        assert status.image == "myapp:latest"
        assert status.backend == BackendType.CONTAINER
