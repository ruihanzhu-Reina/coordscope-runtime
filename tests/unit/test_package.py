import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest


def test_core_import_does_not_load_legacy_engine_or_benchmark():
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; from teampermit.agents.session import IsolatedSession; "
            "assert not any(n == 'MAS' or n.startswith(('MAS.', 'agentdojo.', 'langgraph')) "
            "for n in sys.modules)",
        ],
        check=True,
    )


@pytest.mark.parametrize("entrypoint", ["module", "console"])
def test_cli_entrypoints_run_in_installed_environment(entrypoint):
    if entrypoint == "module":
        command = [sys.executable, "-I", "-m", "teampermit"]
    else:
        scripts = Path(sysconfig.get_path("scripts"))
        executable = scripts / ("teampermit.exe" if sys.platform == "win32" else "teampermit")
        assert executable.is_file()
        command = [str(executable)]
    help_result = subprocess.run(command + ["--help"], check=True, capture_output=True, text=True)
    assert "usage: teampermit" in help_result.stdout
    assert "{check,run,summarize}" in help_result.stdout
    run_help = subprocess.run(command + ["run", "--help"], check=True, capture_output=True, text=True)
    assert "--user-task" in run_help.stdout
    assert "--injection-task" in run_help.stdout
