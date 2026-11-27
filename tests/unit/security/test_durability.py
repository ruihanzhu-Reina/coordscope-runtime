"""Actual process exits exercise durable uncertainty and receipt replay."""

import json
import subprocess
import sys

import pytest

from .gateway_helpers import PAY, make


def test_restart_replays_persisted_receipt_without_reexecuting(tmp_path):
    calls = []
    path = tmp_path / "task.db"
    with make(path, handler=lambda args: calls.append(args) or dict(ok=True, reference="receipt-1")) as g:
        first = g.call("agent_0", "pay", PAY)
    with make(path, handler=lambda args: calls.append(args) or dict(ok=True)) as restored:
        replay = restored.call("agent_0", "pay", PAY)
        assert replay["already_applied"]
        assert replay["evidence_id"] == first["evidence_id"]
        assert json.loads(replay["content"])["reference"] == "receipt-1"
    assert calls == [PAY]


def test_process_crash_after_external_effect_never_automatically_retries(tmp_path):
    path, effect = tmp_path / "task.db", tmp_path / "effect.txt"
    code = """
import os, sys
from pathlib import Path
from tests.unit.security.gateway_helpers import make, PAY
def effect(args):
    path=Path(sys.argv[2])
    with path.open('a') as stream:
        stream.write('effect\\n'); stream.flush(); os.fsync(stream.fileno())
    os._exit(23)
with make(sys.argv[1],handler=effect) as g:
    g.call('agent_0','pay',PAY)
"""
    child = subprocess.run([sys.executable, "-c", code, str(path), str(effect)], capture_output=True, timeout=30)
    assert child.returncode == 23, child.stderr.decode(errors="replace")
    calls = []
    with make(path, handler=lambda args: calls.append(args) or dict(ok=True)) as g:
        assert g.snapshot()["operations"][0]["state"] == "unknown"
        assert g.call("agent_0", "pay", PAY)["error"] == "ACTION_BLOCKED"
        operation = g.snapshot()["operations"][0]
        g.reconcile(operation["id"], "committed", dict(ok=True, reference="external-reconciliation"))
        assert g.call("agent_0", "pay", PAY)["already_applied"]
    assert calls == []
    assert effect.read_text().splitlines() == ["effect"]


def test_known_not_applied_releases_budget_only_after_host_reconciliation(tmp_path):
    with make(tmp_path / "task.db", handler=lambda _: dict(ok=False)) as g:
        g.call("agent_0", "pay", PAY)
        operation = g.snapshot()["operations"][0]
        g.reconcile(operation["id"], "not_applied")
        g.tools["pay"]["handler"] = lambda _: dict(ok=True)
        assert "error" not in g.call("agent_0", "pay", PAY)
        assert g.snapshot()["operations"][0]["state"] == "committed"
        with pytest.raises(ValueError, match="Only unknown"):
            g.reconcile(operation["id"], "not_applied")


@pytest.mark.parametrize("changed", [dict(task_id="other"), dict(user_request="Pay Mallory")])
def test_task_identity_and_user_request_cannot_be_rebound(tmp_path, changed):
    path = tmp_path / "task.db"
    with make(path):
        pass
    with pytest.raises(ValueError, match="does not match"):
        make(path, **changed)


def test_policy_change_cannot_refresh_grant_budget(tmp_path):
    path = tmp_path / "task.db"
    with make(path):
        pass
    with pytest.raises(ValueError, match="does not match"):
        make(path, actions=[])


def test_live_owner_excludes_second_process(tmp_path):
    path = tmp_path / "task.db"
    with make(path):
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from tests.unit.security.gateway_helpers import make; make(sys.argv[1])",
                str(path),
            ],
            capture_output=True,
            timeout=30,
        )
        assert child.returncode != 0
        assert b"active owner" in child.stderr


def test_pending_reservation_survives_owner_recovery(tmp_path):
    path = tmp_path / "task.db"
    with make(path) as g:
        g.journal.reserve("host-step", g.policy.grants[0], "pay", PAY, dict(reads=[], writes=["account:Alice"]))
    with make(path) as g:
        assert g.snapshot()["operations"][0]["state"] == "unknown"
        assert g.call("agent_0", "pay", PAY)["error"] == "ACTION_BLOCKED"


def test_semantically_identical_policy_order_can_reopen_journal(tmp_path):
    path = tmp_path / "task.db"
    actions = [dict(tool="pay", arguments=PAY), dict(tool="pay", arguments=PAY | dict(recipient="Bob"))]
    with make(path, actions=actions) as g:
        g.call("agent_0", "pay", PAY)
    with make(path, actions=list(reversed(actions))) as g:
        assert g.call("agent_0", "pay", PAY)["already_applied"]
