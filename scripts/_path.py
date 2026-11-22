"""Make the cfe_eval package importable when a script is run from any folder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
