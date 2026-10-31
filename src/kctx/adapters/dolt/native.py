"""Native Dolt backup restore without consulting or changing user author config."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kctx.errors import KctxError
from kctx.observability import run_logged


@contextmanager
def _configuration(destination: Path, retained: Path | None) -> Iterator[Path]:
    if retained is not None:
        retained.mkdir(parents=True, exist_ok=False)
        yield retained.resolve()
    else:
        with tempfile.TemporaryDirectory(
            prefix=".kctx-dolt-restore-", dir=destination.parent
        ) as name:
            yield Path(name)


def restore_backup(
    source: Path, destination: Path, *, dolt_bin: str, config_root: Path | None = None
) -> None:
    """Restore every native ref into a new destination, never with ``--force``.

    Dolt's restore operation creates an initial commit and requires an author.
    DOLT_ROOT_PATH is an internal per-operation process environment, not a user
    configuration override: the real user's global config is never read/written.
    A supplied configuration directory remains with the operation's audit data.
    """
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_dir():
        raise KctxError("not-found", "native Dolt backup directory does not exist")
    if destination.exists():
        raise KctxError("conflict", "native restore requires a nonexistent destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _configuration(destination, config_root) as configuration:
        command = ["env", f"DOLT_ROOT_PATH={configuration}", dolt_bin]
        for args, cwd in (
            (
                [
                    "config",
                    "--global",
                    "--add",
                    "user.name",
                    "kctx-restore",
                    "user.email",
                    "kctx-restore@localhost",
                ],
                destination.parent,
            ),
            (["backup", "restore", source.as_uri(), destination.name], destination.parent),
            (
                [
                    "config",
                    "--local",
                    "--add",
                    "user.name",
                    "kctx-restore",
                    "user.email",
                    "kctx-restore@localhost",
                ],
                destination,
            ),
        ):
            result = run_logged([*command, *args], cwd=cwd, check=False)
            if result.returncode:
                raise KctxError(
                    "conflict",
                    result.stderr.strip() or result.stdout.strip() or "native Dolt restore failed",
                )
