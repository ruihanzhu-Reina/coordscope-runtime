"""Real subprocess boundary tests with controlled host callbacks, no model API."""

import os
import subprocess
import sys
import time

import pytest

from coordscope.agents import worker
from coordscope.agents.interpreter import IsolationError, Value


def run(plan=None, dispatch=lambda *_: None, **options):
    return worker.run_in_worker(
        plan=plan or dict(steps=[], **{"return": {"literal": "done"}}),
        context=dict(
            actor="files_1", role="files", task="Read", tools=frozenset({"read_file"}), dependencies=frozenset()
        ),
        variables={},
        roles=["files"],
        limits=dict(max_loop_items=24),
        dispatch=dispatch,
        **options,
    )


def test_interpreter_is_in_another_process_and_effects_stay_in_host():
    worker_pids, host_pids, operations = [], [], []

    def dispatch(op, payload):
        operations.append(op)
        host_pids.append(os.getpid())
        assert "actor" not in payload and "context" not in payload
        if op == "tool":
            assert payload["name"] == "read_file"
            value = worker.value_from_wire(payload["values"]["file_id"])
            assert value.data == "f1"
            return Value.of(dict(content="external data"), ["e1"], ("e1", ""))

    plan = dict(
        steps=[dict(op="tool", name="read_file", args=dict(file_id={"literal": "f1"}), out="data")],
        **{"return": {"ref": "data"}},
    )
    result = run(plan, dispatch, on_start=worker_pids.append)
    assert len(worker_pids) == 1 and worker_pids[0] != os.getpid()
    assert host_pids == [os.getpid(), os.getpid()]
    assert operations == ["tick", "tool"]
    assert result.data == dict(content="external data")
    assert result.dependencies == frozenset({"e1"})
    assert result.field == ("e1", "")


def test_child_errors_fail_closed_before_any_host_effect():
    operations = []
    plan = dict(steps=[dict(op="tool", name="send_money", args={}, out="x")], **{"return": {"literal": "x"}})
    with pytest.raises(IsolationError, match="not assigned"):
        run(plan, lambda op, payload: operations.append(op))
    assert operations == []


def test_provider_credentials_are_not_inherited_and_stderr_is_drained(monkeypatch):
    monkeypatch.setenv("COORDSCOPE_TEST_SECRET", "must-not-inherit")
    command = worker._command()
    # The assertion executes in the real child before its protocol entry point.
    command[-1] = (
        "import os, sys; assert 'COORDSCOPE_TEST_SECRET' not in os.environ; "
        "sys.stderr.write('diagnostic' * 20000); sys.stderr.flush(); " + command[-1]
    )
    monkeypatch.setattr(worker, "_command", lambda: command)
    assert run().data == "done"


def test_stalled_worker_is_killed_even_when_it_never_reads_large_input(monkeypatch):
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(worker.subprocess, "Popen", capture)
    monkeypatch.setattr(worker, "_command", lambda: [sys.executable, "-I", "-c", "import time; time.sleep(60)"])
    started = time.monotonic()
    with pytest.raises(IsolationError, match="timed out"):
        run(dict(steps=[], **{"return": {"literal": "x" * 200000}}), timeout_s=0.3)
    assert time.monotonic() - started < 5
    assert len(processes) == 1 and processes[0].poll() is not None


@pytest.mark.parametrize(
    "code,reason",
    [
        ("import os; os._exit(23)", "closed|protocol"),
        ("import sys, struct; sys.stdout.buffer.write(struct.pack('!I', 16000000)); sys.stdout.flush()", "bound"),
        ("import sys, struct; sys.stdout.buffer.write(struct.pack('!I', 2) + b'[]'); sys.stdout.flush()", "object"),
    ],
)
def test_abrupt_exit_and_malformed_frames_are_rejected(monkeypatch, code, reason):
    monkeypatch.setattr(worker, "_command", lambda: [sys.executable, "-I", "-c", code])
    with pytest.raises(IsolationError, match=reason):
        run()


def test_host_callback_exception_propagates_and_worker_is_reaped(monkeypatch):
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    def broken_dispatch(*args):
        raise RuntimeError("host transport failure")

    monkeypatch.setattr(worker.subprocess, "Popen", capture)
    plan = dict(steps=[dict(op="let", value={"literal": 1}, out="x")], **{"return": {"ref": "x"}})
    with pytest.raises(RuntimeError, match="host transport failure"):
        run(plan, broken_dispatch)
    assert len(processes) == 1 and processes[0].poll() is not None


def test_invalid_provenance_wire_shapes_and_outgoing_size_are_rejected():
    with pytest.raises(IsolationError, match="dependencies"):
        worker.value_from_wire(dict(payload='"x"', dependencies=[{}], field=None))
    with pytest.raises(IsolationError, match="bound"):
        run(dict(steps=[], **{"return": {"literal": "x" * 1000}}), max_frame_bytes=200)
