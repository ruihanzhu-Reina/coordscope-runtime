import pytest
from agentdojo.task_suite.load_suites import get_suites

from coordscope.security.manifest import TOOL_MANIFEST, effect, tool_spec


def test_every_official_tool_has_an_explicit_effect():
    for suite in get_suites("v1.2.2").values():
        for tool in suite.tools:
            assert effect(tool.name) != "unknown"
            assert tool_spec(tool.name).argument_sensitivity == "all"
    assert effect("get_execute_payment") == "unknown"
    assert effect("get_webpage") == "navigate"
    assert effect("get_unread_emails") == "consume"
    with pytest.raises(TypeError):
        TOOL_MANIFEST["invented_tool"] = tool_spec("get_balance")
