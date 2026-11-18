from __future__ import annotations

import argparse
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from edgar import __version__
from edgar.base import submissions
from edgar.base.compensation import map_tables_to_sections
from edgar.base.documents import read_document
from edgar.base.env import (
    config_path,
    get_cache_dir,
    get_rate_limit,
    get_timeout,
    get_user_agent,
    load_config,
    save_config,
)
from edgar.base.errors import EdgarError, NotFoundError, ParseError, UsageError
from edgar.base.facts import detect_taxonomy, list_concepts, select_facts
from edgar.base.fulltext import search as fulltext_search
from edgar.base.html import extract_text, iter_tables, table_context, table_matrix
from edgar.base.http import (
    TTL_FACTS,
    TTL_INDEX,
    TTL_TICKERS,
    HttpClient,
)
from edgar.base.insider import (
    find_insider_filing,
    list_insider_filings,
    parse_insider_filing,
)
from edgar.base.proxy import find_proxy, proxy_pack
from edgar.base.refs import TICKERS_URL, lookup, normalize_cik, pick_company
from edgar.base.sections import extract_sections, find_section
from edgar.cli.output import dumps, make_envelope, make_error, paginate, truncate_text

COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class AgentParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message, self.format_usage().strip())


def _split(values: list[str] | None) -> list[str]:
    output = []
    for value in values or []:
        output.extend(part.strip() for part in value.split(",") if part.strip())
    return output


def _date_arg(value: str | None, flag: str) -> None:
    if not value:
        return
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise UsageError(f"{flag} must be YYYY-MM-DD, got {value!r}.") from exc


def _year_arg(value: str | None) -> None:
    if not value:
        return
    if not re.fullmatch(r"\d{4}", str(value)):
        raise UsageError(f"--year must be YYYY, got {value!r}.")


def _compact_filing(filing: dict) -> dict:
    keys = (
        "accession",
        "form",
        "filing_date",
        "report_date",
        "primary_document",
        "primary_doc_description",
        "is_xbrl",
        "is_inline_xbrl",
    )
    return {
        key: filing[key]
        for key in keys
        if key in filing and filing[key] not in (None, "", False)
    }


def _company_brief(candidate: dict) -> dict:
    return {
        "cik": candidate["cik"],
        "name": candidate.get("name") or "",
        "tickers": candidate.get("tickers") or [],
    }


def _shell_join(parts: list[str]) -> str:
    return " ".join(f'"{part}"' if " " in part else part for part in parts)


def _filing_command(command: str, query: str, accession: str, *extra: str) -> str:
    return _shell_join(["edgar", command, query, accession, *extra])


def _pick(client, query: str) -> dict:
    return pick_company(client, query)


def _load_filing(client, query: str, accession: str | None, form: str | None) -> tuple[dict, dict]:
    company = _pick(client, query)
    if accession:
        filing = submissions.find_filing(client, company["cik"], accession=accession)
    elif form:
        filing = submissions.find_filing(client, company["cik"], form=form)
    else:
        raise UsageError(
            "Specify a filing accession or --form.",
            "Example: edgar filing AAPL --form 10-K",
        )
    return company, filing


def _company_facts(client, cik: str) -> dict:
    return client.get_json(COMPANY_FACTS_URL.format(cik=normalize_cik(cik)), ttl=TTL_FACTS)


# -- commands -------------------------------------------------------------


def cmd_resolve(client, args) -> tuple[dict, list[str]]:
    matches = lookup(client, args.query, limit=args.limit)
    data = {
        "query": args.query,
        "matches": matches,
        "ambiguous": len(matches) > 1,
    }
    if not matches:
        data["hint"] = "Try a ticker symbol or numeric CIK."
    return data, []


def cmd_company(client, args) -> tuple[dict, list[str]]:
    candidate = _pick(client, args.query)
    profile = submissions.profile(client, candidate["cik"])
    forms = _split(args.latest_form) or ["10-K", "20-F", "10-Q", "DEF 14A"]
    latest = {}
    for form in forms:
        result = submissions.list_filings(client, candidate["cik"], forms=[form], limit=1)
        if result["filings"]:
            latest[form] = _compact_filing(result["filings"][0])
    data = {"company": profile, "latest": latest}
    if latest:
        first_form = next(iter(latest))
        filing = latest[first_form]
        data["next"] = {
            "command": _filing_command("sections", args.query, filing["accession"]),
            "why": f"list sections in the latest {first_form}",
        }
    return data, []


