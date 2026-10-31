#!/usr/bin/env python3
"""Real CLI + bundled citation grammar + native Dolt snapshot smoke."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from kctx.config import write_config
from kctx.graph.dolt_store import DoltStore
from kctx.graph.generation import completed_snapshot
from kctx.graph.sync import dolt_db_dir


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kctx-dolt-smoke-") as temporary:
        home = Path(temporary)
        kb = home / "kb"
        (kb / "inventory/assets").mkdir(parents=True)
        asset = {"id": "svc-api", "kind": "service", "name": "API", "owner": "fixture", "schema_version": 1}
        (kb / "inventory/assets/svc-api.json").write_text(json.dumps(asset), encoding="utf-8")
        revision = "a" * 40
        token = f"⟦cite kind=code repo=acme/w rev={revision} path=src/x.py L=1-1⟧"
        (kb / "note.md").write_text(f"API source {token}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(kb)], check=True)
        subprocess.run(["git", "-C", str(kb), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(kb), "-c", "user.name=Smoke", "-c", "user.email=smoke@example.invalid", "commit", "-qm", "fixture"], check=True)
        config = write_config(home / "config.toml", root=str(kb), graph_dir=str(home / "graph"), log_dir=str(home / "logs"))
        saved = os.environ.get("KCTX_CONFIG")
        os.environ["KCTX_CONFIG"] = str(config)
        try:
            def invoke(*arguments: str) -> dict:
                process = subprocess.run(["kctx", "--json", "graph", *arguments], cwd=home, capture_output=True, text=True, check=False)
                assert process.returncode == 0, (arguments, process.returncode, process.stdout, process.stderr)
                return json.loads(process.stdout)

            published = invoke("sync")
            assert published["status"] == "synced"
            found = invoke("uses", "code:acme/w:src/x.py")
            assert found["total"] == 1 and found["by_rel"]["cites"][0]["src_node"] == "doc:note.md"
            assert invoke("check")["parity"]["match"] is True
            store = DoltStore(dolt_db_dir())
            selected = completed_snapshot(store)
            assert selected is not None
            rows = store.sql_read(f"SELECT dst_node,rev,src_path,raw FROM edges AS OF '{selected.data_commit.val}' WHERE rel='cites'")
            assert rows == [{"dst_node": "code:acme/w:src/x.py", "rev": revision, "src_path": "note.md", "raw": token}], rows
            print(f"DOLT_INTEGRATION_OK: native snapshot {selected.data_commit.val}; exact source/target/revision/token; real CLI sync/uses/check")
        finally:
            if saved is None:
                os.environ.pop("KCTX_CONFIG", None)
            else:
                os.environ["KCTX_CONFIG"] = saved
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
