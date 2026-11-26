"""Explicit offline completions. Never benchmark evidence."""

import json


def lit(value):
    return {"literal": value}


def ref(value, *path):
    return {"ref": value, "path": list(path)}


def plan(*steps, result=None):
    return {"steps": list(steps), "return": result or lit("done")}


def agent(role, message, variables=None, out="result"):
    return dict(op="agent", name=role, message=message, variables=variables or {}, out=out)


def call(tool, args=None, out="result"):
    return dict(op="tool", name=tool, args=args or {}, out=out)


class Script:
    def __init__(self, plans, *, actions=(), extract=None, review="deny"):
        self.plans, self.actions, self.extract, self.review = plans, list(actions), extract, review
        self.requests = []

    def __call__(self, kind, actor, messages, remaining):
        self.requests.append(dict(kind=kind, actor=actor, messages=messages))
        if kind == "compiler":
            return {"actions": self.actions}, 1
        if kind == "planner":
            role = json.loads(messages[-1]["content"])["role"]
            return self.plans[role], 1
        if kind == "reviewer":
            return {"decision": self.review, "reason": "scripted exact-action decision"}, 1
        if kind == "quarantined":
            return json.dumps(self.extract), 1
        raise AssertionError(kind)
