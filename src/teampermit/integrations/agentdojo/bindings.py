"""Bind the caller's real environment and preserve the official execution trace."""

import json
from typing import Any

from agentdojo.functions_runtime import Env, FunctionCall, FunctionsRuntime
from agentdojo.types import ChatAssistantMessage, ChatMessage, ChatUserMessage, text_content_block_from_string

from teampermit.security.manifest import tool_spec


def bind_tool(runtime: FunctionsRuntime, env: Env, function: Any, *, observer=None) -> dict[str, Any]:
    """Convert one AgentDojo Function into TeamPermit's tool schema + bound handler."""

    schema = function.parameters.model_json_schema()

    def handler(arguments: dict[str, Any]) -> Any:
        value, error = runtime.run_function(env, function.name, arguments)
        if observer is not None:
            from agentdojo.agent_pipeline.tool_execution import tool_result_to_str

            with observer._metrics_lock:
                observer.runtime_calls.append(
                    {
                        "tool_name": function.name,
                        "arguments": dict(arguments),
                        "output": tool_result_to_str(value) if error is None else str(error),
                        "error": error,
                    }
                )
        if error is not None:
            return {"error": error}
        return value

    return {
        "name": function.name,
        "description": function.description,
        "parameters": schema,
        "handler": handler,
        "side_effect": tool_spec(function.name).side_effect,
    }


def _text_blocks(value: Any) -> list[dict[str, str]]:
    if isinstance(value, list):
        blocks = []
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                blocks.append({"type": "text", "content": str(item.get("content", ""))})
        if blocks:
            return blocks
    return [text_content_block_from_string(str(value or ""))]


def build_messages(query: str, metadata: dict[str, Any], final_answer: str) -> list[ChatMessage]:
    """Project TeamPermit's interaction logs into AgentDojo's official message shape."""

    messages: list[ChatMessage] = [ChatUserMessage(role="user", content=[text_content_block_from_string(query)])]
    # The official judge reconstructs its function trace from assistant calls.
    # Use actual FunctionsRuntime invocations, including calls from discarded
    # stages, and exclude TeamPermit's synthetic/skipped calls and proposals.
    records = metadata.get("agentdojo_runtime_calls", [])
    logs = [{"assistant_message": {"content": ""}, "tool_calls": [record]} for record in records]

    for index, log in enumerate(logs):
        if not isinstance(log, dict):
            continue
        raw_assistant = log.get("assistant_message")
        if isinstance(raw_assistant, dict):
            assistant: ChatAssistantMessage = {
                "role": "assistant",
                "content": _text_blocks(raw_assistant.get("content", "")),
                "tool_calls": [],
            }
            for call_index, record in enumerate(log.get("tool_calls", []) or []):
                if not isinstance(record, dict):
                    continue
                call = FunctionCall(
                    function=str(record.get("tool_name", "")),
                    args=dict(record.get("arguments", {}) or {}),
                    id=str(record.get("id") or f"teampermit-call-{index}-{call_index}"),
                )
                assistant["tool_calls"].append(call)
            messages.append(assistant)
            for call_index, record in enumerate(log.get("tool_calls", []) or []):
                if not isinstance(record, dict):
                    continue
                call = assistant["tool_calls"][call_index]
                output = record.get("output")
                if not isinstance(output, str):
                    output = json.dumps(output, ensure_ascii=False, default=str)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call": call,
                        "tool_call_id": call.id,
                        "content": [text_content_block_from_string(output)],
                        "error": record.get("error"),
                    }
                )

    messages.append(
        ChatAssistantMessage(
            role="assistant",
            content=[text_content_block_from_string(final_answer)],
            tool_calls=None,
        )
    )
    return messages
