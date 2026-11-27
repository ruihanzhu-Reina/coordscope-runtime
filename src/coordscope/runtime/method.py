"""One method for native benchmarks and directly embedded tool environments."""

import re
import threading
import uuid
from pathlib import Path

from coordscope.agents.session import IsolatedSession, Limits
from coordscope.models.client import IsolatedClient
from coordscope.models.providers import provider_config
from coordscope.security.policy import ActionPolicy


class CoordScopeMethod:
    """Own the model transport and create one durable session per native query.

    Adapters supply tools, roles and resource revisions. They retain their own
    mutable environments and native judges. A policy is a trusted caller input;
    model completions have no way to add grants to it.
    """

    def __init__(self, *, model=None, policy=None, journal_dir, completion=None, limits=None):
        self.policy = policy if policy is not None else ActionPolicy.exact([])
        self.journal_dir = Path(journal_dir)
        self.limits = limits or Limits()
        self._completion = completion
        self._metrics_lock = threading.Lock()
        self.mock_used = completion is not None
        self.model = provider_config(model).model
        self.reset()
        self.client = None if completion else IsolatedClient(self.model, observer=self)

    def reset(self):
        self.request_records, self.runtime_calls = [], []
        self.injections = {}
        self.execution_completed = False
        self.provider_fatal_error = None
        self.last_run_metadata = {}

    def complete(self, kind, actor, messages, remaining_tokens):
        if self._completion is not None:
            return self._completion(kind, actor, messages, remaining_tokens)
        response = self.client.complete_isolated(
            messages=messages,
            agent_id=actor,
            remaining_tokens=remaining_tokens,
            kind=kind,
        )
        return response.choices[0].message.content, response.usage.total_tokens

    def execute(self, user_request, tools, specs, *, resources=None, task_id=None):
        """Execute or reopen a host task against the same external environment.

        A supplied task ID reuses its effect ledger. The caller must preserve the
        external environment and task contract. Native benchmark episodes omit
        it because a fresh native environment needs a fresh ledger.
        """
        self.execution_completed = False
        self.last_run_metadata = {}
        task_id = uuid.uuid4().hex if task_id is None else task_id
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", task_id):
            raise ValueError("task_id must be a stable, single path-safe identifier.")
        path = self.journal_dir / task_id / "runtime.sqlite"
        with IsolatedSession(
            user_request,
            tools,
            specs,
            self.complete,
            self.limits,
            policy=self.policy,
            journal_path=path,
            task_id=task_id,
            resources=resources,
        ) as session:
            try:
                answer = session.run()
                self.execution_completed = True
                return answer
            finally:
                self.last_run_metadata = session.snapshot()
                self.last_run_metadata["journal_path"] = str(path.resolve())