def cmd_filings(client, args) -> tuple[dict, list[str]]:
    _date_arg(args.since, "--since")
    _date_arg(args.until, "--until")
    company = _pick(client, args.query)
    forms = _split(args.form)
    result = submissions.list_filings(
        client,
        company["cik"],
        forms=forms,
        since=args.since,
        until=args.until,
        limit=args.limit,
        offset=args.offset,
    )
    data = {
        "company": _company_brief(company),
        "filings": [_compact_filing(filing) for filing in result["filings"]],
        "page": result["page"],
        "coverage": {
            "complete": result["complete"],
            "files_loaded": result["files_loaded"],
            "files_total": result["files_total"],
        },
    }
    if result["page"]["has_more"]:
        extra = ["--limit", str(args.limit), "--offset", str(result["page"]["next_offset"])]
        if forms:
            extra += ["--form", ",".join(forms)]
        if args.since:
            extra += ["--since", args.since]
        if args.until:
            extra += ["--until", args.until]
        data["next"] = {
            "command": _shell_join(["edgar", "filings", args.query, *extra]),
            "why": "next page of filings",
        }
    elif result["filings"]:
        data["next"] = {
            "command": _filing_command("filing", args.query, result["filings"][0]["accession"]),
            "why": "inspect the newest filing",
        }
    return data, []


def cmd_filing(client, args) -> tuple[dict, list[str]]:
    company, filing = _load_filing(client, args.query, args.accession, args.form)
    data = {"company": _company_brief(company), "filing": filing}
    if args.docs:
        bundle = submissions.filing_documents(client, company["cik"], filing["accession"])
        data["documents"] = bundle["documents"]
        data["primary_document"] = bundle["primary_document"]
    data["next"] = {
        "command": _filing_command("sections", args.query, filing["accession"]),
        "why": "list sections in this filing",
    }
    return data, []


def cmd_sections(client, args) -> tuple[dict, list[str]]:
    company, filing = _load_filing(client, args.query, args.accession, None)
    read = read_document(client, company["cik"], filing["accession"], name=args.doc, filing=filing)
    warnings = []
    if not read["is_html"]:
        warnings.append("This document is not HTML; no section map is available. Use `edgar text`.")
    summaries = [
        {
            "id": section["id"],
            "part": section["part"],
            "item": section["item"],
            "title": section["title"],
            "chars": section["chars"],
            "aliases": section["aliases"],
        }
        for section in read["sections"]
    ]
    data = {
        "company": _company_brief(company),
        "filing": _compact_filing(filing),
        "document": {
            "name": read["name"],
            "url": read["url"],
            "chars": read["chars"],
            "content_type": read["content_type"],
        },
        "sections": summaries,
    }
    if summaries:
        data["next"] = {
            "command": _filing_command(
                "text", args.query, filing["accession"], "--section", summaries[0]["id"]
            ),
            "why": f"read {summaries[0]['title'] or summaries[0]['id']}",
        }
    return data, warnings


def _section_text(read: dict, section: dict, include_tables: bool) -> str:
    if include_tables:
        return section["text"]
    blocks = read["blocks"][section["start_block"] + 1 : section["end_block"]]
    return extract_text(blocks, include_tables=False)


def cmd_text(client, args) -> tuple[dict, list[str]]:
    company, filing = _load_filing(client, args.query, args.accession, None)
    read = read_document(client, company["cik"], filing["accession"], name=args.doc, filing=filing)
    warnings = []
    section_meta = None
    if args.section:
        section = find_section(read["sections"], args.section)
        text = _section_text(read, section, include_tables=not args.no_tables)
        section_meta = {
            "id": section["id"],
            "part": section["part"],
            "item": section["item"],
            "title": section["title"],
            "chars": section["chars"],
        }
    else:
        text = (
            extract_text(read["blocks"], include_tables=not args.no_tables)
            if read["blocks"]
            else read["text"]
        )
        if read["is_html"] and not read["sections"]:
            warnings.append("No section map for this form; returning the whole document as text.")
    max_chars = len(text) if args.full else args.max_chars
    chunk, page = truncate_text(text, max_chars=max_chars, offset=args.offset)
    data = {
        "company": _company_brief(company),
        "filing": _compact_filing(filing),
        "document": {"name": read["name"], "url": read["url"]},
        "section": section_meta,
        "text": chunk,
        "page": page,
    }
    if page["has_more"]:
        extra = ["--offset", str(page["next_offset"]), "--max-chars", str(max_chars)]
        if args.section:
            extra += ["--section", args.section]
        if args.no_tables:
            extra.append("--no-tables")
        data["next"] = {
            "command": _filing_command("text", args.query, filing["accession"], *extra),
            "why": "continue reading",
        }
    elif section_meta:
        data["next"] = {
            "command": _filing_command(
                "tables", args.query, filing["accession"], "--section", section_meta["id"]
            ),
            "why": "see tables in this section",
        }
    return data, warnings


def _table_block_index(blocks, table) -> int | None:
    for index, block in enumerate(blocks):
        if block.is_table and block.table is table:
            return index
    return None


