"""Supports Modules 2 and 4 — downloads of what was read from a document.

Responsibility: turn a document's saved page view (page_store.load) into files:
- txt: the page text (reading order)
- layout: monospace text with the page's spacing, indentation, and columns kept
- md: Markdown with titles as headings, tables as Markdown tables, figures and captions marked
- csv: the tables found (one table: a .csv file; several: a .zip with one .csv per table)
- json: everything: text, confidences, recognised lines, layout regions, typed blocks

Uses from schemas.py: nothing directly.
"""

import csv
import io
import json
import zipfile

FORMATS = ("txt", "layout", "md", "csv", "json")


class ExportError(ValueError):
    """The document has nothing to export in the requested format (e.g. no tables for csv)."""


def _join_pages(pages: list[dict], text_of) -> str:
    if len(pages) == 1:
        return text_of(pages[0]).rstrip() + "\n"
    return "\n\n".join(f"===== Page {p['page']} =====\n{text_of(p).rstrip()}" for p in pages) + "\n"


def to_txt(pages: list[dict]) -> bytes:
    return _join_pages(pages, lambda p: p.get("text") or "").encode("utf-8")


def to_layout(pages: list[dict]) -> bytes:
    return _join_pages(pages, lambda p: p.get("layout_text") or p.get("text") or "").encode("utf-8")


def _md_cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def markdown_table(rows: list[list[str]]) -> str:
    width = max((len(r) for r in rows), default=0)
    if not width:
        return ""
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(_md_cell(c) for c in rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _region_md(region: dict) -> str:
    kind, text = region["type"], (region.get("text") or "").strip()
    if kind == "table" and region.get("rows"):
        return markdown_table(region["rows"])
    if kind == "title":
        return f"### {' '.join(text.split())}" if text else ""
    if kind == "figure":
        return "*[Figure]*" + (f" {' '.join(text.split())}" if text else "")
    if kind == "caption":
        return f"*{' '.join(text.split())}*" if text else ""
    if kind == "formula":
        return f"`{' '.join(text.split())}`" if text else ""
    if kind in ("header", "footer"):
        return f"<small>{' '.join(text.split())}</small>" if text else ""
    return text


def _block_md(block: dict) -> str:
    kind, text = block["type"], (block.get("text") or "").strip()
    if kind == "table" and block.get("rows"):
        return markdown_table(block["rows"])
    if kind == "image":
        return "*[Picture]*" + (f" {text}" if text else "")
    return text


def page_markdown(page: dict) -> str:
    if page.get("regions"):
        parts = [_region_md(r) for r in page["regions"]]
    elif page.get("blocks"):
        parts = [_block_md(b) for b in page["blocks"]]
    else:
        parts = [page.get("text") or ""]
    return "\n\n".join(p for p in parts if p)


def to_md(pages: list[dict], title: str) -> bytes:
    body = [f"# {title}"]
    for p in pages:
        if len(pages) > 1:
            body.append(f"## Page {p['page']}")
        body.append(page_markdown(p))
    return ("\n\n".join(b for b in body if b) + "\n").encode("utf-8")


def tables(pages: list[dict]) -> list[tuple[int, list[list[str]]]]:
    """(page number, rows) for every table: layout regions (scans) and typed blocks."""
    found = []
    for p in pages:
        for item in (p.get("regions") or []) + (p.get("blocks") or []):
            if item.get("type") == "table" and item.get("rows"):
                found.append((p["page"], item["rows"]))
    return found


def _csv_bytes(rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue().encode("utf-8-sig")  # BOM: Excel opens UTF-8 correctly


def to_csv(pages: list[dict]) -> tuple[bytes, str, str]:
    """(content, media type, file extension). Raises ExportError when there are no tables."""
    found = tables(pages)
    if not found:
        raise ExportError("No tables were found in this document")
    if len(found) == 1:
        return _csv_bytes(found[0][1]), "text/csv; charset=utf-8", "csv"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        counts: dict[int, int] = {}
        for page, rows in found:
            counts[page] = counts.get(page, 0) + 1
            archive.writestr(f"page{page}_table{counts[page]}.csv", _csv_bytes(rows))
    return buffer.getvalue(), "application/zip", "zip"


def to_json(pages: list[dict], document: dict) -> bytes:
    keep = ("page", "text", "conf", "layout_text", "regions", "blocks", "lines")
    payload = {**document, "pages": [{k: p[k] for k in keep if k in p} for p in pages]}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
