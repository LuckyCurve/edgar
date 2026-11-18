from __future__ import annotations

import re

from edgar.base.errors import NotFoundError, ParseError
from edgar.base.html import (
    Block,
    extract_text,
    iter_blocks,
    looks_like_html,
    normalize_text,
    parse_document,
)
from edgar.base.http import TTL_DOCUMENT
from edgar.base.refs import filing_doc_url
from edgar.base.sections import extract_sections
from edgar.base.submissions import find_filing

_PLAIN_LINE_RE = re.compile(r"[ \t ]+")


def _clean_plain_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    lines = [_PLAIN_LINE_RE.sub(" ", line).strip() for line in value.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_document(
    client,
    cik: str | int,
    accession: str,
    name: str | None = None,
    filing: dict | None = None,
) -> dict:
    if filing is None:
        filing = find_filing(client, cik, accession=accession)
    document_name = name or filing.get("primary_document")
    if not document_name:
        raise NotFoundError(
            "This filing has no primary document.",
            "Run `edgar filing <ticker> <accession> --docs` to see available documents.",
        )
    url = filing_doc_url(cik, accession, document_name)
    response = client.get(url, ttl=TTL_DOCUMENT)
    lower = document_name.lower()
    content_type = (response.content_type or "").lower()
    if lower.endswith(".pdf") or response.content.startswith(b"%PDF") or "application/pdf" in content_type:
        raise ParseError(
            "PDF documents are not converted to text.",
            "Download the original with `edgar download` and read it locally.",
        )

    is_html = lower.endswith((".htm", ".html", ".xhtml")) or "html" in content_type or looks_like_html(
        response.content
    )
    if is_html:
        doc = parse_document(response.content)
        blocks = iter_blocks(doc)
        text = extract_text(blocks)
        sections = extract_sections(blocks, filing.get("form") or "")
    else:
        doc = None
        blocks = []
        text = _clean_plain_text(response.text)
        sections = []

    return {
        "filing": filing,
        "name": document_name,
        "url": url,
        "content_type": response.content_type,
        "bytes": len(response.content),
        "fetched_at": response.fetched_at,
        "cache": response.cache,
        "stale": response.stale,
        "is_html": is_html,
        "doc": doc,
        "blocks": blocks,
        "text": text,
        "chars": len(text),
        "sections": sections,
    }
