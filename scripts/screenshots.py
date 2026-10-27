"""Dev tool: writes the README screenshots to docs/screenshots. Usage: .venv/bin/python scripts/screenshots.py [--out DIR]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from xbot.sample import shots_cli as cli  # noqa: E402

if __name__ == "__main__":
    import os
    os.environ.setdefault("XBOT_CWD", str(ROOT))
    sys.exit(cli(sys.argv[1:]))
