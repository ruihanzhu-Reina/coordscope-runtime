"""One fresh, observable JSON request. No old agent loop, tool access or fallback."""

import copy
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from openai import OpenAI

from .budget import configured_budget
from .providers import gpt4o_sampling, provider_config, validate_gpt4o_response
from .validation import validate_pro_response


class IsolatedClient:
    def __init__(self, model=None, *, observer, transport=None):
        self.provider = provider_config(model)
        self.observer = observer
        if transport is None and os.getenv("MAS_DISABLE_LIVE_LLM") == "1":
            raise RuntimeError("Live model access disabled; use an explicitly injected offline completion")
        if transport is None and not self.provider.api_key:
            raise ValueError("Missing credentials for the explicitly selected provider")
        self.budget = configured_budget(self.provider.model)
        if (
            self.budget is not None
            and self.provider.name == "deepseek"
            and urlsplit(self.provider.base_url).hostname != "api.deepseek.com"
        ):
            raise ValueError("Historical DeepSeek budget rates require the official endpoint")
        self.timeout = float(os.getenv("V1_LLM_TIMEOUT_S", "180"))
        self.transport = (
            transport
            if transport is not None
            else OpenAI(
                api_key=self.provider.api_key,
                base_url=self.provider.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        )

    def _request(self, messages):
        kwargs = dict(
            model=self.provider.model, messages=copy.deepcopy(messages), temperature=0.0, timeout=self.timeout
        )
        if self.provider.name != "deepseek":
            return gpt4o_sampling(kwargs, temperature=0.0)
        kwargs["max_tokens"] = int(os.getenv("OPENROUTER_MAX_TOKENS", "4096"))
        if kwargs["max_tokens"] < 1:
            raise ValueError("OPENROUTER_MAX_TOKENS must be positive")
        for variable, parameter in [("OPENROUTER_TEMPERATURE", "temperature"), ("OPENROUTER_TOP_P", "top_p")]:
            if os.getenv(variable):
                kwargs[parameter] = float(os.environ[variable])
        extra = {}
        if os.getenv("OPENROUTER_TOP_K"):
            extra["top_k"] = int(os.environ["OPENROUTER_TOP_K"])
        if os.getenv("OPENROUTER_REASONING_EFFORT"):
            extra["reasoning"] = {"effort": os.environ["OPENROUTER_REASONING_EFFORT"]}
        if self.provider.model == "deepseek-v4-pro":
            extra["thinking"] = {"type": "enabled"}
        if extra:
            kwargs["extra_body"] = extra
        return kwargs

    def _journal(self, record):
        key = "GPT4O_REQUEST_JOURNAL" if self.provider.name != "deepseek" else "V1_REQUEST_JOURNAL"
        if path := os.getenv(key):
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with self.observer._metrics_lock, target.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())

    def complete_isolated(self, *, messages, agent_id, remaining_tokens, kind):
        if getattr(self.observer, "provider_fatal_error", None):
            raise RuntimeError(self.observer.provider_fatal_error)
        kwargs = self._request(messages)
        allowance = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 4096 + kwargs["max_tokens"]
        if allowance > remaining_tokens:
            raise ValueError("Insufficient episode token budget for isolated request")
        # This observes exposure for evaluation; labels never enter requests.
        text = json.dumps(messages, ensure_ascii=False)
        matches = [key for key, payload in self.observer.injections.items() if payload and payload in text]
        record = dict(
            request_id=uuid.uuid4().hex,
            agent_id=agent_id,
            agent_type=kind,
            model=self.provider.model,
            provider=self.provider.name,
            endpoint=self.provider.base_url,
            status="pending",
            usage_available=False,
            matched_injection_keys=matches,
        )
        started, reservation = time.perf_counter(), None
        try:
            if self.budget is not None:
                reservation = self.budget.reserve(self.provider.model, kwargs["max_tokens"])
                record["budget_request_id"] = reservation
            self._journal(record)
            response = self.transport.chat.completions.create(**kwargs)
            if (
                not response.choices
                or response.choices[0].message.tool_calls
                or not response.choices[0].message.content
                or response.usage is None
            ):
                raise ValueError("Isolated agent must return JSON content and usage, with no tool calls")
            counts = [
                getattr(response.usage, name, None) for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            ]
            if any(type(value) is not int or value < 0 for value in counts) or counts[2] != sum(counts[:2]):
                raise ValueError("Missing or inconsistent provider token usage")
            if self.provider.name != "deepseek":
                validate_gpt4o_response(response)
            elif self.provider.model == "deepseek-v4-pro":
                validate_pro_response(response)
            if self.budget is not None:
                record["cost_upper_bound_usd"] = self.budget.settle(reservation, response.usage)
            record.update(
                status="completed",
                usage_available=True,
                token_in=counts[0],
                token_out=counts[1],
                provider_model=getattr(response, "model", None),
            )
            return response
        except Exception as exc:
            if self.budget is not None and reservation is not None:
                self.budget.uncertain(reservation)
            record.update(status="error", error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
            if isinstance(exc, ValueError) or record["http_status"] in {400, 401, 403, 404}:
                self.observer.provider_fatal_error = f"Provider validation failed: {type(exc).__name__}"
            raise
        finally:
            record["latency_s"] = time.perf_counter() - started
            with self.observer._metrics_lock:
                self.observer.request_records.append(record)
            self._journal(record)
