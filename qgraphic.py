from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run a .qgk program")
    parser.add_argument("file", help="Path to .qgk file")
    args = parser.parse_args(argv)

    from Interpreter.interpreter import run_file

    run_file(Path(args.file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
