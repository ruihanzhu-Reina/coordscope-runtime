"""Never permit a live provider call in the test suite."""

import os

os.environ["MAS_DISABLE_LIVE_LLM"] = "1"
