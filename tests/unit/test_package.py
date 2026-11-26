import subprocess
import sys


def test_core_import_does_not_load_legacy_engine_or_benchmark():
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; from coordscope.agents.session import IsolatedSession; "
            "assert not any(n == 'MAS' or n.startswith(('MAS.', 'agentdojo.', 'langgraph')) "
            "for n in sys.modules)",
        ],
        check=True,
    )
