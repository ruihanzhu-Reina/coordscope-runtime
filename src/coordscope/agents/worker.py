"""Fixed interpreter processes with bounded JSON IPC and host-owned effects.

This separates address spaces and worker failures. It is not an OS sandbox:
the installed interpreter is trusted code and runs as the same user. Credentials,
tool handlers, policy and the ledger stay in the host. Never load worker-supplied
Python or pickle, and never treat wire provenance labels as authority.
"""

from __future__ import annotations

import json
import math
import os
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from .interpreter import IsolationError, PlanInterpreter, Value

MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 8192


def value_to_wire(value):
    return dict(payload=value.payload, dependencies=sorted(value.dependencies), field=value.field)


def value_from_wire(row):
    if not isinstance(row, dict) or set(row) != {"payload", "dependencies", "field"}:
        raise IsolationError("Invalid worker value.")
    payload, dependencies, field = row["payload"], row["dependencies"], row["field"]
    if not isinstance(payload, str) or not isinstance(dependencies, list):
        raise IsolationError("Invalid worker value types.")
    if any(not isinstance(ref, str) for ref in dependencies):
        raise IsolationError("Invalid worker dependencies.")
    if field is not None and (
        not isinstance(field, (list, tuple)) or len(field) != 2 or any(not isinstance(p, str) for p in field)
    ):
        raise IsolationError("Invalid worker field reference.")
    return Value.of(json.loads(payload), dependencies, tuple(field) if field is not None else None)


