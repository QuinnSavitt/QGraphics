from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser(description="QGraphic CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    exec_parser = sub.add_parser("exec", help="Execute a .qgk file")
    exec_parser.add_argument("file", help="Path to .qgk file")

    gui_parser = sub.add_parser("gui", help="Open the GUI editor")
    gui_parser.add_argument("file", nargs="?", help="Optional .qgc file to load")

    args = parser.parse_args(argv)

    if args.cmd == "exec":
        from Interpreter.interpreter import run_file
        run_file(Path(args.file))
        return 0

    if args.cmd == "gui":
        from PyQt5.QtWidgets import QApplication
        from Engine.engine import Frame
        from GUI.framedisplayer import LedMatrixWidget, deserialize_frame

        app = QApplication.instance() or QApplication([])
        frame = Frame()
        if args.file:
            data = Path(args.file).read_bytes()
            frame.display = deserialize_frame(data)
        w = LedMatrixWidget(frame)
        w.show()
        app.exec_()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
