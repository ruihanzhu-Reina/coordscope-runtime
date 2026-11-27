"""The reusable method works with arbitrary host tool names and durable IDs."""

import os

import pytest

from coordscope.agents.roles import SubAgentSpec
from coordscope.runtime.method import CoordScopeMethod
from coordscope.security.policy import ActionPolicy
from tests.helpers.scripted import Script, agent, call, lit, plan


def make_method(tmp_path):
    invocations = []
    tools = [
        dict(
            name="issue_credit",
            description="Controlled credit fixture",
            effect="mutate",
            parameters=dict(type="object", properties=dict(customer=dict(type="string")), required=["customer"]),
            handler=lambda args: invocations.append(args) or dict(ok=True),
        )
    ]
    specs = [SubAgentSpec("credits", "Issue credits", ("issue_credit",))]
    script = Script(
        dict(
            orchestrator=plan(agent("credits", lit("Issue the approved credit"))),
            credits=plan(call("issue_credit", dict(customer=lit("Alice")))),
        )
    )
    method = CoordScopeMethod(
        completion=script,
        journal_dir=tmp_path,
        policy=ActionPolicy.exact([dict(tool="issue_credit", arguments=dict(customer="Alice"))]),
    )
    return method, tools, specs, invocations


def test_same_host_task_reopens_ledger_without_repeating_effect(tmp_path):
    method, tools, specs, invocations = make_method(tmp_path)
    for _ in range(2):
        method.execute("Credit Alice once", tools, specs, task_id="stable-credit")
    assert invocations == [dict(customer="Alice")]
    assert method.last_run_metadata["gateway_events"][-1]["status"] == "already_applied"
    assert method.last_run_metadata["workers"]
    assert all(w["pid"] != os.getpid() for w in method.last_run_metadata["workers"])


@pytest.mark.parametrize("task_id", ["", False, 0, "../different-task"])
def test_invalid_task_identity_never_silently_creates_new_budget(tmp_path, task_id):
    method, tools, specs, invocations = make_method(tmp_path)
    with pytest.raises(ValueError, match="task_id"):
        method.execute("Credit Alice once", tools, specs, task_id=task_id)
    assert invocations == []
    assert list(tmp_path.iterdir()) == []
