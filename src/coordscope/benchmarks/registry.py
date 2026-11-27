"""Lazy built-in and installed benchmark adapters."""

from importlib import import_module, metadata

_BUILTINS = {"agentdojo": "coordscope.benchmarks.agentdojo.adapter:AgentDojoAdapter"}
ENTRY_POINT_GROUP = "coordscope.benchmarks"


def _catalog():
    catalog = dict(_BUILTINS)
    for entry in metadata.entry_points(group=ENTRY_POINT_GROUP):
        if entry.name in catalog:
            raise ValueError(f"Duplicate benchmark adapter name: {entry.name}")
        catalog[entry.name] = entry
    return catalog


def list_benchmarks():
    """List names without importing any benchmark package or extension."""
    return sorted(_catalog())


def get_benchmark(name):
    catalog = _catalog()
    if name not in catalog:
        raise ValueError(f"Unknown benchmark {name!r}. Available: {', '.join(sorted(catalog))}")
    entry = catalog[name]
    if isinstance(entry, str):
        module, attribute = entry.split(":", 1)
        factory = getattr(import_module(module), attribute)
    else:
        factory = entry.load()
    adapter = factory() if callable(factory) else factory
    if not callable(getattr(adapter, "run", None)) or not callable(getattr(adapter, "check", None)):
        raise TypeError(f"Benchmark {name!r} must implement run() and check().")
    return adapter
