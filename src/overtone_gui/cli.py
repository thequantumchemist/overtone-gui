"""
Command line entry point: `overtone-gui view [PATH]`, `overtone-gui example
[NAME]` and `overtone-gui student`.

Student mode needs the optional extra (tblite), so it is imported only when
needed and a missing extra gives an install hint instead of a traceback.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

STUDENT_HINT = (
    "Student mode needs GFN2-xTB (tblite): "
    "pip install \"overtone-gui[student]\""
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="overtone-gui",
        description="Browser app for OVERTONE: view runs, or compute small molecules.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    view = sub.add_parser("view", help="open finished runs in the browser viewer")
    view.add_argument("path", nargs="?",
                      help="run directory (save_results=True) or a vpt2_result.json")
    view.add_argument("--port", type=int, default=0, help="port (default: any free port)")
    view.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    student = sub.add_parser("student", help="compute small molecules with GFN2-xTB, "
                                             "step by step, and view the results")
    student.add_argument("--runs-dir", default=None,
                         help="where calculations are saved (default: ~/overtone-runs)")
    student.add_argument("--port", type=int, default=0, help="port (default: any free port)")
    student.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    example = sub.add_parser("example", help="open a finished example calculation "
                                             "(no calculation needed)")
    example.add_argument("name", nargs="?", help="example to open; omit to list them")
    example.add_argument("--port", type=int, default=0, help="port (default: any free port)")
    example.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    sub.add_parser("version", help="print the installed versions")

    args = parser.parse_args(argv)

    if args.command == "version":
        import overtone

        import overtone_gui
        print(f"overtone-gui {overtone_gui.__version__}, overtone-vpt2 {overtone.__version__}")
        return 0

    if args.command == "view":
        if args.path is not None:
            from overtone_gui.run_data import RunData, RunDirectoryError
            try:
                RunData.load(args.path)  # fail here, not in the browser
            except (RunDirectoryError, OSError, ValueError) as err:
                print(f"overtone-gui view: {err}", file=sys.stderr)
                return 1
        from overtone_gui.app import serve
        serve(args.path, port=args.port, show=not args.no_browser)
        return 0

    if args.command == "example":
        from overtone_gui.run_data import EXAMPLES, RunDirectoryError, example_path
        if args.name is None:
            print("Examples (open one with: overtone-gui example <name>):")
            for key, title in EXAMPLES.items():
                print(f"  {key:16s} {title}")
            return 0
        try:
            path = example_path(args.name)
        except RunDirectoryError as err:
            print(f"overtone-gui example: {err}", file=sys.stderr)
            return 1
        from overtone_gui.app import serve
        serve(path, port=args.port, show=not args.no_browser)
        return 0

    if args.command == "student":
        # tblite parallelises each tiny single point over all cores, which is
        # slower than one thread for small molecules (OVERTONE manual)
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        try:
            import tblite.ase  # noqa: F401
        except ImportError:
            print(STUDENT_HINT, file=sys.stderr)
            return 1
        from overtone_gui.app import serve
        serve(student=True, runs_dir=args.runs_dir, port=args.port, show=not args.no_browser)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
