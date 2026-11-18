from __future__ import annotations

import re
from typing import Iterable

from edgar.base.errors import NotFoundError
from edgar.base.html import Block, extract_text

ITEM_RE = re.compile(r"^item\s+(\d{1,2}(?:\.\d{2})?[A-Z]?)\s*[\.\:\-–—]?\s*(.*)$", re.IGNORECASE)
PART_RE = re.compile(r"^part\s+(i{1,3}|iv)\b", re.IGNORECASE)

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "40-F", "40-F/A"}
TWENTY_F_FORMS = {"20-F", "20-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
CURRENT_FORMS = {"8-K", "8-K/A"}
PROXY_FORMS = {"DEF 14A", "DEFR14A", "PRE 14A", "PRE14A", "DEFA14A", "DEFM14A"}

_TEN_K_ALIASES = {
    "business": ("1", None),
    "risk-factors": ("1A", None),
    "risk": ("1A", None),
    "legal": ("3", None),
    "mda": ("7", None),
    "md&a": ("7", None),
    "management-discussion": ("7", None),
    "market-risk": ("7A", None),
    "financial-statements": ("8", None),
    "controls": ("9A", None),
    "directors": ("10", None),
    "executive-compensation": ("11", None),
    "ownership": ("12", None),
    "related-party": ("13", None),
    "auditor-fees": ("14", None),
    "exhibits": ("15", None),
}

_TWENTY_F_ALIASES = {
    "risk-factors": ("3", None),
    "risk": ("3", None),
    "key-information": ("3", None),
    "business": ("4", None),
    "mda": ("5", None),
    "md&a": ("5", None),
    "management-discussion": ("5", None),
    "operating-financial-review": ("5", None),
    "directors": ("6", None),
    "executive-compensation": ("6", None),
    "compensation": ("6", None),
    "major-shareholders": ("7", None),
    "related-party": ("7", None),
    "financial-statements": ("18", None),
    "exhibits": ("19", None),
}

_TEN_Q_ALIASES = {
    "financial-statements": ("1", "I"),
    "mda": ("2", "I"),
    "md&a": ("2", "I"),
    "market-risk": ("3", "I"),
    "controls": ("4", "I"),
    "legal": ("1", "II"),
    "risk-factors": ("1A", "II"),
    "risk": ("1A", "II"),
    "other-information": ("5", "II"),
    "exhibits": ("6", "II"),
}

_EIGHT_K_ALIASES = {
    "results": "2.02",
    "officers": "5.02",
    "executive-compensation": "5.02",
    "other-events": "8.01",
    "exhibits": "9.01",
}

_PROXY_HEADINGS = [
    ("compensation-discussion-and-analysis", r"compensation discussion and analysis"),
    ("summary-compensation-table", r"summary compensation table"),
    ("grants-of-plan-based-awards", r"grants of plan-based awards"),
    ("outstanding-equity-awards", r"outstanding equity awards"),
    ("option-exercises-and-stock-vested", r"option exercises and stock vested|stock vested"),
    ("pension-benefits", r"pension benefits"),
    ("nonqualified-deferred-compensation", r"non-?qualified deferred compensation"),
    ("potential-payments-upon-termination", r"potential payments upon termination|termination or change in control"),
    ("pay-versus-performance", r"pay versus performance"),
    ("equity-compensation-plan-information", r"equity compensation plan information"),
    ("director-compensation", r"director compensation|compensation of directors"),
    ("ceo-pay-ratio", r"ceo pay ratio|pay ratio"),
    ("compensation-committee", r"compensation committee"),
    ("stock-ownership-guidelines", r"stock ownership guidelines"),
]


def _form_family(form: str) -> str:
    value = form.upper().strip()
    if value in TWENTY_F_FORMS:
        return "twenty-f"
    if value in ANNUAL_FORMS:
        return "annual"
    if value in QUARTERLY_FORMS:
        return "quarterly"
    if value in CURRENT_FORMS:
        return "current"
    if value in PROXY_FORMS:
        return "proxy"
    return "other"


def _aliases(form_family: str, item: str, part: str | None) -> list[str]:
    if form_family == "annual":
        return [name for name, (number, _) in _TEN_K_ALIASES.items() if number == item]
    if form_family == "twenty-f":
        return [name for name, (number, _) in _TWENTY_F_ALIASES.items() if number == item]
    if form_family == "quarterly":
        return [
            name
            for name, (number, section_part) in _TEN_Q_ALIASES.items()
            if number == item and (section_part is None or section_part == part)
        ]
    if form_family == "current":
        return [name for name, number in _EIGHT_K_ALIASES.items() if number == item]
    return []


def _find_items(blocks: Iterable[Block], form_family: str):
    part: str | None = None
    part_boundaries: list[int] = []
    candidates: list[dict] = []
    for index, block in enumerate(blocks):
        if block.is_table:
            continue
        text = block.text
        if len(text) < 160:
            part_match = PART_RE.match(text)
            if part_match:
                part = part_match.group(1).upper()
                part_boundaries.append(index)
                continue
        if len(text) > 300:
            continue
        item_match = ITEM_RE.match(text)
        if not item_match:
            continue
        if len(re.findall(r"\bitem\s+\d", text, re.IGNORECASE)) != 1:
            continue
        item = item_match.group(1).upper()
        candidates.append(
            {
                "index": index,
                "part": part,
                "item": item,
                "heading": text,
                "title": item_match.group(2).strip(" .-–—") or text,
            }
        )

    selected: dict[tuple[str | None, str], dict] = {}
    for candidate in candidates:
        selected[(candidate["part"], candidate["item"])] = candidate
    return list(selected.values()), part_boundaries


def _dedupe_ids(entries: list[dict], form_family: str) -> None:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["item"]] = counts.get(entry["item"], 0) + 1
    for entry in entries:
        item_slug = entry["item"].lower().replace(".", "-")
        if form_family in {"annual", "twenty-f"} and counts[entry["item"]] == 1:
            entry["id"] = f"item-{item_slug}"
        else:
            part_slug = (entry["part"] or "x").lower()
            entry["id"] = f"part-{part_slug}-item-{item_slug}"
        entry["aliases"] = _aliases(form_family, entry["item"], entry["part"])


