#!/usr/bin/env python3
"""Entry point for the kctx CLI. See README.md for the command reference.

Application-boundary logging lives in kctx.observability (handover 7.2);
it no longer couples every invocation to the graph package. -v/--verbose
is consumed here, before cli.main sees argv.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _init_logging(verbose: bool) -> None:
    try:
        from kctx.observability import init_logging
    except ImportError:  # pydantic/structlog absent in a bare interpreter
        return
    init_logging(verbose=verbose)


if __name__ == "__main__":
    argv = sys.argv[1:]
    verbose = False
    clean_argv = []
    for a in argv:
        if a in ("-v", "--verbose"):
            verbose = True
        else:
            clean_argv.append(a)

    _init_logging(verbose=verbose)

    from cli import main

    raise SystemExit(main(clean_argv))