def cmd_tables(client, args) -> tuple[dict, list[str]]:
    company, filing = _load_filing(client, args.query, args.accession, None)
    read = read_document(client, company["cik"], filing["accession"], name=args.doc, filing=filing)
    if not read["blocks"]:
        raise ParseError("This document is not HTML; table extraction is unavailable.")
    tables = iter_tables(read["doc"])
    sections = read["sections"]
    mapping = map_tables_to_sections(
        read["blocks"], tables, sections, max_rows=None, min_rows=1, min_cols=1
    )
    section_by_table: dict[int, str] = {}
    for section_id, entries in mapping.items():
        for entry in entries:
            section_by_table[entry["table_index"]] = section_id

    warnings = []
    selected_section = None
    if args.section:
        selected_section = find_section(sections, args.section)
    section_range = None
    if selected_section:
        section_range = (selected_section["start_block"], selected_section["end_block"])

    matched = []
    try:
        match_re = re.compile(args.match, re.IGNORECASE) if args.match else None
    except re.error as exc:
        raise UsageError(f"Invalid --match regex: {exc}") from exc
    for index, (table, _order) in enumerate(tables):
        block_index = _table_block_index(read["blocks"], table)
        if section_range and (block_index is None or not (section_range[0] < block_index < section_range[1])):
            continue
        matrix = table_matrix(table)
        if not matrix:
            continue
        context = table_context(read["blocks"], table) or ""
        if match_re:
            haystack = context + "\n" + "\n".join(" ".join(row) for row in matrix[:3])
            if not match_re.search(haystack):
                continue
        matched.append(
            {
                "table_index": index,
                "section": section_by_table.get(index),
                "context": context[:160],
                "n_rows": len(matrix),
                "n_cols": max(len(row) for row in matrix),
                "header": matrix[0],
                "matrix": matrix,
                "block_index": block_index,
            }
        )

    if args.table is not None:
        target = next((entry for entry in matched if entry["table_index"] == args.table), None)
        if target is None:
            raise NotFoundError(
                f"No table at index {args.table}.",
                "Run `edgar tables <ticker> <accession>` to list table indexes.",
            )
        table_payload = {
            "table_index": target["table_index"],
            "section": target["section"],
            "context": target["context"],
            "n_rows": target["n_rows"],
            "n_cols": target["n_cols"],
            "header": target["header"],
            "rows": target["matrix"],
        }
        return {
            "company": _company_brief(company),
            "filing": _compact_filing(filing),
            "document": {"name": read["name"], "url": read["url"]},
            "table": table_payload,
        }, warnings

    if not matched:
        warnings.append("No tables matched. Try relaxing --section or --match.")
    total = len(matched)
    page_entries, page = paginate(matched, args.limit, args.offset)
    output = []
    for entry in page_entries:
        preview_rows = entry["matrix"] if args.full else entry["matrix"][: args.rows]
        output.append(
            {
                "table_index": entry["table_index"],
                "section": entry["section"],
                "context": entry["context"],
                "n_rows": entry["n_rows"],
                "n_cols": entry["n_cols"],
                "header": entry["header"],
                "preview": preview_rows,
                "truncated": None if args.full else entry["n_rows"] > args.rows,
            }
        )
    data = {
        "company": _company_brief(company),
        "filing": _compact_filing(filing),
        "document": {"name": read["name"], "url": read["url"]},
        "tables": output,
        "page": page,
    }
    if page["has_more"]:
        extra = ["--limit", str(args.limit), "--offset", str(page["next_offset"])]
        if args.section:
            extra += ["--section", args.section]
        if args.match:
            extra += ["--match", args.match]
        data["next"] = {
            "command": _filing_command("tables", args.query, filing["accession"], *extra),
            "why": "next page of tables",
        }
    elif output:
        data["next"] = {
            "command": _filing_command(
                "tables", args.query, filing["accession"], "--table", str(output[0]["table_index"])
            ),
            "why": "read one table in full",
        }
    return data, warnings


def _table_metadata(entries: list[dict], preview_rows: int) -> list[dict]:
    result = []
    for entry in entries:
        result.append(
            {
                "table_index": entry["table_index"],
                "n_rows": entry["n_rows"],
                "n_cols": entry["n_cols"],
                "header": entry["header"],
                "preview": entry["rows"][:preview_rows],
                "truncated": entry["n_rows"] > preview_rows,
            }
        )
    return result


