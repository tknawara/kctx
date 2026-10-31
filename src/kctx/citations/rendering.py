"""Human-readable citation rendering; citation fields are never executed."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from urllib.parse import urlsplit

from kctx.adapters.files.contained import contained_markdown
from kctx.adapters.git.citations import repo_from_url
from kctx.citations.classification import classify_code
from kctx.citations.construction import QUERY_ALIASES
from kctx.citations.models import CitationStatus
from kctx.citations.records import load_evidence_record
from kctx.citations.redaction import apply_redact_fields
from kctx.citations.syntax import find_cite_lines
from kctx.citations.time import today_str
from kctx.config import Config
from kctx.errors import KctxError
from kctx.redaction import mask_secrets

TICKET_ID_RE = re.compile(r"^([A-Za-z]{2,6})\s?(\d+)$")


@dataclass(frozen=True, slots=True)
class _Rendered:
    text: str
    url: str | None = None


def redact_text(text: str, redact_spec: str | None) -> str:
    return mask_secrets(apply_redact_fields(text, redact_spec))


def _host_for(fields: Mapping[str, str], config: Config) -> str:
    url = fields.get("url", "")
    match = re.search(r"@([\w.-]+):", url)
    if match and "." in match.group(1):
        return match.group(1)
    match = re.match(r"^https?://([^/]+)/", url)
    return match.group(1) if match else config.github_host


def _org_repo(fields: Mapping[str, str]) -> tuple[str | None, str | None]:
    repo = fields.get("repo", "")
    if "/" in repo:
        org, name = repo.split("/", 1)
        return org, name
    parsed = repo_from_url(fields.get("url", ""))
    return parsed if parsed else (None, repo or None)


def _render_code(fields: Mapping[str, str], do_check: bool, config: Config) -> _Rendered:
    org, name = _org_repo(fields)
    rev, path, lines = fields.get("rev", ""), fields.get("path", ""), fields.get("L", "")
    bounds = lines.split("-")
    anchor = (
        f"#L{bounds[0]}-L{bounds[1]}"
        if len(bounds) == 2 and bounds[0] != bounds[1]
        else f"#L{bounds[0]}"
    )
    url = (
        f"https://{_host_for(fields, config)}/{org}/{name}/blob/{rev}/{path}{anchor}"
        if org
        else None
    )
    parts = [url or f"(unresolved repo) {fields.get('repo')}:{path}{anchor}"]
    if fields.get("sym"):
        parts.append(f"({fields['sym']})")
    if fields.get("seen"):
        parts.append(f"as of {fields['seen']}")
    if do_check:
        result = classify_code(fields, config=config)
        if result.status is CitationStatus.FRESH:
            parts.append(f"verified fresh {today_str()}")
        elif result.status is CitationStatus.CHANGED:
            parts.append(f"logic changed since {fields.get('seen')}")
        elif result.status is CitationStatus.MOVED:
            parts.append(f"moved to L={result.line_range} since {fields.get('seen')}")
        elif result.status is CitationStatus.GONE:
            parts.append("path no longer exists")
        else:
            parts.append(f"could not verify ({result.reason or 'source unreachable'})")
    return _Rendered(" — ".join(parts), url)


def _render_query(fields: Mapping[str, str]) -> _Rendered:
    system = fields.get("sys") or fields.get("kind", "query")
    window = f" over {fields['window']}" if fields.get("window") else ""
    result = fields.get("result") or (
        f"{fields['rows']} rows" if fields.get("rows") else "(no summary recorded)"
    )
    text = (
        f"{system} query run {fields.get('seen', '')}{window}: `{fields.get('q', '')}` → {result}"
    )
    if fields.get("ev"):
        text += f"; results: {fields['ev']}"
    return _Rendered(text)


def _render(fields: Mapping[str, str], do_check: bool, config: Config) -> _Rendered:
    kind = fields.get("kind", "")
    canonical = "query" if kind in QUERY_ALIASES else kind
    if canonical == "code":
        return _render_code(fields, do_check, config)
    if canonical in ("commit", "pr"):
        org, name = _org_repo(fields)
        suffix = (
            f"commit/{fields.get('rev', '')}"
            if canonical == "commit"
            else f"pull/{fields.get('n', '')}"
        )
        url = f"https://{_host_for(fields, config)}/{org}/{name}/{suffix}" if org else None
        if canonical == "commit":
            return _Rendered(url or f"commit {fields.get('rev', '')} in {fields.get('repo')}", url)
        base = url or f"{fields.get('repo')}#{fields.get('n', '')}"
        return _Rendered(f"{base} ({fields['state']})" if fields.get("state") else base, url)
    if canonical == "ticket":
        identifier = fields.get("id", "")
        match = TICKET_ID_RE.fullmatch(identifier)
        return _Rendered(f"{{{match.group(1).upper()} {match.group(2)}}}" if match else identifier)
    if canonical in ("doc", "web"):
        url = fields.get("url", "")
        text = url + (f"#{fields['section']}" if fields.get("section") else "")
        if fields.get("quote"):
            text += f' — "{fields["quote"]}"'
        return _Rendered(text, url or None)
    if canonical == "query":
        return _render_query(fields)
    if canonical == "usr":
        return _Rendered(
            f'{fields.get("who", "User")} said on {fields.get("date", "")}: "{fields.get("quote", "")}"'
        )
    if canonical == "ev":
        identifier = fields.get("id", "")
        record = load_evidence_record(identifier, config=config)
        return _Rendered(
            f"ev:{identifier} (record not found)"
            if record is None
            else f"ev:{identifier}\nsource: {record.source}\n---\n{record.excerpt}"
        )
    if canonical == "breg":
        return _Rendered(
            f"BREG {fields.get('name')} [{fields.get('env')}] = {fields.get('value', '(unknown)')} (as of {fields.get('seen')})"
        )
    if canonical == "deploy":
        asset = fields.get("asset") or fields.get("service")
        return _Rendered(
            f"{asset} [{fields.get('env')}] = {fields.get('version', '(unknown)')} (as of {fields.get('seen')})"
        )
    if canonical == "proposal":
        return _Rendered(
            f"proposal {fields.get('id')} ({fields.get('state')} as of {fields.get('seen')})"
        )
    if canonical == "gate":
        return _Rendered(
            f"gate {fields.get('gate')} of proposal {fields.get('proposal')}: {fields.get('outcome')} at {fields.get('rev')}"
        )
    if canonical == "record":
        return _Rendered(
            f"record {fields.get('path')} ({fields.get('state')} as of {fields.get('seen')})"
        )
    return _Rendered(f"(no renderer for kind={kind!r})")


def _format_output(text: str, url: str | None, fmt: str) -> str:
    if fmt == "html":
        body = escape(text)
        if url and url in text and urlsplit(url).scheme in ("http", "https"):
            safe_url = escape(url, quote=True)
            return body.replace(safe_url, f'<a href="{safe_url}">{safe_url}</a>')
        return body
    if not url or url not in text or urlsplit(url).scheme not in ("http", "https"):
        return text
    if fmt == "md":
        return text.replace(url, f"[{url}]({url})")
    if fmt == "slack":
        return text.replace(url, f"<{url}>")
    return text


def render_one(
    fields: Mapping[str, str],
    fmt: str = "plain",
    audience: str = "internal",
    unredacted: bool = False,
    do_check: bool = False,
    *,
    config: Config | None = None,
) -> str:
    sensitivity = fields.get("sens", "internal")
    if audience == "external" and sensitivity != "public":
        return _format_output("[internal reference withheld]", None, fmt)
    if sensitivity == "restricted" and not unredacted:
        return _format_output("[restricted — use --unredacted to view]", None, fmt)
    rendered = _render(fields, do_check, config or Config.load())
    return _format_output(redact_text(rendered.text, fields.get("redact")), rendered.url, fmt)


def extract_cite_items(target: str) -> list[tuple[dict[str, str], str]]:
    items: list[tuple[dict[str, str], str]]
    if "⟦cite" in target:
        items = [(fields, match.group(0)) for match, fields in find_cite_lines(target)]
        if not items:
            raise KctxError("malformed", "no ⟦cite …⟧ found in given text")
        return items
    with contained_markdown([target]) as sources:
        items = []
        for source in sources:
            if not source.root_is_file:
                raise KctxError(
                    "malformed", "citation render target must be a file or literal token"
                )
            items.extend(
                (fields, match.group(0)) for match, fields in find_cite_lines(source.text())
            )
    if not items:
        raise KctxError("not-found", f"no ⟦cite …⟧ found in {target}")
    return items
