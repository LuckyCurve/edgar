from __future__ import annotations

from typing import Any

from edgar.base.errors import NotFoundError
from edgar.base.http import TTL_INDEX, TTL_SUBMISSIONS
from edgar.base.refs import (
    filing_archive_url,
    filing_doc_url,
    filing_index_url,
    normalize_accession,
    normalize_cik,
)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/"
PROFILE_FIELDS = (
    "name",
    "entityType",
    "sic",
    "sicDescription",
    "tickers",
    "exchanges",
    "category",
    "fiscalYearEnd",
    "stateOfIncorporation",
    "phone",
    "website",
    "investorWebsite",
    "lei",
    "formerNames",
    "addresses",
)


def _snake(value: str) -> str:
    output = []
    for char in value:
        if char.isupper():
            output.append("_")
            output.append(char.lower())
        else:
            output.append(char)
    return "".join(output).lstrip("_")


def _recent(data: dict) -> dict:
    filings = data.get("filings") or {}
    if "recent" in filings:
        return filings["recent"] or {}
    return data if "accessionNumber" in data else {}


def _files(data: dict) -> list[dict]:
    return list((data.get("filings") or {}).get("files") or [])


def _row_list(container: dict) -> list[dict]:
    if not container:
        return []
    keys = [key for key, value in container.items() if isinstance(value, list)]
    if not keys:
        return []
    count = max(len(container[key]) for key in keys)
    rows = []
    for index in range(count):
        row = {}
        for key in keys:
            values = container[key]
            row[key] = values[index] if index < len(values) else None
        rows.append(row)
    return rows


def get_submissions(client, cik: str | int) -> tuple[dict, str]:
    normalized = normalize_cik(cik)
    url = f"{SUBMISSIONS_URL}CIK{normalized}.json"
    return client.get_json(url, ttl=TTL_SUBMISSIONS), url


def profile(client, cik: str | int) -> dict:
    data, url = get_submissions(client, cik)
    normalized = normalize_cik(cik)
    result: dict[str, Any] = {"cik": normalized, "cik_int": int(normalized)}
    for field in PROFILE_FIELDS:
        result[_snake(field)] = data.get(field)
    result["source"] = url
    return result


def _row_to_filing(row: dict, cik: str) -> dict:
    accession = normalize_accession(row.get("accessionNumber") or "")
    items = row.get("items") or ""
    return {
        "accession": accession,
        "form": row.get("form") or "",
        "filing_date": row.get("filingDate") or "",
        "report_date": row.get("reportDate") or "",
        "accepted_at": row.get("acceptanceDateTime") or "",
        "primary_document": row.get("primaryDocument") or "",
        "primary_doc_description": row.get("primaryDocDescription") or "",
        "items": [item.strip() for item in items.split(",") if item.strip()],
        "file_number": row.get("fileNumber") or "",
        "film_number": row.get("filmNumber") or "",
        "size": row.get("size"),
        "is_xbrl": bool(row.get("isXBRL")),
        "is_inline_xbrl": bool(row.get("isInlineXBRL")),
        "archive_url": filing_archive_url(cik, accession),
        "index_url": filing_index_url(cik, accession),
        "primary_doc_url": filing_doc_url(cik, accession, row.get("primaryDocument"))
        if row.get("primaryDocument")
        else "",
    }


def _matches(filing: dict, forms: set[str], since: str | None, until: str | None) -> bool:
    if forms and filing["form"].upper() not in forms:
        return False
    date = filing["filing_date"]
    if since and date < since:
        return False
    if until and date > until:
        return False
    return True


def _load_supplements(client, base: dict, existing: list[dict]) -> tuple[list[dict], int, int]:
    files = sorted(_files(base), key=lambda item: item.get("filingTo") or "", reverse=True)
    rows = list(existing)
    loaded = 0
    for item in files:
        name = item.get("name")
        if not name:
            continue
        data = client.get_json(SUBMISSIONS_URL + name, ttl=TTL_SUBMISSIONS)
        rows.extend(_row_list(_recent(data)))
        loaded += 1
    return rows, loaded, len(files)