def cmd_proxy(client, args) -> tuple[dict, list[str]]:
    _year_arg(args.year)
    company = _pick(client, args.query)
    pack = proxy_pack(
        client,
        company["cik"],
        year=args.year,
        accession=args.accession,
        include_text=True,
        max_rows=None,
    )
    warnings = []
    if pack["missing"]:
        warnings.append("Sections not found: " + ", ".join(pack["missing"]))
    summaries = []
    for section in pack["sections"]:
        item = {
            "id": section["id"],
            "title": section["title"],
            "chars": section["chars"],
            "table_count": section["table_count"],
        }
        if args.text:
            chunk, page = truncate_text(section.get("text", ""), args.max_chars)
            item["text"] = chunk
            item["page"] = page
        summaries.append(item)
    data = {
        "company": _company_brief(company),
        "filing": _compact_filing(pack["filing"]),
        "document": pack["document"],
        "sections": summaries,
        "missing": pack["missing"],
    }
    if args.table:
        key = args.table
        if key not in pack["tables"]:
            raise NotFoundError(
                f"No compensation table section {key!r}.",
                "Available: " + (", ".join(sorted(pack["tables"])) or "(none)"),
            )
        data["tables"] = {
            key: [
                {
                    "table_index": entry["table_index"],
                    "n_rows": entry["n_rows"],
                    "n_cols": entry["n_cols"],
                    "header": entry["header"],
                    "rows": entry["rows"],
                    "truncated": False,
                }
                for entry in pack["tables"][key]
            ]
        }
        return data, warnings
    if args.section:
        key = args.section
        section = next((item for item in pack["sections"] if item["id"] == key), None)
        if section is None:
            raise NotFoundError(
                f"No proxy section {key!r}.",
                "Available: " + (", ".join(item["id"] for item in pack["sections"]) or "(none)"),
            )
        section = dict(section)
        text = section.pop("text", "")
        if args.text or args.full:
            max_chars = len(text) if args.full else args.max_chars
            chunk, page = truncate_text(text, max_chars)
            section["text"] = chunk
            section["page"] = page
        data["section"] = section
        if key in pack["tables"]:
            if args.full:
                data["tables"] = {
                    key: [
                        {
                            "table_index": entry["table_index"],
                            "n_rows": entry["n_rows"],
                            "n_cols": entry["n_cols"],
                            "header": entry["header"],
                            "rows": entry["rows"],
                            "truncated": False,
                        }
                        for entry in pack["tables"][key]
                    ]
                }
            else:
                data["tables"] = {key: _table_metadata(pack["tables"][key], preview_rows=args.rows)}
        return data, warnings

    data["tables"] = {
        key: _table_metadata(entries, preview_rows=args.rows) for key, entries in pack["tables"].items()
    }
    if args.full:
        data["tables"] = {
            key: [
                {
                    "table_index": entry["table_index"],
                    "n_rows": entry["n_rows"],
                    "n_cols": entry["n_cols"],
                    "header": entry["header"],
                    "rows": entry["rows"],
                    "truncated": False,
                }
                for entry in entries
            ]
            for key, entries in pack["tables"].items()
        }
    if "summary-compensation-table" in data["tables"]:
        data["next"] = {
            "command": _shell_join(
                ["edgar", "proxy", args.query, "--table", "summary-compensation-table"]
            ),
            "why": "read the full summary compensation table",
        }
    return data, warnings


def _compact_fact(fact: dict) -> dict:
    keys = ("start", "end", "val", "accn", "fy", "fp", "form", "filed", "frame")
    return {key: fact[key] for key in keys if key in fact and fact[key] not in (None, "")}


def cmd_facts(client, args) -> tuple[dict, list[str]]:
    _date_arg(args.since, "--since")
    _date_arg(args.until, "--until")
    company = _pick(client, args.query)
    facts = _company_facts(client, company["cik"])
    concepts = _split(args.concept)
    if not concepts:
        raise UsageError(
            "Specify --concept.",
            "Find tags with `edgar concepts <ticker> --query revenue`.",
        )
    taxonomy = args.taxonomy or detect_taxonomy(facts)
    selected = select_facts(
        facts,
        concepts,
        taxonomy=taxonomy,
        since=args.since,
        until=args.until,
        period=args.period,
        unit=args.unit,
        forms=_split(args.form),
        dedupe=not args.all,
        limit=args.limit,
        offset=args.offset,
    )
    groups = []
    for group in selected["groups"]:
        groups.append(
            {
                "tag": group["tag"],
                "label": group["label"],
                "unit": group["unit"],
                "total": group["total"],
                "last_end": group.get("last_end"),
                "truncated": group["truncated"],
                "next_offset": group["next_offset"],
                "facts": [_compact_fact(fact) for fact in group["facts"]],
            }
        )
    data = {
        "company": {"cik": company["cik"], "name": facts.get("entityName") or company["name"]},
        "selection": {
            "taxonomy": taxonomy,
            "period": args.period,
            "dedupe": "latest-filed" if not args.all else "all",
            "since": args.since,
            "until": args.until,
        },
        "groups": groups,
        "missing": selected["missing"],
        "count": selected["count"],
    }
    if any(group["truncated"] for group in groups):
        extra = [
            "--concept",
            ",".join(concepts),
            "--period",
            args.period,
            "--limit",
            str(args.limit),
            "--offset",
            str(args.offset + args.limit),
        ]
        if taxonomy != "us-gaap":
            extra += ["--taxonomy", taxonomy]
        if args.since:
            extra += ["--since", args.since]
        if args.until:
            extra += ["--until", args.until]
        if args.form:
            extra += ["--form", ",".join(_split(args.form))]
        if args.unit:
            extra += ["--unit", args.unit]
        if args.all:
            extra.append("--all")
        data["next"] = {
            "command": _shell_join(["edgar", "facts", args.query, *extra]),
            "why": "next page of facts",
        }
    warnings = []
    if selected["missing"]:
        warnings.append("No facts for: " + ", ".join(selected["missing"]))
    cutoff = f"{datetime.now().year - 2}-01-01"
    for group in groups:
        last_end = group.get("last_end")
        if last_end and last_end < cutoff:
            warnings.append(
                f"{group['tag']} has no facts after {last_end}; "
                f'run `edgar concepts {args.query} --query {group["tag"]}` to find other tags.'
            )
    return data, warnings


