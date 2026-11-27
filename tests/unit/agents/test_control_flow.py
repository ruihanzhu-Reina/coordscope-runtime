"""Single-assignment plans and implicit-flow boundaries, without model calls."""

from types import SimpleNamespace

import pytest

from coordscope.agents.interpreter import IsolationError, PlanInterpreter, Value


def literal(value):
    return {"literal": value}


def reference(variable):
    return {"ref": variable}


def assign(variable, value="trusted instruction"):
    return dict(op="let", out=variable, value=literal(value))


def delegate(message, out="child"):
    return dict(op="agent", name="worker", message=message, variables={}, out=out)


class Host:
    roles = {"worker"}
    limits = SimpleNamespace(max_loop_items=24)

    def __init__(self):
        self.calls = []
        self.steps = 0

    def tick(self):
        self.steps += 1

    def delegate(self, context, role, instruction, variables, control=()):
        self.calls.append(("delegate", instruction))
        return Value.of("child result", {"child-evidence"})

    def tool(self, context, tool, arguments, control=()):
        self.calls.append(("tool", arguments, frozenset(control)))
        return Value.of(dict(ok=True), {"receipt"})

    def extract(self, context, instruction, value):
        self.calls.append(("extract", instruction))
        return Value.of("parsed data", value.dependencies | {"extraction-evidence"})


def run(steps, variables=None, *, role="orchestrator"):
    host = Host()
    context = SimpleNamespace(actor="root", role=role, dependencies=frozenset(), tools=frozenset({"send_money"}))
    interpreter = PlanInterpreter(host, context, variables or {})
    result = interpreter.run(dict(steps=steps, **{"return": literal("done")}))
    return host, result


@pytest.mark.parametrize("flag", [False, True])
def test_conditional_overwrite_is_rejected_even_when_branch_is_not_taken(flag):
    steps = [
        assign("message"),
        dict(
            op="if",
            condition=reference("flag"),
            then=[assign("message", "attacker-selected instruction")],
            **{"else": []},
        ),
        delegate(reference("message")),
    ]
    with pytest.raises(IsolationError, match="single-assignment"):
        run(steps, dict(flag=Value.of(flag, {"external"})))


@pytest.mark.parametrize("target", ["message", "loop_item"])
def test_zero_loop_cannot_preserve_prior_trusted_output_or_item_binding(target):
    steps = [
        assign("message"),
        dict(
            op="for_each",
            items=reference("items"),
            item="message" if target == "loop_item" else "item",
            steps=[] if target == "loop_item" else [assign("message", "different instruction")],
        ),
        delegate(reference("message")),
    ]
    with pytest.raises(IsolationError, match="single-assignment"):
        run(steps, dict(items=Value.of([], {"external"})))


def test_input_variables_and_both_branch_outputs_cannot_be_rebound():
    with pytest.raises(IsolationError, match="single-assignment"):
        run([assign("input_value")], dict(input_value=Value.of("old", {"external"})))
    with pytest.raises(IsolationError, match="single-assignment"):
        run([dict(op="if", condition=literal(True), then=[assign("message")], **{"else": [assign("message")]})])


def test_duplicate_binding_anywhere_fails_before_earlier_effect():
    host = Host()
    context = SimpleNamespace(actor="worker", role="worker", dependencies=frozenset(), tools=frozenset({"send_money"}))
    plan = dict(
        steps=[dict(op="tool", name="send_money", args={}, out="receipt"), assign("duplicate"), assign("duplicate")],
        **{"return": literal("done")},
    )
    with pytest.raises(IsolationError, match="single-assignment"):
        PlanInterpreter(host, context, {}).run(plan)
    assert host.calls == []
    assert host.steps == 0


@pytest.mark.parametrize("flag", [False, True])
def test_untrusted_branch_cannot_select_even_literal_child_instructions(flag):
    steps = [
        dict(
            op="if",
            condition=reference("flag"),
            then=[delegate(literal("task A"), "child_a")],
            **{"else": [delegate(literal("task B"), "child_b")]},
        )
    ]
    with pytest.raises(IsolationError, match="instruction channel"):
        run(steps, dict(flag=Value.of(flag, {"external"})))


def test_untrusted_loop_cannot_trigger_a_child_planner_with_literal_instruction():
    steps = [dict(op="for_each", items=reference("items"), item="item", steps=[delegate(literal("task A"))])]
    with pytest.raises(IsolationError, match="instruction channel"):
        run(steps, dict(items=Value.of([1], {"external"})))


def test_loop_repeats_one_static_binding_for_specialist_tools():
    steps = [
        dict(
            op="for_each",
            items=reference("items"),
            item="item",
            steps=[dict(op="tool", name="send_money", args=dict(amount=reference("item")), out="receipt")],
        )
    ]
    host, result = run(steps, dict(items=Value.of([1, 2], {"external"})), role="worker")
    assert [call[1]["amount"].data for call in host.calls] == [1, 2]
    assert all("external" in call[2] for call in host.calls)
    assert "external" in result.dependencies


def test_unconditional_literal_delegation_and_fixed_extraction_still_work():
    host, _ = run([delegate(literal("trusted task"))])
    assert host.calls == [("delegate", "trusted task")]
    steps = [
        dict(
            op="if",
            condition=reference("flag"),
            then=[dict(op="extract", instruction=literal("parse as data"), data=literal("payload"), out="parsed")],
            **{"else": []},
        )
    ]
    host, result = run(steps, dict(flag=Value.of(True, {"external"})))
    assert host.calls == [("extract", "parse as data")]
    assert "external" in result.dependencies