def _build_sections(blocks: list[Block], entries: list[dict], boundaries: list[int]) -> list[dict]:
    entries = sorted(entries, key=lambda entry: entry["index"])
    stops = sorted(set(boundaries) | {entry["index"] for entry in entries})
    output: list[dict] = []
    for entry in entries:
        start = entry["index"]
        end = next((stop for stop in stops if stop > start), len(blocks))
        text = extract_text(blocks[start + 1 : end])
        output.append(
            {
                "id": entry.get("id"),
                "part": entry.get("part"),
                "item": entry.get("item"),
                "title": entry["title"],
                "heading": entry["heading"],
                "aliases": entry.get("aliases", []),
                "chars": len(text),
                "text": text,
                "start_block": start,
                "end_block": end,
            }
        )
    return output


def _extract_proxy_sections(blocks: list[Block]) -> list[dict]:
    found: dict[str, dict] = {}
    for index, block in enumerate(blocks):
        if block.is_table or len(block.text) > 160:
            continue
        text = block.text
        heading_like = (
            (block.font_size or 0) >= 10.5
            or block.bold
            or block.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
            or len(text) <= 60
        )
        if not heading_like:
            continue
        for key, pattern in _PROXY_HEADINGS:
            if re.search(pattern, text, re.IGNORECASE):
                current = found.get(key)
                if current is None or (len(text), -index) < (
                    len(current["title"]),
                    -current["index"],
                ):
                    found[key] = {"index": index, "key": key, "title": text}
                break

    entries = sorted(found.values(), key=lambda entry: entry["index"])
    known = {entry["index"] for entry in entries}
    major: set[int] = set()
    for index, block in enumerate(blocks):
        if block.is_table or not block.text:
            continue
        if index in known:
            major.add(index)
            continue
        if len(block.text) > 160:
            continue
        if (block.font_size or 0) >= 14 or block.tag in {"h1", "h2", "h3"}:
            major.add(index)
        elif re.match(r"^(proposal|item|part)\s+", block.text, re.IGNORECASE) and len(block.text) <= 80:
            major.add(index)

    major_sorted = sorted(major)
    output: list[dict] = []
    for entry in entries:
        start = entry["index"]
        end = next((stop for stop in major_sorted if stop > start), len(blocks))
        text = extract_text(blocks[start + 1 : end], include_tables=False)
        output.append(
            {
                "id": entry["key"],
                "part": None,
                "item": None,
                "title": entry["title"],
                "heading": entry["title"],
                "aliases": [],
                "chars": len(text),
                "text": text,
                "start_block": start,
                "end_block": end,
            }
        )
    return output


def extract_sections(blocks: list[Block], form: str) -> list[dict]:
    family = _form_family(form)
    if family == "proxy":
        return _extract_proxy_sections(blocks)
    if family == "other":
        return []

    entries, part_boundaries = _find_items(blocks, family)
    if not entries:
        return []
    _dedupe_ids(entries, family)
    return _build_sections(blocks, entries, part_boundaries)


def find_section(sections: list[dict], spec: str) -> dict:
    needle = str(spec).strip().lower()
    if not needle:
        raise NotFoundError("No section specified.")
    for section in sections:
        if needle == str(section.get("id") or "").lower():
            return section
    for section in sections:
        if needle in {alias.lower() for alias in section.get("aliases", [])}:
            return section
    for section in sections:
        if needle == str(section.get("item") or "").lower():
            return section
        part = section.get("part")
        if part and needle in {
            f"part-{str(part).lower()}-item-{str(section.get('item')).lower()}",
            f"{str(part).lower()}-{str(section.get('item')).lower()}",
        }:
            return section
    for section in sections:
        if needle in str(section.get("title") or "").lower():
            return section
    available = ", ".join(str(section.get("id")) for section in sections) or "(none)"
    raise NotFoundError(
        f"No section matches {spec!r}.",
        f"Available sections: {available}",
    )
