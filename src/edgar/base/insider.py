from __future__ import annotations

from edgar.base.errors import ParseError
from edgar.base.form4 import parse_form4
from edgar.base.http import TTL_DOCUMENT
from edgar.base.refs import filing_doc_url
from edgar.base.submissions import filing_documents, find_filing, list_filings

INSIDER_FORMS = ["3", "3/A", "4", "4/A", "5", "5/A"]


def list_insider_filings(
    client,
    cik: str | int,
    since: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    return list_filings(client, cik, forms=INSIDER_FORMS, since=since, limit=limit, offset=offset)


def _xml_candidates(documents: list[dict], primary: str | None) -> list[str]:
    names = [document["name"] for document in documents if document["name"].lower().endswith(".xml")]
    primary_base = (primary or "").rsplit("/", 1)[-1]
    ordered = []
    if primary_base in names:
        ordered.append(primary_base)
    for name in names:
        if name not in ordered and "index" not in name.lower():
            ordered.append(name)
    return ordered


def parse_insider_filing(client, cik: str | int, filing: dict) -> dict:
    bundle = filing_documents(client, cik, filing["accession"])
    candidates = _xml_candidates(bundle["documents"], filing.get("primary_document"))
    if not candidates:
        raise ParseError(
            "No XML ownership document in this filing.",
            "Run `edgar filing <ticker> <accession> --docs` to inspect the documents.",
        )
    last_error: Exception | None = None
    for name in candidates[:4]:
        url = filing_doc_url(cik, filing["accession"], name)
        content = client.get(url, ttl=TTL_DOCUMENT).content
        try:
            ownership = parse_form4(content)
        except ParseError as exc:
            last_error = exc
            continue
        return {
            "document": {"name": name, "url": url},
            "ownership": ownership,
        }
    raise ParseError(
        "Could not parse the ownership XML.",
        str(last_error) if last_error else "The filing may use an unsupported schema.",
    )


def find_insider_filing(
    client,
    cik: str | int,
    accession: str | None = None,
    form: str | None = None,
) -> dict:
    if accession:
        return find_filing(client, cik, accession=accession)
    forms = [form] if form else INSIDER_FORMS
    result = list_filings(client, cik, forms=forms, limit=1)
    if not result["filings"]:
        raise ParseError("No insider filing found for this company.")
    return result["filings"][0]
