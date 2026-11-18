from __future__ import annotations

from urllib.parse import urlencode

from edgar.base.http import TTL_SEARCH
from edgar.base.refs import filing_archive_url, filing_doc_url, normalize_cik

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"


def search(
    client,
    query: str,
    forms: list[str] | None = None,
    cik: str | int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    params: dict[str, str] = {"q": query}
    if forms:
        params["forms"] = ",".join(forms)
    if cik:
        params["ciks"] = normalize_cik(cik)
    if since:
        params["startdt"] = since
    if until:
        params["enddt"] = until
    if offset:
        params["from"] = str(offset)
    url = f"{SEARCH_URL}?{urlencode(params)}"
    data = client.get_json(url, ttl=TTL_SEARCH)

    hits = []
    for hit in (data.get("hits") or {}).get("hits") or []:
        source = hit.get("_source") or {}
        identifier = str(hit.get("_id") or "")
        accession, _, filename = identifier.partition(":")
        ciks = source.get("ciks") or []
        hit_cik = ciks[0] if ciks else (normalize_cik(cik) if cik else None)
        document_url = (
            filing_doc_url(hit_cik, accession, filename)
            if hit_cik and accession and filename
            else None
        )
        hits.append(
            {
                "accession": accession,
                "filename": filename,
                "form": source.get("form"),
                "file_type": source.get("file_type"),
                "filed": source.get("file_date"),
                "period": source.get("period_ending"),
                "ciks": ciks,
                "company": (source.get("display_names") or [None])[0],
                "description": source.get("file_description"),
                "score": hit.get("_score"),
                "document_url": document_url,
                "filing_url": filing_archive_url(hit_cik, accession)
                if hit_cik and accession
                else None,
            }
        )

    total = (data.get("hits") or {}).get("total") or {}
    total_value = total.get("value")
    relation = total.get("relation")
    consumed = offset + len(hits)
    has_more = relation == "gte" or (isinstance(total_value, int) and consumed < total_value)
    return {
        "query": query,
        "total": {"value": total_value, "relation": relation},
        "hits": hits,
        "page": {
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": consumed if has_more else None,
        },
        "took_ms": data.get("took"),
        "source": url,
    }
