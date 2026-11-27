"""Controlled host tools; no real network or payment effects."""

from coordscope.evidence.store import EvidenceStore
from coordscope.security.gateway import GovernedGateway
from coordscope.security.policy import ActionPolicy
from coordscope.security.resources import Footprint

PAY = dict(recipient="Alice", amount=10)


def tools(handler=None, read=None):
    return [
        dict(
            name="pay",
            description="Controlled transfer",
            effect="mutate",
            resource_domain="bank",
            parameters=dict(
                type="object",
                properties=dict(recipient=dict(type="string"), amount=dict(type="integer", minimum=1)),
                required=["recipient", "amount"],
            ),
            resources=lambda args: Footprint(writes=("account:" + args["recipient"],)),
            handler=handler or (lambda _: dict(ok=True)),
        ),
        dict(
            name="lookup",
            description="Controlled account lookup",
            effect="read",
            resource_domain="directory",
            parameters=dict(type="object", properties=dict(user=dict(type="string")), required=["user"]),
            resources=lambda args: Footprint(reads=("directory:" + args["user"],)),
            handler=read or (lambda _: dict(recipient="Alice")),
        ),
    ]


def make(
    path,
    *,
    handler=None,
    read=None,
    actions=None,
    policy=None,
    resources=None,
    user_request="Pay Alice 10 once",
    task_id="task-1",
    catalog=None,
):
    catalog = tools(handler, read) if catalog is None else catalog
    policy = (
        ActionPolicy.exact([dict(tool="pay", arguments=PAY)] if actions is None else actions)
        if policy is None
        else policy
    )
    gateway = GovernedGateway(
        catalog,
        EvidenceStore(),
        policy,
        journal_path=path,
        task_id=task_id,
        user_request=user_request,
        resources=resources,
    )
    gateway.permit("agent_0", [tool["name"] for tool in catalog])
    return gateway


def source_policy(max_uses=1):
    return ActionPolicy.from_document(
        dict(
            version=1,
            grants=[
                dict(
                    id="pay-lookup",
                    tool="pay",
                    max_uses=max_uses,
                    arguments=dict(
                        recipient=dict(source=dict(tool="lookup", arguments=dict(user="alice"), path="/recipient")),
                        amount=dict(exact=10),
                    ),
                )
            ],
        )
    )