def cmd_concepts(client, args) -> tuple[dict, list[str]]:
    company = _pick(client, args.query)
    facts = _company_facts(client, company["cik"])
    taxonomy = args.taxonomy or detect_taxonomy(facts)
    rows = list_concepts(
        facts,
        query=args.query_text,
        taxonomy=taxonomy,
        limit=100000,
        include_description=args.detail,
    )
    page_rows, page = paginate(rows, args.limit, args.offset)
    data = {
        "company": {"cik": company["cik"], "name": facts.get("entityName") or company["name"]},
        "taxonomy": taxonomy,
        "concepts": page_rows,
        "page": page,
        "usage": f"edgar facts {args.query} --concept <tag> --period annual",
    }
    if page["has_more"]:
        extra = ["--limit", str(args.limit), "--offset", str(page["next_offset"])]
        if args.query_text:
            extra += ["--query", args.query_text]
        data["next"] = {
            "command": _shell_join(["edgar", "concepts", args.query, *extra]),
            "why": "next page of concepts",
        }
    return data, []


def cmd_search(client, args) -> tuple[dict, list[str]]:
    _date_arg(args.since, "--since")
    _date_arg(args.until, "--until")
    cik = None
    company = None
    if args.ticker:
        candidate = _pick(client, args.ticker)
        cik = candidate["cik"]
        company = _company_brief(candidate)
    result = fulltext_search(
        client,
        args.query_text,
        forms=_split(args.form),
        cik=cik,
        since=args.since,
        until=args.until,
        limit=args.limit,
        offset=args.offset,
    )
    hits = []
    for hit in result["hits"]:
        item = {
            "accession": hit["accession"],
            "form": hit["form"],
            "filed": hit["filed"],
            "company": hit["company"],
            "description": hit["description"],
            "document_url": hit["document_url"],
            "filename": hit["filename"],
        }
        if args.detail:
            item.update(
                {
                    "ciks": hit["ciks"],
                    "period": hit["period"],
                    "file_type": hit["file_type"],
                    "score": hit["score"],
                    "filing_url": hit["filing_url"],
                }
            )
        hits.append(item)
    data = {
        "query": args.query_text,
        "company": company,
        "total": result["total"],
        "hits": hits,
        "page": result["page"],
    }
    if result["page"]["has_more"]:
        extra = ["--limit", str(args.limit), "--offset", str(result["page"]["next_offset"])]
        if args.ticker:
            extra += ["--ticker", args.ticker]
        if args.form:
            extra += ["--form", ",".join(_split(args.form))]
        if args.since:
            extra += ["--since", args.since]
        if args.until:
            extra += ["--until", args.until]
        data["next"] = {
            "command": _shell_join(["edgar", "search", args.query_text, *extra]),
            "why": "next page of search hits",
        }
    return data, []


def _compact_transaction(transaction: dict) -> dict:
    keys = ("type", "security", "date", "code", "shares", "price", "acquired_disposed", "shares_after")
    return {key: transaction[key] for key in keys if transaction.get(key) not in (None, "")}


def cmd_insiders(client, args) -> tuple[dict, list[str]]:
    _date_arg(args.since, "--since")
    company = _pick(client, args.query)
    result = list_insider_filings(
        client, company["cik"], since=args.since, limit=args.limit, offset=args.offset
    )
    filings = []
    warnings = []
    parse_count = min(len(result["filings"]), 20) if args.parse else 0
    if args.parse and len(result["filings"]) > 20:
        warnings.append("Parsed the first 20 filings; narrow --limit for more.")
    for filing in result["filings"][:parse_count] if args.parse else []:
        entry = _compact_filing(filing)
        try:
            parsed = parse_insider_filing(client, company["cik"], filing)
            ownership = parsed["ownership"]
            summary = {
                "period": ownership["period"],
                "owners": ownership["owners"],
                "transaction_count": len(ownership["transactions"]),
                "transactions": [
                    _compact_transaction(transaction) for transaction in ownership["transactions"][: args.rows]
                ],
                "document": parsed["document"],
            }
            if args.full:
                summary["transactions"] = ownership["transactions"]
                summary["footnotes"] = ownership["footnotes"]
            entry["insider"] = summary
        except EdgarError as exc:
            entry["insider_error"] = exc.to_dict()
        filings.append(entry)
    if not args.parse:
        filings = [_compact_filing(filing) for filing in result["filings"]]
    data = {
        "company": _company_brief(company),
        "filings": filings,
        "page": result["page"],
        "coverage": {"complete": result["complete"]},
    }
    if result["page"]["has_more"]:
        extra = ["--limit", str(args.limit), "--offset", str(result["page"]["next_offset"])]
        if args.since:
            extra += ["--since", args.since]
        if args.parse:
            extra.append("--parse")
        data["next"] = {
            "command": _shell_join(["edgar", "insiders", args.query, *extra]),
            "why": "next page of insider filings",
        }
    return data, warnings