def list_filings(
    client,
    cik: str | int,
    forms: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_supplements: bool = True,
) -> dict:
    base, url = get_submissions(client, cik)
    normalized = normalize_cik(cik)
    form_set = {form.upper() for form in (forms or [])}
    rows = _row_list(_recent(base))
    files_total = len(_files(base))
    files_loaded = 0
    complete = files_total == 0

    def matches(rows_in):
        return [
            filing
            for filing in (_row_to_filing(row, normalized) for row in rows_in)
            if _matches(filing, form_set, since, until)
        ]

    found = matches(rows)
    while include_supplements and files_loaded < files_total and (offset + limit) > len(found):
        files = sorted(_files(base), key=lambda item: item.get("filingTo") or "", reverse=True)
        item = files[files_loaded]
        name = item.get("name")
        if not name:
            files_loaded += 1
            continue
        data = client.get_json(SUBMISSIONS_URL + name, ttl=TTL_SUBMISSIONS)
        rows.extend(_row_list(_recent(data)))
        files_loaded += 1
        found = matches(rows)
        if files_loaded == files_total:
            complete = True

    found.sort(key=lambda filing: (filing["filing_date"], filing["accepted_at"]), reverse=True)
    page = found[offset : offset + limit]
    consumed = offset + len(page)
    has_more = consumed < len(found) or not complete
    return {
        "cik": normalized,
        "filings": page,
        "page": {
            "offset": offset,
            "limit": limit,
            "total": len(found),
            "has_more": has_more,
            "next_offset": consumed if has_more else None,
        },
        "complete": complete,
        "files_loaded": files_loaded,
        "files_total": files_total,
        "source": url,
    }


def find_filing(
    client,
    cik: str | int,
    accession: str | None = None,
    form: str | None = None,
) -> dict:
    if accession:
        normalized = normalize_accession(accession)
        base, _ = get_submissions(client, cik)
        rows = _row_list(_recent(base))
        for row in rows:
            if normalize_accession(row.get("accessionNumber") or "") == normalized:
                return _row_to_filing(row, normalize_cik(cik))
        for item in sorted(_files(base), key=lambda value: value.get("filingTo") or "", reverse=True):
            name = item.get("name")
            if not name:
                continue
            data = client.get_json(SUBMISSIONS_URL + name, ttl=TTL_SUBMISSIONS)
            for row in _row_list(_recent(data)):
                if normalize_accession(row.get("accessionNumber") or "") == normalized:
                    return _row_to_filing(row, normalize_cik(cik))
        raise NotFoundError(
            f"No filing {normalized} for CIK {normalize_cik(cik)}.",
            "List filings with `edgar filings <ticker> --form <form>`.",
        )
    if form:
        result = list_filings(client, cik, forms=[form], limit=1)
        if not result["filings"]:
            raise NotFoundError(
                f"No {form} filing found for CIK {normalize_cik(cik)}.",
                "Check the form name; `edgar filings <ticker> --limit 20` lists recent forms.",
            )
        return result["filings"][0]
    raise NotFoundError("Specify an accession number or a form.")


def filing_documents(client, cik: str | int, accession: str) -> dict:
    filing = find_filing(client, cik, accession=accession)
    index_url = filing_index_url(cik, accession)
    try:
        index = client.get_json(index_url, ttl=TTL_INDEX)
    except NotFoundError:
        documents = []
        if filing["primary_document"]:
            documents.append(
                {
                    "name": filing["primary_document"],
                    "size": None,
                    "last_modified": None,
                    "type": "",
                    "is_primary": True,
                    "url": filing["primary_doc_url"],
                }
            )
        return {"filing": filing, "documents": documents, "primary_document": filing["primary_document"]}
    primary = (filing["primary_document"] or "").rsplit("/", 1)[-1]
    documents = []
    for item in (index.get("directory") or {}).get("item") or []:
        name = item.get("name")
        if not name:
            continue
        documents.append(
            {
                "name": name,
                "size": item.get("size"),
                "last_modified": item.get("last-modified"),
                "type": item.get("type") or "",
                "is_primary": name == primary,
                "url": filing_doc_url(cik, accession, name),
            }
        )
    return {"filing": filing, "documents": documents, "primary_document": primary}
