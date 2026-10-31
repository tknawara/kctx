"""Correction schema, review statuses, and target resolution validation."""

from pathlib import Path

import kctx.services.corrections as corrections
from kctx.errors import KctxError
from kctx.services.validation_common import Diagnostics, read_record


def validate_corrections(root: Path, diagnostics: Diagnostics) -> int:
    paths = corrections.all_paths(root)
    for path in paths:
        # The typed decoder validates closed row statuses and unchanged evidence.
        parsed = read_record(path, corrections.parse, diagnostics)
        if parsed is None:
            continue
        target = parsed.frontmatter.target
        try:
            resolves = corrections.target_resolves(root, target)
        except (KctxError, ValueError, OSError) as error:
            diagnostics.malformed(path, error)
            continue
        if not resolves:
            diagnostics.problem(
                "incomplete", str(path), f"target {target.spelling!r} does not resolve"
            )
    return len(paths)
