from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from lxml import html as lxml_html
from lxml.etree import Element, _Element

from edgar.base.errors import ParseError

BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "caption",
    "center",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "ul",
}

SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}

_SPACE_RE = re.compile(r"[\s  -   　]+")
_ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿]")
_FONT_SIZE_RE = re.compile(
    r"font(?:-size)?\s*:\s*(?:[a-z\-]+\s+)*([0-9.]+)\s*(pt|px)", re.IGNORECASE
)
_FONT_WEIGHT_RE = re.compile(r"font-weight\s*:\s*([6-9]00|bold)", re.IGNORECASE)
_HEADING_FONT_SIZES = {"h1": 18.0, "h2": 16.0, "h3": 14.0, "h4": 12.0, "h5": 11.0, "h6": 10.0}


@dataclass
class Block:
    text: str
    tag: str
    order: int
    is_table: bool = False
    element: _Element | None = None
    table: _Element | None = None
    font_size: float | None = None
    bold: bool = False

    @property
    def is_heading_candidate(self) -> bool:
        return not self.is_table


def normalize_text(value: str) -> str:
    value = _ZERO_WIDTH_RE.sub("", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return _SPACE_RE.sub(" ", value).strip()


def _local_tag(element) -> str:
    tag = element.tag
    if not isinstance(tag, str):
        return ""
    if "}" in tag:
        tag = tag.split("}", 1)[1]
    return tag.lower()


def _is_hidden(element) -> bool:
    tag = _local_tag(element)
    if tag in {"script", "style", "noscript", "template"}:
        return True
    if ":" in str(element.tag):
        suffix = str(element.tag).split(":", 1)[1].lower()
        if suffix in {"header", "hidden", "references"}:
            return True
    style = (element.get("style") or "").replace(" ", "").lower()
    if "display:none" in style or "visibility:hidden" in style:
        return True
    classes = (element.get("class") or "").lower().split()
    return "hidden" in classes or "xbrl-hidden" in classes


def _inline_text(element: _Element) -> str:
    parts: list[str] = [element.text or ""]
    for child in element:
        if not isinstance(child.tag, str):
            parts.append(child.tail or "")
            continue
        tag = _local_tag(child)
        if _is_hidden(child):
            pass
        elif tag == "br":
            parts.append("\n")
        elif tag in BLOCK_TAGS or tag == "table":
            pass
        else:
            parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def parse_document(content: bytes | str) -> _Element:
    if isinstance(content, str):
        content = content.encode("utf-8")
    if not content.strip():
        raise ParseError("Document is empty.")
    try:
        return lxml_html.fromstring(content)
    except (ValueError, TypeError) as exc:
        raise ParseError("Could not parse the document as HTML.") from exc


def _element_order(doc: _Element) -> dict[_Element, int]:
    return {element: index for index, element in enumerate(doc.iter())}


def _table_rows(table: _Element) -> Iterable[_Element]:
    rows = table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")
    if rows:
        return rows
    return table.xpath(".//tr[not(ancestor::table[2])]")


def _row_cells(row: _Element) -> list[_Element]:
    return [child for child in row if isinstance(child.tag, str) and _local_tag(child) in {"td", "th"}]


def _style_info(element: _Element) -> tuple[float | None, bool]:
    sizes: list[float] = []
    bold = False
    for node in element.iter():
        if not isinstance(node.tag, str):
            continue
        tag = _local_tag(node)
        if tag in _HEADING_FONT_SIZES:
            sizes.append(_HEADING_FONT_SIZES[tag])
            bold = True
        if tag in {"b", "strong"}:
            bold = True
        style = node.get("style") or ""
        for match in _FONT_SIZE_RE.finditer(style):
            size = float(match.group(1))
            if match.group(2).lower() == "px":
                size *= 0.75
            sizes.append(size)
        if _FONT_WEIGHT_RE.search(style):
            bold = True
    return (max(sizes) if sizes else None), bold


def _cell_text(cell: _Element) -> str:
    parts: list[str] = []

    def walk(element: _Element):
        if element.text:
            parts.append(element.text)
        for child in element:
            if not isinstance(child.tag, str):
                if child.tail:
                    parts.append(child.tail)
                continue
            tag = _local_tag(child)
            spaced = tag in BLOCK_TAGS or tag in {"table", "br", "tr", "td", "th"}
            if spaced:
                parts.append(" ")
            walk(child)
            if spaced:
                parts.append(" ")
            if child.tail:
                parts.append(child.tail)

    walk(cell)
    return normalize_text("".join(parts))


class _Walker:
    def __init__(self, order: dict[_Element, int]):
        self.order = order
        self.blocks: list[Block] = []

    def walk(self, element: _Element):
        tag = _local_tag(element)
        if _is_hidden(element):
            return
        if tag == "table":
            for row in _table_rows(element):
                cells = [_cell_text(cell) for cell in _row_cells(row)]
                text = normalize_text(" | ".join(cell for cell in cells if cell))
                if text:
                    self.blocks.append(
                        Block(
                            text=text,
                            tag="tr",
                            order=self.order.get(element, 0),
                            is_table=True,
                            element=row,
                            table=element,
                        )
                    )
            return
        if tag in BLOCK_TAGS:
            text = normalize_text(_inline_text(element))
            if text:
                font_size = None
                bold = False
                if len(text) <= 220:
                    font_size, bold = _style_info(element)
                self.blocks.append(
                    Block(
                        text=text,
                        tag=tag,
                        order=self.order.get(element, 0),
                        element=element,
                        font_size=font_size,
                        bold=bold,
                    )
                )
        for child in element:
            if isinstance(child.tag, str):
                self.walk(child)


def iter_blocks(doc: _Element) -> list[Block]:
    order = _element_order(doc)
    walker = _Walker(order)
    body = doc.body if getattr(doc, "body", None) is not None else doc
    walker.walk(body)
    return walker.blocks


def iter_tables(doc: _Element) -> list[tuple[_Element, int]]:
    order = _element_order(doc)
    return [(table, order.get(table, 0)) for table in doc.iter("table") if isinstance(table.tag, str)]


def table_matrix(table: _Element) -> list[list[str]]:
    rows: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}
    for row_index, row in enumerate(_table_rows(table)):
        values: list[str] = []
        column = 0
        while (row_index, column) in pending:
            values.append(pending.pop((row_index, column)))
            column += 1
        for cell in _row_cells(row):
            while (row_index, column) in pending:
                values.append(pending.pop((row_index, column)))
                column += 1
            try:
                colspan = max(1, int(cell.get("colspan") or 1))
            except ValueError:
                colspan = 1
            try:
                rowspan = max(1, int(cell.get("rowspan") or 1))
            except ValueError:
                rowspan = 1
            text = _cell_text(cell)
            for offset in range(colspan):
                values.append(text if offset == 0 else "")
                if rowspan > 1:
                    for down in range(1, rowspan):
                        pending[(row_index + down, column + offset)] = text if offset == 0 else ""
            column += colspan
        max_column = max([len(values)] + [c + 1 for (r, c) in pending if r == row_index])
        while column < max_column:
            values.append(pending.pop((row_index, column), ""))
            column += 1
        if values:
            rows.append(values)
    if not rows:
        return []
    width = max(len(row) for row in rows)
    keep = [
        column
        for column in range(width)
        if any(column < len(row) and row[column] for row in rows)
    ]
    if len(keep) != width:
        rows = [
            [row[column] if column < len(row) else "" for column in keep] for row in rows
        ]
    return rows


def table_context_block(blocks: list[Block], table: _Element) -> Block | None:
    table_order = None
    for block in blocks:
        if block.is_table and block.table is table:
            table_order = block.order
            break
    if table_order is None:
        return None
    candidate = None
    for block in blocks:
        if not block.is_table and block.order < table_order:
            candidate = block
    return candidate


def table_context(blocks: list[Block], table: _Element) -> str | None:
    block = table_context_block(blocks, table)
    return block.text if block else None


def extract_text(blocks: list[Block], include_tables: bool = True) -> str:
    return "\n\n".join(block.text for block in blocks if include_tables or not block.is_table)


def looks_like_html(content: bytes) -> bool:
    head = content.lstrip()[:512].lower()
    return (
        head.startswith(b"<!doctype html")
        or head.startswith(b"<html")
        or head.startswith(b"<table")
        or b"<body" in head
    )
