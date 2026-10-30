#!/usr/bin/env python3
"""Entry point for the kctx CLI. See README.md for the command reference.

Observability is wired here, at the actual entry point, rather than inside
cli.py's dispatch: every command gets a run_id and a top-level span for free
without touching cli.py's existing per-command handlers. -v/--verbose is
consumed here too (not registered on cli.py's own argparse), since cli.py's
parser doesn't know about it and shouldn't have to -- it's stripped from
argv before cli.main() ever sees it.
"""

import sys

from graph.observability import init_logging, span

if __name__ == "__main__":
    argv = sys.argv[1:]
    verbose = False
    clean_argv = []
    for a in argv:
        if a in ("-v", "--verbose"):
            verbose = True
        else:
            clean_argv.append(a)

    init_logging(verbose=verbose)

    from cli import main

    with span("kctx.command", argv=clean_argv):
        code = main(clean_argv)
    raise SystemExit(code)
