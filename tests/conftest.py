import subprocess

import pytest


@pytest.fixture(autouse=True)
def _no_real_os_side_effects(monkeypatch):
    """Tests never touch the real launchctl / schtasks / crontab or show notifications."""

    def no_scheduler(args, input=None):
        return subprocess.CompletedProcess(args, 1, b"", b"not found (test stub)")

    monkeypatch.setattr("agent_history.schedule._run", no_scheduler)
    monkeypatch.setattr("agent_history.cli.notify", lambda title, message: None)
