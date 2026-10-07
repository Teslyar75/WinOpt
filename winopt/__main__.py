from __future__ import annotations

import sys


def _entry() -> int:
    if len(sys.argv) <= 1:
        from winopt.gui import run_gui

        return run_gui()
    from winopt.cli import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_entry())
