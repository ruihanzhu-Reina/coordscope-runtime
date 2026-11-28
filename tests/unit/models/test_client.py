import copy
import threading
from types import SimpleNamespace

import pytest

from teampermit.models.client import IsolatedClient


def client(monkeypatch, response=None):
    monkeypatch.setenv("MANTA_PROVIDER", "deepseek")
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "100")
    monkeypatch.delenv("V1_BUDGET_DB", raising=False)
    monkeypatch.delenv("V1_REQUEST_JOURNAL", raising=False)
    monkeypatch.delenv("OPENROUTER_REASONING_EFFORT", raising=False)
    observer = SimpleNamespace(
        _metrics_lock=threading.Lock(),
        request_records=[],
        injections={"attack": "DATA_ONLY"},
        provider_fatal_error=None,
    )
    wire = []

    def create(**kwargs):
        wire.append(copy.deepcopy(kwargs))
        return response or SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}', tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="deepseek-flash",
        )

    transport = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return IsolatedClient("deepseek-flash", observer=observer, transport=transport), wire, observer


def test_no_tool_interface_no_history_and_observed_usage(monkeypatch):
    model, wire, observer = client(monkeypatch)
    for kind, content in [("quarantined", "DATA_ONLY"), ("planner", "Trusted task")]:
        model.complete_isolated(
            messages=[dict(role="user", content=content)], agent_id=kind, remaining_tokens=10000, kind=kind
        )
    assert "DATA_ONLY" not in str(wire[-1])
    assert all("tools" not in request for request in wire)
    assert [r["agent_type"] for r in observer.request_records] == ["quarantined", "planner"]
    assert [r["matched_injection_keys"] for r in observer.request_records] == [["attack"], []]
    assert all(r["usage_available"] for r in observer.request_records)
    with pytest.raises(ValueError, match="token budget"):
        model.complete_isolated(messages=[], agent_id="x", remaining_tokens=1, kind="planner")
    assert len(wire) == 2


@pytest.mark.parametrize("bad", ["tool_calls", "usage", "content"])
def test_invalid_model_output_fails_closed_without_retry(monkeypatch, bad):
    message = SimpleNamespace(content="{}", tool_calls=None)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    if bad == "tool_calls":
        message.tool_calls = [dict(function="send_money")]
    if bad == "usage":
        usage.total_tokens = -1
    if bad == "content":
        message.content = None
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model="deepseek-flash")
    model, wire, observer = client(monkeypatch, response)
    with pytest.raises(ValueError):
        model.complete_isolated(messages=[], agent_id="x", remaining_tokens=10000, kind="quarantined")
    assert len(wire) == 1
    assert observer.request_records[0]["status"] == "error"
    assert observer.provider_fatal_error


def test_offline_mode_never_constructs_real_client(monkeypatch):
    monkeypatch.setenv("MANTA_PROVIDER", "deepseek")
    monkeypatch.setenv("MAS_DISABLE_LIVE_LLM", "1")
    with pytest.raises(RuntimeError, match="disabled"):
        IsolatedClient("deepseek-flash", observer=SimpleNamespace())
