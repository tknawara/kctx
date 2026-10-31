"""Assert the Viper-annotated twin and the executable runtime twin have
token-identical bodies (contract constructs stripped). Drift here means the
grid is executing something Viper never verified — the job must fail."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def body_tokens(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "assess_fresh_tagged"
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


a = body_tokens(HERE / "assess_fresh_contracts.py")
b = body_tokens(HERE / "twin_runtime.py")
if a != b:
    print("DRIFT: annotated twin body != runtime twin body")
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            print(f"  stmt {i}: annotated={x[:80]} runtime={y[:80]}")
    sys.exit(1)
print(f"twin drift check: PASS ({len(a)} statements identical)")
