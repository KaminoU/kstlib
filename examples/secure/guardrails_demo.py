"""Show how filesystem guardrails accept safe paths and block traversal attempts."""

from __future__ import annotations

from pathlib import Path

from kstlib.secure import RELAXED_POLICY, PathGuardrails, PathSecurityError


def build_workspace(root: Path) -> None:
    """Populate a sandbox with a small report file for the demo."""
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    report_file = reports / "daily.txt"
    report_file.write_text("Daily conversions: 42", encoding="utf-8")


def guardrails_demo() -> None:
    """Resolve a safe file and demonstrate how traversal is denied."""
    workspace = Path(__file__).with_name("workspace")
    guard = PathGuardrails(workspace, policy=RELAXED_POLICY)
    build_workspace(guard.root)

    safe_report = guard.resolve_file("reports/daily.txt")
    print(f"Report lives at: {safe_report}")

    try:
        guard.resolve_file("../etc/passwd")
    except PathSecurityError as exc:
        print(f"Traversal blocked: {exc}")


if __name__ == "__main__":  # pragma: no cover - manual example
    guardrails_demo()
