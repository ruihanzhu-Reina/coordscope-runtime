from coordscope.evaluation.metrics import official_outcomes, resource_metrics, summarize


def test_clean_security_sentinel_is_not_an_attack_success():
    clean = official_outcomes(True, True, clean=True)
    assert clean["task_success"] is True
    assert clean["attack_success"] is None


def test_failed_or_scripted_run_is_not_a_safety_win():
    for kwargs in ({"error_status": "INFRA_ERROR"}, {"mock_used": True}):
        result = official_outcomes(False, False, clean=False, **kwargs)
        assert not result["evaluation_valid"]
        assert result["attack_success"] is None


def test_summary_denominators_and_usage_are_explicit():
    rows = [
        dict(condition="clean", **official_outcomes(True, True, clean=True)),
        dict(condition="attack", attack_exposed=True, **official_outcomes(True, False, clean=False)),
        dict(condition="attack", **official_outcomes(False, False, clean=False, error_status="TIMEOUT")),
    ]
    result = summarize(rows)
    assert result["attempted_episodes"] == 3
    assert result["valid_episodes"] == 2
    assert result["targeted_asr"] == 0
    assert result["attack_n"] == 1
    assert resource_metrics([], mock_used=False)["tokens"] is None
