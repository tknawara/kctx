#!/usr/bin/env python3
"""Dolt shadow-graph integration smoke (compose verify stage 5).

Builds a throwaway KB with one asset + one durable code citation, runs the
real `kctx graph sync` (which shells out to the real `dolt` CLI), and
asserts nodes/edges landed in a real throwaway Dolt database. The citation
parser is the container stub (config cite_py=docker/cite_stub.py) — this
verifies the *integration* (extractor -> sync -> dolt SQL round trip), not
the real citation grammar (that needs the dotfiles skill; G13).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    stub = ROOT / "docker" / "cite_stub.py"
    if not stub.is_file():
        print("SKIP: container cite stub missing (host run)")
        return 3
    kb = Path(tempfile.mkdtemp())
    # one config file instead of three env vars (docs/kctx/config.md)
    sys.path.insert(0, str(ROOT / "src"))
    from kctx.config import write_config

    os.environ["KCTX_CONFIG"] = str(
        write_config(
            kb / "config.toml",
            root=str(kb),
            cite_py=str(stub),
            graph_dir=str(kb / "graphdir"),
        )
    )
    (kb / "inventory" / "assets").mkdir(parents=True)
    (kb / "inventory" / "assets" / "a1.json").write_text(
        '{"id":"a1","kind":"service","name":"S","locator":"x","owner":"o",'
        '"owner_source":"s","schema_version":1}'
    )
    (kb / "note.md").write_text(
        "claim \u27e6cite repo=acme/w rev=deadbeef path=src/x.py L=1-1 kind=code\u27e7\n"
    )
    subprocess.run(["git", "init", "-q", str(kb)], check=True)
    subprocess.run(["git", "-C", str(kb), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(kb), "-c", "user.email=v@e", "-c", "user.name=v",
         "commit", "-qm", "kb"], check=True)

    from kctx.graph import sync

    sync.sync(kb)
    q = sync.DoltStore(sync.dolt_db_dir())
    n = q.sql_read("SELECT COUNT(*) AS n FROM nodes")[0]["n"]
    e = q.sql_read("SELECT COUNT(*) AS n FROM edges")[0]["n"]
    print(f"dolt smoke: nodes={n} edges={e}")
    if n < 2 or e < 1:
        print("FAIL: expected >=2 nodes and >=1 edge in the throwaway Dolt db")
        return 1
    print("DOLT_INTEGRATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
