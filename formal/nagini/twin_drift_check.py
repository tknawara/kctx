"""Assert the Viper-annotated twin and the executable runtime twin have
token-identical bodies (contract constructs stripped). Drift here means the
grid is executing something Viper never verified — the job must fail."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


PAIRS = [
    ("assess_fresh_tagged", "assess_fresh_contracts.py", "twin_runtime.py"),
    ("usable_for_tagged", "usable_for_contracts.py", "usable_for_runtime.py"),
]


def body_tokens(path: Path, fn_name: str) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == fn_name
    )
    # drop contract call statements (Requires/Ensures) and comments; keep logic
    def is_noise(st) -> bool:
        # contract calls and the docstring: verification artifacts, not logic
        if isinstance(st, ast.Expr):
            if isinstance(st.value, ast.Constant) and isinstance(
                st.value.value, str
            ):
                return True  # docstring
            if (
                isinstance(st.value, ast.Call)
                and isinstance(st.value.func, ast.Name)
                and st.value.func.id in ("Requires", "Ensures")
            ):
                return True
        return False

    return [ast.dump(st) for st in fn.body if not is_noise(st)]


ok = True
for fn_name, annotated, runtime in PAIRS:
    a = body_tokens(HERE / annotated, fn_name)
    b = body_tokens(HERE / runtime, fn_name)
    if a != b:
        ok = False
        print(f"DRIFT: {fn_name} ({annotated} != {runtime})")
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                print(f"  stmt {i}: annotated={x[:80]} runtime={y[:80]}")
    else:
        print(f"twin drift check: PASS {fn_name} ({len(a)} statements identical)")
if not ok:
    sys.exit(1)
