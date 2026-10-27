import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AEGIS_DB", ":memory:")  # tests never touch data/aegis.db
