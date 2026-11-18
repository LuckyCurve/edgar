from __future__ import annotations

from edgar.base.compensation import map_tables_to_sections
from edgar.base.documents import read_document
from edgar.base.errors import NotFoundError, ParseError
from edgar.base.html import iter_tables
from edgar.base.submissions import find_filing, list_filings

PROXY_FORMS = ["DEF 14A", "DEFR14A", "PRE 14A", "DEFA14A", "DEFM14A"]
COMPENSATION_KEYS = [
    "compensation-discussion-and-analysis",
    "summary-compensation-table",
    "outstanding-equity-awards",
    "pay-versus-performance",
    "equity-compensation-plan-information",
    "director-compensation",
    "ceo-pay-ratio",
]


def find_proxy(client, cik: str | int, year: str | int | None = None, accession: str | None = None) -> dict:
    if accession:
        filing = find_filing(client, cik, accession=accession)
        return filing
    for form in PROXY_FORMS:
        result = list_filings(client, cik, forms=[form], limit=20 if year else 1)
        filings = result["filings"]
        if year:
            filings = [filing for filing in filings if filing["filing_date"][:4] == str(year)]
        if filings:
            return filings[0]
    shown = f"in {year}" if year else ""
    raise NotFoundError(
        f"No proxy statement found {shown} for this company.",
        "Try `edgar proxy <ticker>` without --year, or inspect `edgar filings <ticker> --form DEF 14A`.",
    )


def proxy_pack(
    client,
    cik: str | int,
    year: str | int | None = None,
    accession: str | None = None,
    include_text: bool = False,
    max_rows: int | None = None,
) -> dict:
    filing = find_proxy(client, cik, year=year, accession=accession)
    read = read_document(client, cik, filing["accession"], filing=filing)
    if not read["is_html"]:
        raise ParseError("This proxy statement is not HTML; section extraction is unavailable.")
    sections = read["sections"]
    tables = iter_tables(read["doc"])
    mapping = map_tables_to_sections(read["blocks"], tables, sections, max_rows=max_rows)
    section_summaries = []
    for section in sections:
        item = {
            "id": section["id"],
            "title": section["title"],
            "chars": section["chars"],
            "table_count": len(mapping.get(section["id"], [])),
        }
        if include_text:
            item["text"] = section["text"]
        section_summaries.append(item)
    present = {section["id"] for section in sections}
    return {
        "filing": filing,
        "document": {
            "name": read["name"],
            "url": read["url"],
            "chars": read["chars"],
            "bytes": read["bytes"],
        },
        "sections": section_summaries,
        "tables": mapping,
        "missing": [key for key in COMPENSATION_KEYS if key not in present],
    }
