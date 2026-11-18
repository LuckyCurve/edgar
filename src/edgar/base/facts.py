from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from edgar.base.errors import NotFoundError

Periods = {"annual", "quarterly", "ytd", "instant", "all"}


def _taxonomy(facts: dict, taxonomy: str) -> dict:
    return (facts.get("facts") or {}).get(taxonomy) or {}


def list_concepts(
    facts: dict,
    query: str | None = None,
    taxonomy: str = "us-gaap",
    limit: int = 20,
    include_description: bool = False,
) -> list[dict]:
    rows = []
    for tag, payload in _taxonomy(facts, taxonomy).items():
        rows.append(
            {
                "tag": tag,
                "label": payload.get("label") or tag,
                "units": sorted((payload.get("units") or {}).keys()),
                "description": payload.get("description") or "",
            }
        )
    if query:
        needle = query.casefold()
        scored = []
        for row in rows:
            tag = row["tag"].casefold()
            label = row["label"].casefold()
            if tag == needle:
                score = 0
            elif label == needle:
                score = 1
            elif tag.startswith(needle):
                score = 2
            elif label.startswith(needle):
                score = 3
            elif needle in tag:
                score = 4
            elif needle in label:
                score = 5
            elif needle in row["description"].casefold():
                score = 6
            else:
                continue
            scored.append((score, row["tag"], row))
        scored.sort(key=lambda item: (item[0], item[1]))
        rows = [row for _, _, row in scored]
    else:
        rows.sort(key=lambda row: row["tag"])
    result = []
    for row in rows[:limit]:
        if include_description:
            result.append(row)
        else:
            result.append({key: value for key, value in row.items() if key != "description"})
    return result


def _days(entry: dict) -> int | None:
    start = entry.get("start")
    end = entry.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _matches_period(entry: dict, period: str) -> bool:
    if period == "all":
        return True
    days = _days(entry)
    if period == "instant":
        return days is None
    if days is None:
        return False
    if period == "annual":
        return 330 <= days <= 400
    if period == "quarterly":
        return 60 <= days <= 120
    if period == "ytd":
        return 150 <= days <= 330
    return True


def _flatten(payload: dict, taxonomy: str, tag: str) -> Iterable[dict]:
    for unit, entries in (payload.get("units") or {}).items():
        for entry in entries:
            row = dict(entry)
            row["taxonomy"] = taxonomy
            row["tag"] = tag
            row["unit"] = unit
            row["label"] = payload.get("label") or tag
            yield row


def select_facts(
    facts: dict,
    concepts: list[str],
    taxonomy: str = "us-gaap",
    since: str | None = None,
    until: str | None = None,
    period: str = "all",
    unit: str | None = None,
    forms: list[str] | None = None,
    dedupe: bool = True,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    if period not in Periods:
        raise ValueError(f"Unknown period: {period}")
    available = _taxonomy(facts, taxonomy)
    lowered = {tag.casefold(): tag for tag in available}
    form_set = {form.upper() for form in (forms or [])}
    groups: list[dict] = []
    missing: list[str] = []
    recognized = False

    for concept in concepts:
        actual = lowered.get(concept.casefold())
        if actual is None:
            missing.append(concept)
            continue
        recognized = True
        payload = available[actual]
        unit_groups: dict[str, list[dict]] = {}
        for entry in _flatten(payload, taxonomy, actual):
            if unit and entry["unit"] != unit:
                continue
            end = entry.get("end") or ""
            if since and end < since:
                continue
            if until and end > until:
                continue
            if not _matches_period(entry, period):
                continue
            if form_set and str(entry.get("form") or "").upper() not in form_set:
                continue
            unit_groups.setdefault(entry["unit"], []).append(entry)

        found_any = False
        for unit_name, entries in unit_groups.items():
            found_any = True
            if dedupe:
                chosen: dict[tuple, dict] = {}
                for entry in entries:
                    key = (entry.get("start"), entry.get("end"))
                    previous = chosen.get(key)
                    if previous is None or (entry.get("filed") or "", entry.get("accn") or "") > (
                        previous.get("filed") or "",
                        previous.get("accn") or "",
                    ):
                        chosen[key] = entry
                entries = list(chosen.values())
            entries.sort(key=lambda entry: (entry.get("end") or "", entry.get("start") or ""))
            total = len(entries)
            page = entries[offset : offset + limit]
            groups.append(
                {
                    "taxonomy": taxonomy,
                    "tag": actual,
                    "label": payload.get("label") or actual,
                    "unit": unit_name,
                    "facts": page,
                    "total": total,
                    "last_end": entries[-1].get("end") if entries else None,
                    "truncated": offset + len(page) < total,
                    "next_offset": offset + len(page) if offset + len(page) < total else None,
                }
            )
        if not found_any:
            missing.append(concept)

    if not groups:
        if recognized:
            return {
                "groups": [],
                "missing": missing,
                "count": 0,
                "total": 0,
            }
        suggestions = list_concepts(facts, query=concepts[0] if concepts else None, taxonomy=taxonomy, limit=5)
        hint = None
        if suggestions:
            hint = "Did you mean: " + ", ".join(row["tag"] for row in suggestions) + "?"
        raise NotFoundError(
            f"No facts found for {', '.join(concepts)} in {taxonomy}."
            + (f" {hint}" if hint else ""),
            hint or "Use `edgar concepts <ticker> --query <text>` to find tags.",
        )

    return {
        "groups": groups,
        "missing": missing,
        "count": sum(len(group["facts"]) for group in groups),
        "total": sum(group["total"] for group in groups),
    }