def _json(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _write_frame(stream, message, limit):
    data = _json(message)
    if len(data) > limit:
        raise IsolationError("Worker IPC frame exceeds its bound.")
    stream.write(struct.pack("!I", len(data)))
    stream.write(data)
    stream.flush()


def _read_exact(stream, count):
    chunks = []
    while count:
        data = stream.read(count)
        if not data:
            raise EOFError("Worker IPC closed before completing a frame.")
        chunks.append(data)
        count -= len(data)
    return b"".join(chunks)


def _read_frame(stream, limit):
    length = struct.unpack("!I", _read_exact(stream, 4))[0]
    if length > limit:
        raise IsolationError("Worker IPC frame exceeds its bound.")
    message = json.loads(_read_exact(stream, length))
    if not isinstance(message, dict):
        raise IsolationError("Worker IPC message must be an object.")
    return message


def _worker_environment():
    # Python is launched by absolute path. Preserve only Windows loader/temp
    # settings; model/provider credentials are never inherited by the worker.
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _command():
    root = str(Path(__file__).resolve().parents[2])
    bootstrap = (
        f"import sys; sys.path.insert(0, {root!r}); from coordscope.agents.worker import worker_main; worker_main()"
    )
    return [sys.executable, "-I", "-u", "-c", bootstrap]


def run_in_worker(
    *,
    plan,
    context,
    variables,
    roles,
    limits,
    dispatch,
    timeout_s=30,
    max_frame_bytes=MAX_FRAME_BYTES,
    on_start=None,
):
    """Interpret one fixed plan, brokering each operation to ``dispatch``.

    ``dispatch(op, payload)`` runs synchronously in the host and returns a Value
    (or None for tick). Bind the host context in that callback; there is no actor
    selector in RPC payloads. The timeout kills a stalled worker, but cannot
    interrupt a synchronous host handler. Tool transports need their own timeout.
    """
    if (
        not isinstance(timeout_s, (int, float))
        or isinstance(timeout_s, bool)
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("Worker timeout must be positive.")
    if type(max_frame_bytes) is not int or not 1 <= max_frame_bytes <= MAX_FRAME_BYTES:
        raise ValueError("Invalid worker frame limit.")
    context = dict(context)
    context["tools"] = sorted(context["tools"])
    context["dependencies"] = sorted(context["dependencies"])
    packet = dict(
        plan=plan,
        context=context,
        variables={name: value_to_wire(value) for name, value in variables.items()},
        roles=list(roles),
        limits=limits,
        max_frame_bytes=max_frame_bytes,
    )
    # Validate the outgoing bound before creating a process or writing a pipe.
    if len(_json(packet)) > max_frame_bytes:
        raise IsolationError("Worker IPC frame exceeds its bound.")
    messages = queue.Queue(maxsize=1)
    outbound = queue.Queue(maxsize=1)
    sent = queue.Queue(maxsize=1)
    stopped = threading.Event()
    diagnostics = bytearray()
    deadline = time.monotonic() + timeout_s
    with tempfile.TemporaryDirectory(prefix="coordscope-worker-") as directory:
        process = subprocess.Popen(
            _command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=directory,
            env=_worker_environment(),
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def read_messages():
            def offer(item):
                while not stopped.is_set():
                    try:
                        messages.put(item, timeout=0.05)
                        return
                    except queue.Full:
                        pass

            try:
                while not stopped.is_set():
                    offer((True, _read_frame(process.stdout, max_frame_bytes)))
            except (EOFError, ValueError, OSError, RecursionError) as exc:
                offer((False, exc))

        def write_messages():
            while not stopped.is_set():
                try:
                    message = outbound.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    _write_frame(process.stdin, message, max_frame_bytes)
                    sent.put(None)
                except (ValueError, OSError) as exc:
                    sent.put(exc)

        def send(message):
            outbound.put_nowait(message)
            try:
                error = sent.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise IsolationError("Interpreter worker timed out writing a frame.") from exc
            if error is not None:
                raise IsolationError("Interpreter worker closed its input.") from error

        def read_stderr():
            while chunk := process.stderr.read(4096):
                room = MAX_STDERR_BYTES - len(diagnostics)
                diagnostics.extend(chunk[: max(0, room)])

        reader = threading.Thread(target=read_messages, daemon=True)
        writer = threading.Thread(target=write_messages, daemon=True)
        stderr_reader = threading.Thread(target=read_stderr, daemon=True)
        reader.start()
        writer.start()
        stderr_reader.start()
        try:
            if on_start is not None:
                on_start(process.pid)
            send(packet)
            sequence = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise IsolationError("Interpreter worker timed out.")
                try:
                    valid, message = messages.get(timeout=remaining)
                except queue.Empty as exc:
                    raise IsolationError("Interpreter worker timed out.") from exc
                if not valid:
                    detail = diagnostics.decode("utf-8", errors="replace")[-1200:]
                    raise IsolationError(f"Interpreter worker protocol failed: {message}. {detail}") from message
                if message.get("kind") == "result" and set(message) == {"kind", "value"}:
                    return value_from_wire(message["value"])
                if message.get("kind") == "error" and set(message) == {"kind", "message"}:
                    raise IsolationError(str(message["message"])[:1200])
                if set(message) != {"kind", "id", "op", "payload"} or message["kind"] != "rpc":
                    raise IsolationError("Invalid worker RPC envelope.")
                if type(message["id"]) is not int or message["id"] != sequence:
                    raise IsolationError("Invalid worker RPC sequence.")
                if not isinstance(message["op"], str) or message["op"] not in {"tick", "tool", "delegate", "extract"}:
                    raise IsolationError("Unknown worker RPC operation.")
                if not isinstance(message["payload"], dict):
                    raise IsolationError("Invalid worker RPC payload.")
                required = {
                    "tick": set(),
                    "tool": {"name", "values", "control"},
                    "delegate": {"role", "instruction", "variables", "control"},
                    "extract": {"instruction", "value"},
                }[message["op"]]
                if set(message["payload"]) != required:
                    raise IsolationError("Invalid worker RPC fields.")
                if "control" in required:
                    control = message["payload"]["control"]
                    if not isinstance(control, list) or any(not isinstance(ref, str) for ref in control):
                        raise IsolationError("Invalid worker control dependencies.")
                result = dispatch(message["op"], message["payload"])
                if time.monotonic() >= deadline:
                    raise IsolationError("Interpreter worker timed out after host dispatch.")
                if result is not None and not isinstance(result, Value):
                    raise IsolationError("Host dispatch must return a runtime Value or None.")
                send(
                    dict(kind="reply", id=sequence, value=None if result is None else value_to_wire(result)),
                )
                sequence += 1
        finally:
            stopped.set()
            if process.poll() is None:
                process.kill()
            process.wait()
            # Closing the pipes after wait unblocks readers. The message reader
            # can be waiting on its bounded queue; it is deliberately a daemon.
            process.stdin.close()
            reader.join(timeout=1)
            writer.join(timeout=1)
            stderr_reader.join(timeout=1)
            process.stdout.close()
            process.stderr.close()


class _RemoteSession:
    def __init__(self, packet):
        self.roles = frozenset(packet["roles"])
        self.limits = SimpleNamespace(**packet["limits"])
        self.sequence = 0
        self.limit = packet["max_frame_bytes"]

    def _rpc(self, operation, payload):
        sequence = self.sequence
        self.sequence += 1
        _write_frame(sys.stdout.buffer, dict(kind="rpc", id=sequence, op=operation, payload=payload), self.limit)
        reply = _read_frame(sys.stdin.buffer, self.limit)
        if set(reply) != {"kind", "id", "value"} or reply["kind"] != "reply" or reply["id"] != sequence:
            raise IsolationError("Invalid host RPC reply.")
        return None if reply["value"] is None else value_from_wire(reply["value"])

    def tick(self):
        self._rpc("tick", {})

    def tool(self, context, tool, values, control=()):
        return self._rpc(
            "tool", dict(name=tool, values={k: value_to_wire(v) for k, v in values.items()}, control=sorted(control))
        )

    def delegate(self, parent, role, instruction, variables, control=()):
        return self._rpc(
            "delegate",
            dict(
                role=role,
                instruction=instruction,
                variables={k: value_to_wire(v) for k, v in variables.items()},
                control=sorted(control),
            ),
        )

    def extract(self, context, instruction, value):
        return self._rpc("extract", dict(instruction=instruction, value=value_to_wire(value)))


def worker_main():
    """Internal fixed-code entry point; stdin/stdout are reserved for JSON frames."""
    limit = MAX_FRAME_BYTES
    try:
        packet = _read_frame(sys.stdin.buffer, limit)
        limit = packet["max_frame_bytes"]
        session = _RemoteSession(packet)
        context = SimpleNamespace(**packet["context"])
        context.tools = frozenset(context.tools)
        context.dependencies = frozenset(context.dependencies)
        variables = {name: value_from_wire(row) for name, row in packet["variables"].items()}
        value = PlanInterpreter(session, context, variables).run(packet["plan"])
        _write_frame(sys.stdout.buffer, dict(kind="result", value=value_to_wire(value)), limit)
    except Exception as exc:
        _write_frame(sys.stdout.buffer, dict(kind="error", message=f"{type(exc).__name__}: {str(exc)[:1000]}"), limit)