def _safe_filename(name: str) -> str:
    candidate = Path(name).name
    if candidate in {"", ".", ".."} or "/" in candidate or "\\" in candidate:
        raise UsageError(f"Unsafe document name: {name!r}")
    return candidate


def cmd_download(client, args) -> tuple[dict, list[str]]:
    if args.url:
        response = client.get(args.url, ttl=TTL_INDEX)
        name = _safe_filename(urlparse(args.url).path)
        out_dir = Path(args.out or ".").expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / name
        target.write_bytes(response.content)
        return {
            "directory": str(out_dir.resolve()),
            "files": [
                {"name": name, "path": str(target.resolve()), "bytes": len(response.content), "url": args.url}
            ],
        }, []
    if not args.query or not args.accession:
        raise UsageError("Specify TICKER ACCESSION, or use --url.")
    company = _pick(client, args.query)
    bundle = submissions.filing_documents(client, company["cik"], args.accession)
    documents = bundle["documents"]
    selected = []
    if args.doc:
        wanted = set(args.doc)
        selected = [document for document in documents if document["name"] in wanted]
        if len(selected) != len(wanted):
            found = {document["name"] for document in selected}
            raise NotFoundError(
                "Some documents were not found: " + ", ".join(sorted(wanted - found)),
                "Run `edgar filing <ticker> <accession> --docs` to list names.",
            )
    elif args.all:
        selected = documents
    else:
        selected = [document for document in documents if document["is_primary"]]
        if not selected and bundle["primary_document"]:
            selected = [
                {
                    "name": bundle["primary_document"],
                    "url": f"{bundle['filing']['archive_url']}{bundle['primary_document']}",
                }
            ]
    if not selected:
        raise NotFoundError("No documents selected.")
    out_dir = Path(args.out or f"edgar-filings/{args.query.upper()}/{args.accession}").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    warnings = []
    if len(selected) > 50:
        warnings.append(f"Downloading {len(selected)} documents; this may take a while.")
    for document in selected:
        name = _safe_filename(document["name"])
        response = client.get(document["url"], ttl=TTL_INDEX)
        target = out_dir / name
        target.write_bytes(response.content)
        files.append(
            {"name": name, "path": str(target.resolve()), "bytes": len(response.content), "url": document["url"]}
        )
    return {
        "company": _company_brief(company),
        "filing": _compact_filing(bundle["filing"]),
        "directory": str(out_dir.resolve()),
        "files": files,
    }, warnings


def cmd_config(client, args) -> tuple[dict, list[str]]:
    path = config_path()
    values = load_config()
    if args.action == "path":
        return {"path": str(path)}, []
    if args.action == "show":
        effective = {
            "user_agent": get_user_agent(),
            "rate_limit": get_rate_limit(),
            "timeout": get_timeout(),
            "cache_dir": str(get_cache_dir()),
        }
        return {
            "path": str(path),
            "config": values,
            "effective": effective,
        }, []
    key = (args.key or "").replace("-", "_")
    allowed = {"user_agent", "rate_limit", "timeout", "cache_dir"}
    if key not in allowed:
        raise UsageError(
            f"Unknown config key: {args.key!r}",
            "Allowed: " + ", ".join(sorted(allowed)),
        )
    if args.action == "unset":
        values.pop(key, None)
        save_config(values)
        return {"path": str(path), "config": values}, []
    if args.value is None:
        raise UsageError(f"config set {args.key} needs a value.")
    value: str | float = args.value
    if key in {"rate_limit", "timeout"}:
        try:
            value = float(args.value)
        except ValueError as exc:
            raise UsageError(f"{key} must be a number.") from exc
    values[key] = value
    save_config(values)
    warnings = []
    if key == "user_agent" and "@" not in str(value):
        warnings.append("SEC archive requests are blocked without a contact email in user_agent.")
    return {"path": str(path), "config": values}, warnings


def cmd_cache(client, args) -> tuple[dict, list[str]]:
    root = get_cache_dir()
    if args.action == "dir":
        return {"cache_dir": str(root)}, []
    if not root.exists():
        return {"cache_dir": str(root), "files": 0, "bytes": 0}, []
    files = [path for path in root.rglob("*") if path.is_file()]
    size = sum(path.stat().st_size for path in files)
    if args.action == "info":
        return {"cache_dir": str(root), "files": len(files), "bytes": size}, []
    shutil.rmtree(root)
    return {"cache_dir": str(root), "removed_files": len(files), "removed_bytes": size}, []


