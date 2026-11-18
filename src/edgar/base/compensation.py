from __future__ import annotations

import re

from edgar.base.html import Block, table_context, table_matrix


def _table_block_index(blocks: list[Block], table) -> int | None:
    for index, block in enumerate(blocks):
        if block.is_table and block.table is table:
            return index
    return None


def map_tables_to_sections(
    blocks: list[Block],
    tables: list[tuple],
    sections: list[dict],
    max_rows: int | None = None,
    min_rows: int = 2,
    min_cols: int = 3,
) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    seen: dict[str, set[tuple]] = {}
    for table_index, (table, _order) in enumerate(tables):
        block_index = _table_block_index(blocks, table)
        if block_index is None:
            continue
        section = next(
            (
                candidate
                for candidate in sections
                if candidate["start_block"] < block_index < candidate["end_block"]
            ),
            None,
        )
        if section is None:
            continue
        context = table_context(blocks, table) or ""
        if re.match(r"^\s*\(\d+\)", context) or context.lower().startswith("notes to"):
            continue
        rows = table_matrix(table)
        if len(rows) < min_rows:
            continue
        width = max(len(row) for row in rows)
        if width < min_cols:
            continue
        key = tuple(tuple(row) for row in rows)
        bucket = seen.setdefault(section["id"], set())
        if key in bucket:
            continue
        bucket.add(key)
        payload = {
            "table_index": table_index,
            "n_rows": len(rows),
            "n_cols": width,
            "header": next((row for row in rows if any(row)), rows[0]),
            "rows": rows if max_rows is None else rows[:max_rows],
            "truncated": max_rows is not None and len(rows) > max_rows,
        }
        mapping.setdefault(section["id"], []).append(payload)
    return mapping
