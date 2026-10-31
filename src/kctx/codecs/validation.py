"""Typed reference contracts for otherwise free-form runbooks and change briefs."""

from dataclasses import dataclass

from kctx.codecs.documents import parse_document
from kctx.codecs.frontmatter import split_list_value
from kctx.domain.ids import AssetId
from kctx.domain.vocabulary import RunbookLayer
from kctx.errors import KctxError


@dataclass(frozen=True, slots=True)
class RunbookReferences:
    layer: RunbookLayer | None
    assets: tuple[AssetId, ...]
    alerts: tuple[AssetId, ...]


@dataclass(frozen=True, slots=True)
class ChangeReferences:
    assets: tuple[AssetId, ...]


def decode_runbook_references(text: str) -> RunbookReferences | None:
    if not text.startswith("---"):
        return None
    fields = parse_document(text).frontmatter
    if not fields:
        return None
    raw_layer = fields.get("layer", "")
    try:
        layer = RunbookLayer(raw_layer) if raw_layer else None
    except ValueError as error:
        raise KctxError("malformed", f"bad layer {raw_layer!r}") from error
    return RunbookReferences(
        layer,
        tuple(AssetId(value) for value in split_list_value(fields.get("assets", ""))),
        tuple(AssetId(value) for value in split_list_value(fields.get("alerts", ""))),
    )


def decode_change_references(text: str) -> ChangeReferences | None:
    if not text.startswith("---"):
        return None
    fields = parse_document(text).frontmatter
    if not fields:
        return None
    return ChangeReferences(
        tuple(AssetId(value) for value in split_list_value(fields.get("assets", "")))
    )
