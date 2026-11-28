"""Benchmark-independent role definition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    tool_names: tuple[str, ...]