def cmd_doctor(client, args) -> tuple[dict, list[str]]:
    checks = []

    def add(name: str, ok: bool, detail: str, hint: str | None = None):
        check = {"name": name, "ok": ok, "detail": detail}
        if hint:
            check["hint"] = hint
        checks.append(check)

    agent_ok = "@" in client.user_agent
    add(
        "user_agent",
        agent_ok,
        client.user_agent,
        None if agent_ok else 'Run: edgar config set user_agent "Your Name you@example.com"',
    )
    try:
        client.cache_dir.mkdir(parents=True, exist_ok=True)
        probe = client.cache_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("cache_writable", True, str(client.cache_dir))
    except OSError as exc:
        add("cache_writable", False, str(exc), "Set EDGAR_CACHE_DIR to a writable directory.")
    try:
        data = client.get_json(TICKERS_URL, ttl=TTL_TICKERS)
        add("data_api", True, f"{len(data)} ticker rows")
    except EdgarError as exc:
        add("data_api", False, exc.message, exc.hint)
    try:
        client.get_json(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/index.json",
            ttl=TTL_INDEX,
        )
        add("archive_access", True, "www.sec.gov/Archives reachable")
    except EdgarError as exc:
        add("archive_access", False, exc.message, exc.hint)
    overall = all(check["ok"] for check in checks)
    return {"ok": overall, "checks": checks}, []


COMMANDS = {
    "resolve": cmd_resolve,
    "company": cmd_company,
    "filings": cmd_filings,
    "filing": cmd_filing,
    "sections": cmd_sections,
    "text": cmd_text,
    "tables": cmd_tables,
    "proxy": cmd_proxy,
    "facts": cmd_facts,
    "concepts": cmd_concepts,
    "search": cmd_search,
    "insiders": cmd_insiders,
    "download": cmd_download,
    "config": cmd_config,
    "cache": cmd_cache,
    "doctor": cmd_doctor,
}


# -- parser ---------------------------------------------------------------


