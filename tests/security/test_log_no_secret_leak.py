"""Cross-module smoke test : no secret marker leaks through any log path.

This module exercises the four HIGH gap fix points landed at the start
of v2.5.0-log-impl (auth callback, websocket connect, pipeline base
subprocess stderr, pipeline shell/python command-line args) and asserts
that synthetic credential markers never appear in the captured log
stream.

The test acts as a regression suite : if a future contributor reverts
or weakens any of the redactions, the corresponding assertion fails
and surfaces the leak before it reaches users.
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock

import pytest

from kstlib.auth.callback import CallbackHandler
from kstlib.pipeline.models import StepConfig, StepStatus, StepType
from kstlib.pipeline.steps.python import PythonStep
from kstlib.pipeline.steps.shell import ShellStep

# Synthetic credential markers used across all assertions. Each marker is a
# unique recognizable string so that a single grep can confirm absence.
_OAUTH_CODE = "4_FakeOAuthCode_supersecret_xyz789"
_WS_USERINFO_PASS = "FakeWsBasicPwd_abc123"
_WS_QUERY_TOKEN = "FakeWsQueryToken_def456"
_SHELL_BEARER = "sk_live_FakeShellBearer_ghi789"
_SHELL_PWD_FLAG = "FakeShellPwdFlag_jkl012"
_SUBPROCESS_STDERR_PWD = "FakeStderrPwd_mno345"
_PYTHON_TOKEN = "FakePythonToken_pqr678"


@pytest.fixture
def all_kstlib_caplog(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture every log record from the kstlib hierarchy at TRACE level."""
    caplog.set_level(logging.NOTSET, logger="kstlib")
    return caplog


def _assert_no_marker(caplog: pytest.LogCaptureFixture, marker: str) -> None:
    """Assert the marker never appears in any captured log message."""
    for record in caplog.records:
        msg = record.getMessage()
        assert marker not in msg, (
            f"Secret marker {marker!r} leaked into log ({record.name} / {record.levelname}): {msg!r}"
        )


class TestNoSecretLeakRegression:
    """Synthetic exercise of the four HIGH gap fix points."""

    def test_auth_callback_does_not_leak_oauth_code(
        self,
        all_kstlib_caplog: pytest.LogCaptureFixture,
    ) -> None:
        """CallbackHandler.log_message must not forward the OAuth code."""
        handler = CallbackHandler.__new__(CallbackHandler)
        handler.log_message(
            '"%s" %s %s',
            f"GET /callback?code={_OAUTH_CODE}&state=xyz HTTP/1.1",
            "200",
            "-",
        )
        _assert_no_marker(all_kstlib_caplog, _OAUTH_CODE)

    @pytest.mark.asyncio
    async def test_websocket_connect_does_not_leak_url_credentials(
        self,
        all_kstlib_caplog: pytest.LogCaptureFixture,
    ) -> None:
        """WebSocketManager._finalize_connection must redact URL credentials and tokens."""
        try:
            from kstlib.websocket import WebSocketManager
        except ImportError:
            pytest.skip("websockets package not installed")

        url = f"wss://user:{_WS_USERINFO_PASS}@host.example.com:8443/ws?token={_WS_QUERY_TOKEN}"
        ws = WebSocketManager(url)
        ws._on_connect = None
        ws._subscriptions = {}
        ws._start_background_tasks = MagicMock()

        await ws._finalize_connection()

        _assert_no_marker(all_kstlib_caplog, _WS_USERINFO_PASS)
        _assert_no_marker(all_kstlib_caplog, _WS_QUERY_TOKEN)

    def test_shell_step_does_not_leak_authorization_header(
        self,
        all_kstlib_caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ShellStep DEBUG / dry_run INFO must redact Authorization Bearer tokens."""
        step = ShellStep()
        config = StepConfig(
            name="leak-bearer",
            type=StepType.SHELL,
            command=f"curl -H 'Authorization: Bearer {_SHELL_BEARER}' https://api.example.com",
        )
        result = step.execute(config, dry_run=True)
        assert result.status == StepStatus.SKIPPED
        assert _SHELL_BEARER not in result.stdout
        _assert_no_marker(all_kstlib_caplog, _SHELL_BEARER)

    def test_shell_step_does_not_leak_password_flag(
        self,
        all_kstlib_caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ShellStep DEBUG must redact --password=<value>."""
        step = ShellStep()
        config = StepConfig(
            name="leak-pwd",
            type=StepType.SHELL,
            command=f"echo OK --password={_SHELL_PWD_FLAG}",
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        _assert_no_marker(all_kstlib_caplog, _SHELL_PWD_FLAG)

    def test_subprocess_failure_does_not_leak_stderr(
        self,
        all_kstlib_caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ShellStep failure WARNING must drop subprocess stderr.

        The marker is injected into the subprocess via ``env:`` so that
        the shell command line itself never contains it. This isolates
        the regression to the stderr-drop fix (gap 2.3): if stderr
        forwarding ever returns to the WARNING log, the marker would
        appear there and only there.
        """
        step = ShellStep()
        cmd = (
            f'{sys.executable} -c "import os, sys; '
            "sys.stderr.write('auth failed for user: ' + os.environ['LEAK_PROBE'] + '\\n'); "
            'sys.exit(7)"'
        )
        config = StepConfig(
            name="leak-stderr",
            type=StepType.SHELL,
            command=cmd,
            env={"LEAK_PROBE": _SUBPROCESS_STDERR_PWD},
        )
        result = step.execute(config)
        assert result.status == StepStatus.FAILED
        # The marker is intentionally preserved on the result for deliberate
        # inspection by the caller, but must NOT appear in any log record.
        assert result.error is not None
        assert _SUBPROCESS_STDERR_PWD in result.error
        _assert_no_marker(all_kstlib_caplog, _SUBPROCESS_STDERR_PWD)

    def test_python_step_does_not_leak_token_arg(
        self,
        all_kstlib_caplog: pytest.LogCaptureFixture,
    ) -> None:
        """PythonStep DEBUG dry_run must redact --token <value>."""
        step = PythonStep()
        config = StepConfig(
            name="leak-token",
            type=StepType.PYTHON,
            module="platform",
            args=("--token", _PYTHON_TOKEN),
        )
        result = step.execute(config, dry_run=True)
        assert result.status == StepStatus.SKIPPED
        assert _PYTHON_TOKEN not in result.stdout
        _assert_no_marker(all_kstlib_caplog, _PYTHON_TOKEN)
