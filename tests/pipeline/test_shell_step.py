"""Tests for the kstlib.pipeline.steps.shell module."""

from __future__ import annotations

import logging
import sys

import pytest

from kstlib.pipeline.models import StepConfig, StepStatus, StepType
from kstlib.pipeline.steps.shell import ShellStep


class TestShellStepExecute:
    """Tests for ShellStep.execute method."""

    def test_simple_echo(self) -> None:
        """Execute a simple echo command."""
        step = ShellStep()
        config = StepConfig(
            name="greet",
            type=StepType.SHELL,
            command="echo hello",
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert "hello" in result.stdout
        assert result.return_code == 0
        assert result.duration > 0

    def test_command_with_stderr(self) -> None:
        """Capture stderr from command."""
        step = ShellStep()
        cmd = f"{sys.executable} -c \"import sys; sys.stderr.write('warn\\n')\""
        config = StepConfig(
            name="warn",
            type=StepType.SHELL,
            command=cmd,
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert "warn" in result.stderr

    def test_failing_command(self) -> None:
        """Handle non-zero exit code."""
        step = ShellStep()
        cmd = f'{sys.executable} -c "import sys; sys.exit(1)"'
        config = StepConfig(
            name="fail",
            type=StepType.SHELL,
            command=cmd,
        )
        result = step.execute(config)
        assert result.status == StepStatus.FAILED
        assert result.return_code == 1

    def test_timeout(self) -> None:
        """Handle command timeout."""
        step = ShellStep()
        cmd = f'{sys.executable} -c "import time; time.sleep(10)"'
        config = StepConfig(
            name="slow",
            type=StepType.SHELL,
            command=cmd,
            timeout=0.5,
        )
        result = step.execute(config)
        assert result.status == StepStatus.TIMEOUT
        assert result.error is not None
        assert "Timed out" in result.error

    def test_with_env(self) -> None:
        """Pass environment variables to command."""
        step = ShellStep()
        cmd = f"{sys.executable} -c \"import os; print(os.environ['TEST_VAR'])\""
        config = StepConfig(
            name="env-test",
            type=StepType.SHELL,
            command=cmd,
            env={"TEST_VAR": "hello_pipeline"},
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert "hello_pipeline" in result.stdout

    def test_dry_run(self) -> None:
        """Dry run does not execute the command."""
        step = ShellStep()
        config = StepConfig(
            name="dangerous",
            type=StepType.SHELL,
            command="echo should_not_run",
        )
        result = step.execute(config, dry_run=True)
        assert result.status == StepStatus.SKIPPED
        assert "dry-run" in result.stdout
        assert "should_not_run" in result.stdout

    def test_multiline_command(self) -> None:
        """Execute multi-line command string."""
        step = ShellStep()
        cmd = f"{sys.executable} -c \"print('line1'); print('line2')\""
        config = StepConfig(
            name="multi",
            type=StepType.SHELL,
            command=cmd,
        )
        result = step.execute(config)
        assert result.status == StepStatus.SUCCESS
        assert "line1" in result.stdout
        assert "line2" in result.stdout

    def test_invalid_working_dir(self) -> None:
        """Handle invalid working directory."""
        step = ShellStep()
        config = StepConfig(
            name="bad-dir",
            type=StepType.SHELL,
            command="echo hello",
            working_dir="/nonexistent/path/that/does/not/exist",
        )
        result = step.execute(config)
        assert result.status == StepStatus.FAILED
        assert result.error is not None

    def test_error_message_on_failure(self) -> None:
        """Capture error message from failing command."""
        step = ShellStep()
        cmd = f"{sys.executable} -c \"import sys; sys.stderr.write('error msg\\n'); sys.exit(2)\""
        config = StepConfig(
            name="error",
            type=StepType.SHELL,
            command=cmd,
        )
        result = step.execute(config)
        assert result.status == StepStatus.FAILED
        assert result.return_code == 2
        assert result.error is not None
        assert "error msg" in result.error

    def test_command_log_does_not_leak_password_flag(self, caplog: pytest.LogCaptureFixture) -> None:
        """ShellStep DEBUG log redacts --password=<value> via _sanitize_command."""
        step = ShellStep()
        secret_marker = "Pa55wDFakeSeCret!"
        config = StepConfig(
            name="leak-flag",
            type=StepType.SHELL,
            command=f"echo OK --password={secret_marker}",
        )

        caplog.set_level(logging.DEBUG, logger="kstlib.pipeline.steps.shell")
        result = step.execute(config)

        assert result.status == StepStatus.SUCCESS
        for record in caplog.records:
            assert secret_marker not in record.getMessage()

    def test_dry_run_log_does_not_leak_authorization(self, caplog: pytest.LogCaptureFixture) -> None:
        """ShellStep dry_run INFO log redacts Authorization header tokens."""
        step = ShellStep()
        secret_marker = "sk_live_FakeBearerToken_xyz"
        config = StepConfig(
            name="leak-dryrun",
            type=StepType.SHELL,
            command=f"curl -H 'Authorization: Bearer {secret_marker}' https://api.example.com",
        )

        caplog.set_level(logging.INFO, logger="kstlib.pipeline.steps.shell")
        result = step.execute(config, dry_run=True)

        assert result.status == StepStatus.SKIPPED
        assert secret_marker not in result.stdout
        for record in caplog.records:
            assert secret_marker not in record.getMessage()

    def test_failure_log_does_not_leak_stderr(self, caplog: pytest.LogCaptureFixture) -> None:
        """Subprocess stderr must NOT appear in the WARNING log on failure.

        User shell commands may carry credentials in stderr (curl error
        echoing the URL, sshpass auth failure, psql connection string).
        We log a generic failure message and keep the full stderr in
        StepResult.stderr / StepResult.error for deliberate inspection.
        """
        step = ShellStep()
        secret_marker = "Pa55wDFakeSeCret!"
        cmd = (
            f'{sys.executable} -c "import sys; '
            f"sys.stderr.write('auth failed for user: {secret_marker}\\n'); "
            'sys.exit(7)"'
        )
        config = StepConfig(
            name="leak-check",
            type=StepType.SHELL,
            command=cmd,
        )

        caplog.set_level(logging.WARNING, logger="kstlib.pipeline.steps._base")
        result = step.execute(config)

        assert result.status == StepStatus.FAILED
        assert result.error is not None
        assert secret_marker in result.error
        for record in caplog.records:
            assert secret_marker not in record.getMessage()
