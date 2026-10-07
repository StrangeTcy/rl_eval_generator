"""Run the unchanged accepted CS001-CS011 regression tests against target code."""
from pathlib import Path
import sys

ENGINE_FILES = Path(__file__).resolve().parents[2] / "envs" / "epistemic_reasoning" / "files"
if str(ENGINE_FILES) not in sys.path:
    sys.path.insert(0, str(ENGINE_FILES))
