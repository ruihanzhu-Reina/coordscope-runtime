"""Deterministic authorization and frozen dispatch payload regressions."""

import threading

import pytest

from .gateway_helpers import PAY, make


def test_host_exact_policy_rejects_substitution_without_model(tmp_path):
    calls = []
    with make(tmp_path / "task.db", handler=lambda args: calls.append(args) or dict(ok=True)) as g:
        assert g.call("agent_0", "pay", PAY | dict(amount=1000))["error"] == "ACTION_BLOCKED"
        g.call("agent_0", "pay", PAY)
        assert g.call("agent_0", "pay", PAY)["already_applied"]
        assert calls == [PAY]


def test_empty_policy_and_role_boundary_fail_closed(tmp_path):
    calls = []
    with make(tmp_path / "task.db", actions=[], handler=lambda args: calls.append(args)) as g:
        assert g.call("agent_0", "pay", PAY)["error"] == "ACTION_BLOCKED"
        assert g.call("unissued_actor", "lookup", dict(user="alice"))["error"] == "ACTION_BLOCKED"
        assert calls == []


@pytest.mark.parametrize("amount", [True, 1.5, "10", -1])
def test_full_schema_validation_precedes_dispatch(tmp_path, amount):
    with make(tmp_path / "task.db") as g:
        assert g.call("agent_0", "pay", PAY | dict(amount=amount))["error"] == "ACTION_BLOCKED"
        assert g.snapshot()["operations"] == []


def test_argument_mutation_in_handler_does_not_rewrite_authorization(tmp_path):
    original = dict(PAY)

    def mutate(args):
        args["recipient"] = "Changed"
        return dict(ok=True)

    with make(tmp_path / "task.db", handler=mutate) as g:
        g.call("agent_0", "pay", original)
        assert original == PAY
        assert g.snapshot()["operations"][0]["arguments"] == PAY


def test_concurrent_identical_calls_dispatch_once(tmp_path):
    calls, results = [], []
    with make(tmp_path / "task.db", handler=lambda args: calls.append(args) or dict(ok=True)) as g:
        threads = [threading.Thread(target=lambda: results.append(g.call("agent_0", "pay", PAY))) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads)
        assert len(results) == 4
        assert calls == [PAY]


@pytest.mark.parametrize("failure", [dict(error="ambiguous"), dict(ok=False), dict(success=False)])
def test_ambiguous_effect_is_unknown_and_blocks_conflicting_calls(tmp_path, failure):
    with make(tmp_path / "task.db", handler=lambda _: failure) as g:
        g.call("agent_0", "pay", PAY)
        assert g.snapshot()["operations"][0]["state"] == "unknown"
        assert g.call("agent_0", "pay", PAY)["error"] == "ACTION_BLOCKED"


def test_recording_failure_after_effect_remains_unknown(tmp_path, monkeypatch):
    calls = []
    with make(tmp_path / "task.db", handler=lambda args: calls.append(args) or dict(ok=True)) as g:
        monkeypatch.setattr(g.store, "add", lambda *a, **kw: (_ for _ in ()).throw(ValueError("receipt failure")))
        with pytest.raises(ValueError, match="receipt failure"):
            g.call("agent_0", "pay", PAY)
        assert calls == [PAY]
        assert g.snapshot()["operations"][0]["state"] == "unknown"


def test_missing_host_effect_rejected(tmp_path):
    from .gateway_helpers import tools

    catalog = tools()
    catalog[0].pop("effect")
    with pytest.raises(ValueError, match="explicit reviewed effect"):
        make(tmp_path / "task.db", catalog=catalog)


def test_nested_pydantic_output_is_committed_as_normalized_json(tmp_path):
    from pydantic import BaseModel

    class Result(BaseModel):
        reference: str

    with make(tmp_path / "task.db", handler=lambda _: [Result(reference="receipt-1")]) as g:
        g.call("agent_0", "pay", PAY)
        assert g.snapshot()["operations"][0]["state"] == "committed"
        assert g.snapshot()["operations"][0]["result"] == [dict(reference="receipt-1")]
        assert len(g.snapshot()["receipts"]) == 1


def test_ref_schema_rejects_nested_invalid_payload(tmp_path):
    from .gateway_helpers import tools

    catalog = tools()
    catalog[0]["parameters"] = dict(
        type="object",
        properties=dict(recipient=dict(type="string"), amount={"$ref": "#/$defs/positive"}),
        required=["recipient", "amount"],
        **{"$defs": {"positive": dict(type="integer", minimum=1)}},
    )
    with make(tmp_path / "task.db", catalog=catalog) as g:
        assert g.call("agent_0", "pay", dict(recipient="Alice", amount=False))["error"] == "ACTION_BLOCKED"
