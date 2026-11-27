"""Serializable run configuration and benchmark-owned scoring contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON value: {value}")

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)


@dataclass(frozen=True)
class RunConfig:
    schema_version: int
    benchmark: str
    task_id: str
    model: str | None = None
    policy: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Only run config schema_version 1 is supported.")
        if type(self.benchmark) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]*", self.benchmark):
            raise ValueError("Benchmark must be a registered lowercase identifier.")
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("task_id must be a nonempty string.")
        if self.model is not None and (type(self.model) is not str or not self.model.strip()):
            raise ValueError("model must be a nonempty string or null.")
        if self.policy is not None and not isinstance(self.policy, Path):
            raise ValueError("policy must be a resolved Path or None.")
        if type(self.options) is not dict:
            raise ValueError("Benchmark options must be a JSON object.")
        json.dumps(self.options, allow_nan=False)

    @classmethod
    def from_file(cls, path):
        path = Path(path).resolve()
        row = read_json(path)
        required = {"schema_version", "benchmark", "task_id"}
        allowed = required | {"model", "policy", "options"}
        if type(row) is not dict or not required <= set(row) or set(row) - allowed:
            raise ValueError("Run config contains missing or unsupported top-level fields.")
        policy = row.get("policy")
        if policy is not None:
            if type(policy) is not str or not policy.strip():
                raise ValueError("policy must be a JSON file path or null.")
            policy = (path.parent / policy).resolve()
        return cls(**{**row, "policy": policy})

    def to_document(self):
        return dict(
            schema_version=self.schema_version,
            benchmark=self.benchmark,
            task_id=self.task_id,
            model=self.model,
            policy=str(self.policy) if self.policy is not None else None,
            options=self.options,
        )


@dataclass(frozen=True)
class BenchmarkOutcome:
    """Native scores remain separate; attack_success means attacker goal achieved."""

    task_success: bool | None
    condition: str = "clean"
    attack_success: bool | None = None
    attack_exposed: bool | str | None = None
    native_metrics: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)
    error_status: str | None = None
    error: str | None = None

    def __post_init__(self):
        if self.task_success is not None and type(self.task_success) is not bool:
            raise ValueError("task_success must be a native boolean or null.")
        if self.attack_success is not None and type(self.attack_success) is not bool:
            raise ValueError("attack_success must be a native boolean or null.")
        if type(self.condition) is not str or not self.condition:
            raise ValueError("Outcome condition must be nonempty.")
        if self.condition == "clean" and self.attack_success is not None:
            raise ValueError("Clean outcomes cannot report attacker success.")
        if self.error_status is not None and self.error_status not in {"INFRA_ERROR", "JUDGE_ERROR", "TIMEOUT"}:
            raise ValueError("Unsupported benchmark error status.")
        if self.error is not None and type(self.error) is not str:
            raise ValueError("Benchmark errors must be strings.")
        if type(self.native_metrics) is not dict or type(self.metadata) is not dict or type(self.artifacts) is not dict:
            raise ValueError("Native metrics, metadata and artifacts must be JSON objects.")
        if any(type(key) is not str or type(value) is not str for key, value in self.artifacts.items()):
            raise ValueError("Artifact entries must map names to relative path strings.")
        for path in self.artifacts.values():
            if Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("Artifacts must stay within the run directory.")
        json.dumps(dict(metrics=self.native_metrics, metadata=self.metadata, artifacts=self.artifacts), allow_nan=False)


class BenchmarkAdapter(Protocol):
    def check(self) -> dict[str, Any]: ...

    def run(self, config: RunConfig, method: Any, run_directory: Path) -> BenchmarkOutcome: ...
