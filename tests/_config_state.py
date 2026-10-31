"""One config-file owner shared by both unittest import styles."""

import os
import tempfile
from pathlib import Path


_directory = tempfile.TemporaryDirectory(prefix="kctx-test-cfg-")
file = Path(_directory.name) / "config.toml"
values: dict[str, str | int] = {}
file.write_text("", encoding="utf-8")
os.environ["KCTX_CONFIG"] = str(file)
