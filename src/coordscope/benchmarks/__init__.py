"""Benchmark contracts and lazy discovery; no native benchmark imports."""

from .base import BenchmarkAdapter, BenchmarkOutcome, RunConfig
from .registry import get_benchmark, list_benchmarks

__all__ = ["BenchmarkAdapter", "BenchmarkOutcome", "RunConfig", "get_benchmark", "list_benchmarks"]
