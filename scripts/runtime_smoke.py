#!/usr/bin/env python3
"""Exercise the installed CLI from an unrelated directory without proof tools."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from kctx.config import write_config


def main() -> int:
    forbidden = ("lean", "lake", "elan", "docker")
    assert all(shutil.which(tool) is None for tool in forbidden), "runtime image contains proof/container tools"
    assert not Path("/app/formal").exists(), "runtime contains formal sources"
    executable = shutil.which("kctx")
    assert executable is not None, "installed entry point missing"
    with tempfile.TemporaryDirectory(prefix="kctx-runtime-") as temporary:
        base = Path(temporary)
        kb, elsewhere = base / "knowledge", base / "elsewhere"
        kb.mkdir()
        elsewhere.mkdir()
        config = write_config(base / "config.toml", root=str(kb), log_dir=str(base / "logs"))
        environment = {**os.environ, "KCTX_CONFIG": str(config), "HOME": str(base)}

        def invoke(*arguments: str, code: int = 0) -> dict:
            process = subprocess.run([executable, "--json", *arguments], cwd=elsewhere, env=environment, capture_output=True, text=True)
            assert process.returncode == code, (arguments, process.returncode, process.stdout, process.stderr)
            result = json.loads(process.stdout)
            assert isinstance(result, dict), result
            return result

        asset = invoke("asset", "add", "--kind", "service", "--name", "API", "--id", "svc-api", "--alias", "public-api")
        assert asset["id"] == "svc-api"
        assert invoke("asset", "show", "public-api")["id"] == "svc-api"
        refused = invoke("asset", "add", "--kind", "invalid", "--name", "bad", code=1)
        assert refused["error"] == "malformed"
        assert len(tuple((kb / "inventory/assets").glob("*.json"))) == 1
        run = invoke("run", "new", "--project", "demo", "--mode", "review", "--task", "Inspect local document")
        observation = invoke("observe", run["run_id"], "--system", "doc", "--locator", "guide.md", "--asset", "svc-api")
        covered = invoke("cover", run["run_id"], "--item", "guide-reviewed", "--outcome", "supported", "--evidence", observation["id"])
        assert covered["outcome"] == "supported"
        receipt = invoke("check", run["run_id"], "--require", "guide-reviewed")
        assert receipt["missing_required"] == []
        proposal = invoke("proposal", "add", "--kind", "config", "--origin", "user-request", "--title", "Document API", "--context", "Explain service", "--evidence", observation["id"], "--change", "Write guide", "--why", "Scoped documentation")
        assert proposal["frontmatter"]["status"] == "draft"
        blocked = invoke("proposal", "set", proposal["id"], "--status", "proposed", code=1)
        assert blocked["error"] == "incomplete"
        assert invoke("proposal", "show", proposal["id"])["frontmatter"]["status"] == "draft"
        assert not tuple(elsewhere.iterdir()), "writes escaped configured KB"
        module = subprocess.run(["python3", "-m", "kctx", "--json", "asset", "show", "svc-api"], cwd=elsewhere, env=environment, capture_output=True, text=True)
        assert module.returncode == 0 and json.loads(module.stdout)["id"] == "svc-api"
        print("RUNTIME_SMOKE_OK: installed/module entry; explicit KB; asset alias; malformed enum refusal; observation/coverage/check; draft readiness; no Lean/Docker/formal files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
