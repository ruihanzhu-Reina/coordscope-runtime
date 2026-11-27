"""Resource-level changes invalidate only dependent evidence and effects."""

import pytest

from coordscope.security.resources import Footprint

from .gateway_helpers import PAY, make, source_policy, tools


def lookup(g):
    receipt = g.call("agent_0", "lookup", dict(user="alice"))
    return dict(recipient=dict(evidence_id=receipt["evidence_id"], path="/recipient"))


def test_unrelated_write_preserves_source_and_changed_source_is_rejected(tmp_path):
    state = {"directory:alice": "v1", "account:Bob": "v1", "account:Alice": "v1"}
    actions = [dict(tool="pay", arguments=PAY), dict(tool="pay", arguments=PAY | dict(recipient="Bob"))]
    with make(tmp_path / "task.db", actions=actions, resources=state.get) as g:
        sources = lookup(g)
        g.call("agent_0", "pay", PAY | dict(recipient="Bob"))
        assert "error" not in g.call("agent_0", "pay", PAY, argument_sources=sources)
    with make(tmp_path / "changed.db", resources=state.get) as g:
        sources = lookup(g)
        state["directory:alice"] = "v2"
        assert g.call("agent_0", "pay", PAY, argument_sources=sources)["error"] == "ACTION_BLOCKED"


def test_source_policy_requires_external_validator(tmp_path):
    with make(tmp_path / "unsupported.db", policy=source_policy()) as g:
        assert g.call("agent_0", "pay", PAY, argument_sources=lookup(g))["error"] == "ACTION_BLOCKED"
    with make(tmp_path / "validated.db", policy=source_policy(), resources=lambda _: "v1") as g:
        sources = lookup(g)
        assert "error" not in g.call("agent_0", "pay", PAY, argument_sources=sources)
        assert g.events[-1]["argument_provenance"][0]["freshness_verified"]


def test_read_cache_removed_external_changes_are_observed(tmp_path):
    state = dict(recipient="Alice")
    with make(tmp_path / "task.db", read=lambda _: dict(state)) as g:
        first = g.call("agent_0", "lookup", dict(user="alice"))
        state["recipient"] = "Bob"
        second = g.call("agent_0", "lookup", dict(user="alice"))
        assert first["evidence_id"] != second["evidence_id"]
        assert '"Bob"' in second["content"]


def test_unknown_blocks_only_conflicting_resources(tmp_path):
    actions = [dict(tool="pay", arguments=PAY), dict(tool="pay", arguments=PAY | dict(recipient="Bob"))]
    calls = []

    def pay(args):
        calls.append(args)
        return dict(ok=args["recipient"] != "Alice")

    with make(tmp_path / "task.db", actions=actions, handler=pay) as g:
        g.call("agent_0", "pay", PAY)
        assert "error" not in g.call("agent_0", "pay", PAY | dict(recipient="Bob"))
        assert g.call("agent_0", "pay", PAY)["error"] == "ACTION_BLOCKED"
        assert calls == [PAY, PAY | dict(recipient="Bob")]


def test_validator_failure_after_effect_remains_unknown(tmp_path):
    def broken(_):
        raise RuntimeError("validator unreachable")

    with make(tmp_path / "task.db", resources=broken) as g:
        with pytest.raises(RuntimeError, match="validator unreachable"):
            g.call("agent_0", "pay", PAY)
        assert g.snapshot()["operations"][0]["state"] == "unknown"


def test_unknown_source_write_blocks_consumer_even_with_distinct_target(tmp_path):
    catalog = tools()
    catalog[0]["resources"] = lambda args: (
        Footprint(writes=("directory:alice",)) if args["recipient"] == "Bob" else Footprint(writes=("account:Alice",))
    )
    actions = [dict(tool="pay", arguments=PAY), dict(tool="pay", arguments=PAY | dict(recipient="Bob"))]
    with make(tmp_path / "task.db", catalog=catalog, actions=actions, resources=lambda _: "v1") as g:
        sources = lookup(g)
        g.tools["pay"]["handler"] = lambda _: dict(ok=False)
        g.call("agent_0", "pay", PAY | dict(recipient="Bob"))
        assert g.call("agent_0", "pay", PAY, argument_sources=sources)["error"] == "ACTION_BLOCKED"


def test_source_and_write_can_share_resource_without_self_conflict(tmp_path):
    catalog = tools()
    catalog[0]["resources"] = lambda _: Footprint(writes=("directory:alice",))
    with make(tmp_path / "task.db", catalog=catalog, policy=source_policy(), resources=lambda _: "v1") as g:
        sources = lookup(g)
        assert "error" not in g.call("agent_0", "pay", PAY, argument_sources=sources)
        assert g.call("agent_0", "pay", PAY, argument_sources=sources)["already_applied"]


def test_transformed_and_control_dependencies_cannot_bypass_freshness(tmp_path):
    state = {"directory:alice": "v1"}
    with make(tmp_path / "task.db", resources=state.get) as g:
        source = g.call("agent_0", "lookup", dict(user="alice"))["evidence_id"]
        state["directory:alice"] = "v2"
        assert g.call("agent_0", "pay", PAY, evidence_ids=[source])["error"] == "ACTION_BLOCKED"
        assert g.call("agent_0", "lookup", dict(user="alice"), evidence_ids=[source])["error"] == "ACTION_BLOCKED"
        assert g.snapshot()["operations"] == []


def test_second_source_check_observed_change_cancels_before_dispatch(tmp_path):
    calls = []
    count = 0

    def revision(key):
        nonlocal count
        if key == "directory:alice":
            count += 1
            return "v1" if count <= 2 else "v2"
        return "v1"

    with make(
        tmp_path / "task.db",
        policy=source_policy(),
        resources=revision,
        handler=lambda args: calls.append(args) or dict(ok=True),
    ) as g:
        source = lookup(g)
        assert g.call("agent_0", "pay", PAY, argument_sources=source)["error"] == "ACTION_BLOCKED"
        assert calls == []
        assert g.snapshot()["operations"][0]["state"] == "not_applied"


def test_source_grant_budget_is_shared_across_distinct_concrete_arguments(tmp_path):
    state = dict(recipient="Alice", revision=1)
    with make(
        tmp_path / "task.db",
        policy=source_policy(),
        read=lambda _: dict(recipient=state["recipient"]),
        resources=lambda _: state["revision"],
    ) as g:
        assert "error" not in g.call("agent_0", "pay", PAY, argument_sources=lookup(g))
        state.update(recipient="Bob", revision=2)
        second = g.call("agent_0", "pay", PAY | dict(recipient="Bob"), argument_sources=lookup(g))
        assert second["error"] == "ACTION_BLOCKED"
        assert "budget" in second["reason"]
        assert len(g.snapshot()["operations"]) == 1