def build_parser() -> AgentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--pretty", action="store_true", help="indent JSON output")
    common.add_argument("--refresh", action="store_true", help="ignore cached HTTP responses")
    common.add_argument("--no-cache", action="store_true", help="do not read or write the HTTP cache")
    common.add_argument("--user-agent", help="SEC User-Agent, including a contact email")
    common.add_argument("--rate-limit", type=float, help="requests per second (max 10)")
    common.add_argument("--timeout", type=float, help="HTTP timeout in seconds")
    common.add_argument("--cache-dir", help="cache directory")
    common.add_argument("--debug", action="store_true", help="include tracebacks in errors")

    parser = AgentParser(
        prog="edgar",
        description="SEC EDGAR data for agents. Every value comes from SEC; nothing is computed.",
        epilog="Start with: edgar company AAPL",
    )
    parser.add_argument("--version", action="version", version=f"edgar {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, description: str = "") -> AgentParser:
        return sub.add_parser(name, parents=[common], help=help_text, description=description or help_text)

    p = add("resolve", "find a company by ticker, CIK, or name", "Rank companies matching a ticker, CIK, or name fragment.")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)

    p = add("company", "company profile and latest key filings")
    p.add_argument("query")
    p.add_argument("--latest-form", action="append", help="repeatable; default 10-K, 20-F, 10-Q, DEF 14A")

    p = add("filings", "list filings, newest first")
    p.add_argument("query")
    p.add_argument("-f", "--form", action="append", help="form type; repeatable or comma-separated")
    p.add_argument("--since", help="filing date >= YYYY-MM-DD")
    p.add_argument("--until", help="filing date <= YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)

    p = add("filing", "one filing's metadata and document list", "Omit ACCESSION to select the latest --form.")
    p.add_argument("query")
    p.add_argument("accession", nargs="?")
    p.add_argument("-f", "--form")
    p.add_argument("--docs", action="store_true", help="include every document in the filing")

    p = add("sections", "list section ids without their text")
    p.add_argument("query")
    p.add_argument("accession")
    p.add_argument("--doc", help="document filename inside the filing")

    p = add("text", "read a section or the whole document, paged")
    p.add_argument("query")
    p.add_argument("accession")
    p.add_argument("--section", help="section id or alias (mda, risk, business, ...)")
    p.add_argument("--doc", help="document filename inside the filing")
    p.add_argument("--max-chars", type=int, default=4000)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--full", action="store_true", help="return all text")
    p.add_argument("--no-tables", action="store_true", help="omit table rows from text")

    p = add("tables", "find tables, then read one in full")
    p.add_argument("query")
    p.add_argument("accession")
    p.add_argument("--doc")
    p.add_argument("--section", help="only tables in this section")
    p.add_argument("--match", help="case-insensitive regex on context and first rows")
    p.add_argument("--table", type=int, help="return this table index in full")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--rows", type=int, default=2, help="preview rows per table")
    p.add_argument("--full", action="store_true", help="return every matching table's rows")

    p = add("proxy", "executive compensation from the latest proxy", "Sections and tables from DEF 14A.")
    p.add_argument("query")
    p.add_argument("--year", help="filing year, e.g. 2025")
    p.add_argument("--accession", help="use a specific proxy filing")
    p.add_argument("--section", help="one proxy section id")
    p.add_argument("--table", help="one section's tables in full")
    p.add_argument("--rows", type=int, default=2, help="preview rows per table")
    p.add_argument("--text", action="store_true", help="include section text")
    p.add_argument("--max-chars", type=int, default=2000)
    p.add_argument("--full", action="store_true", help="return full rows")

    p = add("facts", "XBRL facts across years", "Annual facts by default; no ratios or derived values.")
    p.add_argument("query")
    p.add_argument("--concept", action="append", required=True, help="tag; repeatable or comma-separated")
    p.add_argument("--taxonomy", help="us-gaap or ifrs-full; detected when omitted")
    p.add_argument("--period", choices=["annual", "quarterly", "ytd", "instant", "all"], default="annual")
    p.add_argument("--since", help="period end >= YYYY-MM-DD")
    p.add_argument("--until", help="period end <= YYYY-MM-DD")
    p.add_argument("--form", action="append", help="form type; repeatable or comma-separated")
    p.add_argument("--unit", help="USD, shares, USD-per-shares, ...")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--all", action="store_true", help="keep every filed duplicate instead of latest-filed")

    p = add("concepts", "search XBRL concept tags and labels")
    p.add_argument("query")
    p.add_argument("--query", dest="query_text", help="match tag, label, or description")
    p.add_argument("--taxonomy", help="us-gaap or ifrs-full; detected when omitted")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--detail", action="store_true", help="include descriptions")

    p = add("search", "full-text search across EDGAR (2001+)")
    p.add_argument("query_text", metavar="query")
    p.add_argument("-f", "--form", action="append", help="form type; repeatable or comma-separated")
    p.add_argument("--ticker", help="limit to one company")
    p.add_argument("--since", help="filing date >= YYYY-MM-DD")
    p.add_argument("--until", help="filing date <= YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--detail", action="store_true", help="include CIKs, period, score, URLs")

    p = add("insiders", "Form 3/4/5 insider filings", "Add --parse to read transactions.")
    p.add_argument("query")
    p.add_argument("--since", help="filing date >= YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--parse", action="store_true", help="parse up to 20 filings")
    p.add_argument("--rows", type=int, default=3, help="transactions shown per filing")
    p.add_argument("--full", action="store_true", help="all transactions and footnotes")

    p = add("download", "save original SEC documents locally")
    p.add_argument("query", nargs="?")
    p.add_argument("accession", nargs="?")
    p.add_argument("--url", help="download a single URL instead of a filing")
    p.add_argument("-o", "--out", help="output directory")
    p.add_argument("--doc", action="append", help="document filename; repeatable")
    p.add_argument("--all", action="store_true", help="download every document in the filing")

    p = add("config", "show or change local settings")
    p.add_argument("action", choices=["show", "set", "unset", "path"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")

    p = add("cache", "inspect or clear the HTTP cache")
    p.add_argument("action", choices=["info", "dir", "clear"])

    add("doctor", "check User-Agent, cache, and SEC connectivity")

    return parser


def _build_client(args) -> HttpClient:
    return HttpClient(
        user_agent=args.user_agent,
        rate_limit=args.rate_limit,
        cache_dir=args.cache_dir,
        timeout=args.timeout,
        use_cache=not args.no_cache,
    )


def _configure_stdout() -> None:
    """Keep JSON valid UTF-8 even on Windows consoles with a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        print(dumps(make_error(None, exc)))
        return exc.exit_code

    client = _build_client(args)
    client.refresh = bool(args.refresh)
    handler = COMMANDS.get(args.command)
    if handler is None:
        error = UsageError(f"Unknown command: {args.command}")
        print(dumps(make_error(args.command, error), args.pretty))
        return error.exit_code
    try:
        data, warnings = handler(client, args)
        envelope = make_envelope(args.command, data, client, warnings)
        print(dumps(envelope, args.pretty))
        return 0
    except EdgarError as exc:
        print(dumps(make_error(args.command, exc), args.pretty))
        return exc.exit_code
    except BrokenPipeError:
        return 0
    except Exception as exc:  # pragma: no cover - safety net for agents
        if args.debug:
            traceback.print_exc()
        error = EdgarError(
            f"Unexpected failure: {exc}",
            "Re-run with --debug for a traceback.",
        )
        print(dumps(make_error(args.command, error), args.pretty))
        return 1


if __name__ == "__main__":
    sys.exit(main())
