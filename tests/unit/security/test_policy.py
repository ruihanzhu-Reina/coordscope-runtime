"""Host-policy boundary tests: no model, network, or external effects."""

import copy
from dataclasses import FrozenInstanceError

import pytest

from coordscope.security.policy import ActionPolicy


def catalog():
    return [
        dict(
            name="send_money",
            effect="mutate",
            parameters=dict(properties=dict(recipient={}, amount={}, memo={}), required=["recipient", "amount"]),
        ),
        dict(name="lookup_account", effect="read", parameters=dict(properties=dict(user_id={}), required=["user_id"])),
    ]


def document():
    return dict(
        version=1,
        grants=[
            dict(
                id="pay-alice",
                tool="send_money",
                max_uses=1,
                arguments=dict(
                    recipient=dict(source=dict(tool="lookup_account", arguments=dict(user_id="alice"), path="/iban")),
                    amount=dict(exact=10),
                ),
            )
        ],
    )


def proof():
    return dict(
        parameter="recipient",
        verified=True,
        freshness_verified=True,
        origin="external_tool_result",
        tool="lookup_account",
        arguments=dict(user_id="alice"),
        path="/iban",
        value="ALICE-IBAN",
    )


ARGS = dict(recipient="ALICE-IBAN", amount=10)


def test_empty_policy_and_wrong_exact_actions_deny():
    assert ActionPolicy().authorize("send_money", ARGS) is None
    policy = ActionPolicy.exact([dict(tool="send_money", arguments=ARGS)]).validate(catalog())
    assert policy.authorize("send_money", ARGS).max_uses == 1
    assert policy.authorize("send_money", dict(recipient="MALLORY", amount=1000)) is None
    assert policy.authorize("send_money", {**ARGS, "memo": "injected"}) is None
    assert policy.authorize("send_money", dict(recipient="ALICE-IBAN")) is None
    assert policy.authorize("other_tool", ARGS) is None


def test_declared_dynamic_source_allows_only_host_verified_exact_field():
    policy = ActionPolicy.from_document(document()).validate(catalog())
    grant = policy.authorize("send_money", ARGS, [proof()])
    assert grant.id == "pay-alice"
    assert grant.max_uses == 1
    assert policy.authorize("send_money", ARGS) is None
    assert policy.authorize("send_money", {**ARGS, "amount": 1000}, [proof()]) is None


@pytest.mark.parametrize(
    "change",
    [
        dict(verified=False),
        dict(freshness_verified=False),
        dict(origin="model_result"),
        dict(tool="__quarantined_result__"),
        dict(tool="__agent_result__"),
        dict(tool="other_lookup"),
        dict(arguments=dict(user_id="mallory")),
        dict(path="/other_iban"),
        dict(value="MALLORY-IBAN"),
    ],
)
def test_wrong_source_or_unverified_proof_cannot_authorize(change):
    policy = ActionPolicy.from_document(document())
    assert policy.authorize("send_money", ARGS, [proof() | change]) is None


def test_duplicate_proofs_and_overlapping_grants_fail_closed():
    policy = ActionPolicy.from_document(document())
    assert policy.authorize("send_money", ARGS, [proof(), proof()]) is None
    assert policy.authorize("send_money", ARGS, [proof() | dict(parameter="not-an-argument")]) is None
    assert policy.authorize("send_money", ARGS, [proof() | dict(parameter=[])]) is None
    overlap = document()
    overlap["grants"].append(
        dict(id="exact-alice", tool="send_money", arguments={k: dict(exact=v) for k, v in ARGS.items()})
    )
    assert ActionPolicy.from_document(overlap).authorize("send_money", ARGS, [proof()]) is None


def test_immutable_policy_and_detached_exports_keep_stable_fingerprint():
    supplied = document()
    policy = ActionPolicy.from_document(supplied)
    fingerprint = policy.fingerprint
    supplied["grants"][0]["arguments"]["amount"]["exact"] = 1000
    exported = policy.to_document()
    exported["grants"][0]["arguments"]["amount"]["exact"] = 2000
    policy.grants[0].arguments["amount"]["exact"] = 3000
    assert policy.authorize("send_money", ARGS, [proof()]) is not None
    assert policy.fingerprint == fingerprint
    assert ActionPolicy.from_document(policy.to_document()).fingerprint == fingerprint
    with pytest.raises(FrozenInstanceError):
        policy.grants = ()


def test_exact_ids_and_fingerprints_ignore_dictionary_order():
    left = ActionPolicy.exact([dict(tool="send_money", arguments=ARGS)])
    right = ActionPolicy.exact([dict(arguments=dict(amount=10, recipient="ALICE-IBAN"), tool="send_money")])
    assert left.grants[0].id == right.grants[0].id
    assert left.fingerprint == right.fingerprint


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=True),
        lambda d: d.update(version=True),
        lambda d: d.update(version=2),
        lambda d: d.update(grants={}),
        lambda d: d["grants"][0].update(extra=True),
        lambda d: d["grants"][0].update(max_uses=True),
        lambda d: d["grants"][0].update(max_uses=0),
        lambda d: d["grants"][0]["arguments"]["amount"].update(free=True),
        lambda d: d["grants"][0]["arguments"].update(amount=dict(free=True)),
        lambda d: d["grants"][0]["arguments"]["recipient"]["source"].update(tool="__agent_result__"),
        lambda d: d["grants"][0]["arguments"]["recipient"]["source"].update(path="/bad~2escape"),
        lambda d: d["grants"].append(copy.deepcopy(d["grants"][0])),
        lambda d: d["grants"][0]["arguments"].update(amount=dict(exact=float("nan"))),
    ],
)
def test_invalid_or_ambiguous_policy_rejected(mutate):
    supplied = document()
    mutate(supplied)
    with pytest.raises(ValueError):
        ActionPolicy.from_document(supplied)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["grants"][0].update(tool="missing"),
        lambda d: d["grants"][0]["arguments"].pop("amount"),
        lambda d: d["grants"][0]["arguments"].update(undeclared=dict(exact=1)),
        lambda d: d["grants"][0]["arguments"]["recipient"]["source"].update(tool="missing"),
        lambda d: d["grants"][0]["arguments"]["recipient"]["source"].update(arguments={}),
    ],
)
def test_policy_and_lookup_must_match_trusted_catalog(mutate):
    supplied = document()
    mutate(supplied)
    with pytest.raises(ValueError):
        ActionPolicy.from_document(supplied).validate(catalog())


def test_catalog_requires_explicit_host_effect_and_unique_names():
    tools = catalog()
    tools[0].pop("effect")
    with pytest.raises(ValueError):
        ActionPolicy().validate(tools)
    with pytest.raises(ValueError):
        ActionPolicy().validate(catalog() + [catalog()[0]])
