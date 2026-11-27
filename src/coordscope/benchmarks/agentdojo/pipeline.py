"""Thin native pipeline: preserve AgentDojo environments and official traces."""

from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.logging import Logger
from pydantic import TypeAdapter

from coordscope.runtime.method import CoordScopeMethod

from .bindings import bind_tool, build_messages, environment_revisions
from .partitions import match_partition

PARTITION_COMMIT = "e71647382155dc6949d6ccf9a9d7ec7cf429b856"


class CoordScopePipeline(BasePipelineElement):
    name = "coordscope-host-policy"

    def __init__(
        self, *, method=None, model=None, completion=None, partitions=None, limits=None, policy=None, journal_dir=None
    ):
        if method is not None and any(value is not None for value in (model, completion, limits, policy, journal_dir)):
            raise ValueError("Supply one method or its construction arguments, not both.")
        if method is None:
            if journal_dir is None:
                raise ValueError("A durable journal directory is required.")
            method = CoordScopeMethod(
                model=model,
                completion=completion,
                limits=limits,
                policy=policy,
                journal_dir=journal_dir,
            )
        self.method, self.partitions = method, partitions

    @property
    def execution_completed(self):
        return self.method.execution_completed

    @property
    def last_run_metadata(self):
        return self.method.last_run_metadata

    @property
    def runtime_calls(self):
        return self.method.runtime_calls

    @property
    def mock_used(self):
        return self.method.mock_used

    def bind_suite(self, suite):
        match_partition({f.name for f in suite.tools}, self.partitions)

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args=None):
        if messages:
            raise ValueError("Isolated episodes must start with a fresh root request, not an external transcript.")
        self.method.reset()
        # Observer-only evaluation data; never used to construct the policy.
        self.method.injections = dict(getattr(Logger.get(), "context", {}).get("injections", {}))
        suite_name, specs = match_partition(set(runtime.functions), self.partitions)
        tools = []
        for function in runtime.functions.values():
            tool = bind_tool(runtime, env, function, observer=self.method)
            try:
                tool["returns"] = TypeAdapter(function.return_type).json_schema()
            except (TypeError, ValueError):
                tool["returns"] = {"description": "Opaque JSON result; parse with quarantined extract."}
            tools.append(tool)
        try:
            answer = self.method.execute(query, tools, specs, resources=environment_revisions(env))
        finally:
            self.method.last_run_metadata.update(
                suite=suite_name,
                partition_upstream_commit=PARTITION_COMMIT,
                agentdojo_adapter="official_runtime_and_judges",
                benchmark_scope="pinned_MultiAgentDojo_roles_on_caller_supplied_tasks",
                agentdojo_runtime_calls=list(self.method.runtime_calls),
            )
        metadata = self.method.last_run_metadata
        result_messages = build_messages(query, metadata, answer)
        return query, runtime, env, result_messages, {**(extra_args or {}), "coordscope_metadata": metadata}
