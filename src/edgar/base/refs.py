from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from edgar.base.errors import AmbiguousError, NotFoundError, UsageError
from edgar.base.http import TTL_SUBMISSIONS, TTL_TICKERS

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_CIK_RE = re.compile(r"^(?:CIK)?\s*0*(\d{1,10})$", re.IGNORECASE)
_ACCESSION_RE = re.compile(r"^(\d{10})-?(\d{2})-?(\d{6})$")


def normalize_cik(value: Any) -> str:
    if isinstance(value, bool):
        raise UsageError("CIK must be a number or ticker, not a boolean.")
    text = str(value).strip()
    match = _CIK_RE.match(text)
    if not match:
        raise UsageError(f"Not a CIK: {value!r}", "Use a ticker like AAPL or a numeric CIK.")
    number = int(match.group(1))
    if number <= 0:
        raise UsageError(f"Not a CIK: {value!r}")
    return f"{number:010d}"


def cik_int(cik: str | int) -> int:
    return int(normalize_cik(cik))


def normalize_accession(value: str) -> str:
    text = str(value).strip()
    match = _ACCESSION_RE.match(text)
    if not match:
        raise UsageError(
            f"Not an accession number: {value!r}",
            "Use the form 0000320193-26-000026 (or 000032019326000026).",
        )
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def accession_nodash(value: str) -> str:
    return normalize_accession(value).replace("-", "")


def filing_index_url(cik: str | int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int(cik)}/{accession_nodash(accession)}/index.json"


def filing_doc_url(cik: str | int, accession: str, name: str) -> str:
    clean = str(name).lstrip("/")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int(cik)}/"
        f"{accession_nodash(accession)}/{quote(clean, safe='/-_.~')}"
    )


def filing_archive_url(cik: str | int, accession: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int(cik)}/{accession_nodash(accession)}/"


def _ticker_index(client) -> list[dict]:
    raw = client.get_json(TICKERS_URL, ttl=TTL_TICKERS)
    rows = raw.values() if isinstance(raw, dict) else raw
    by_cik: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            cik = normalize_cik(row.get("cik_str"))
        except UsageError:
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        name = str(row.get("title") or "").strip()
        entry = by_cik.setdefault(
            cik,
            {"cik": cik, "cik_int": int(cik), "name": name, "tickers": []},
        )
        if ticker and ticker not in entry["tickers"]:
            entry["tickers"].append(ticker)
        if name and not entry["name"]:
            entry["name"] = name
    for entry in by_cik.values():
        entry["tickers"].sort()
    return list(by_cik.values())


def _submission_candidate(client, cik: str) -> dict:
    url = SUBMISSIONS_URL.format(cik=cik)
    data = client.get_json(url, ttl=TTL_SUBMISSIONS)
    return {
        "cik": cik,
        "cik_int": int(cik),
        "name": str(data.get("name") or ""),
        "tickers": [str(t) for t in (data.get("tickers") or [])],
    }


def _looks_like_cik(query: str) -> bool:
    return bool(_CIK_RE.match(query.strip()))


def lookup(client, query: str, limit: int = 20) -> list[dict]:
    """Resolve a ticker, CIK, or company-name fragment to ranked candidates."""
    text = str(query).strip()
    if not text:
        raise UsageError("Company query is empty.")
    if _looks_like_cik(text):
        return [_submission_candidate(client, normalize_cik(text))]

    rows = _ticker_index(client)
    upper = text.upper()
    exact = [row for row in rows if upper in row["tickers"]]
    if exact:
        return exact[:limit]

    needle = text.casefold()
    scored: list[tuple[int, str, dict]] = []
    for row in rows:
        name = row["name"].casefold()
        if needle not in name:
            continue
        if name == needle:
            score = 0
        elif name.startswith(needle):
            score = 1
        elif re.search(rf"\b{re.escape(needle)}", name):
            score = 2
        else:
            score = 3
        scored.append((score, row["name"], row))
    scored.sort(key=lambda item: (item[0], len(item[1]), item[1]))
    return [row for _, _, row in scored[:limit]]


def pick_company(client, query: str) -> dict:
    candidates = lookup(client, query)
    if not candidates:
        raise NotFoundError(
            f"No SEC company matches {query!r}.",
            "Try a ticker (AAPL) or numeric CIK; `edgar resolve <name>` lists matches.",
        )
    if len(candidates) > 1:
        labels = ", ".join(
            f"{row['name']} ({'/'.join(row['tickers']) or row['cik']})" for row in candidates[:5]
        )
        raise AmbiguousError(
            f"{query!r} matches {len(candidates)} companies: {labels}",
            "Use one of the tickers or CIKs above, or `edgar resolve <name>` for the full list.",
        )
    return candidates[0]
