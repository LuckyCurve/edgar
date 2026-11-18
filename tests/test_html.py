import unittest

from edgar.base.html import (
    extract_text,
    iter_blocks,
    iter_tables,
    normalize_text,
    parse_document,
    table_context,
    table_matrix,
)


def doc(html: str):
    return parse_document(html.encode("utf-8"))


class BlockTests(unittest.TestCase):
    def test_blocks_are_not_duplicated(self):
        root = doc("<html><body><div><p>Hello <b>world</b>.</p><p>Second <i>line</i>.</p></div></body></html>")
        texts = [b.text for b in iter_blocks(root) if not b.is_table]
        self.assertEqual(texts, ["Hello world.", "Second line."])

    def test_table_rows_are_blocks_and_not_plain_text(self):
        root = doc("<html><body><p>Before</p><table><tr><td>A</td><td>B</td></tr></table><p>After</p></body></html>")
        blocks = iter_blocks(root)
        self.assertEqual([b.text for b in blocks], ["Before", "A | B", "After"])
        self.assertEqual([b.is_table for b in blocks], [False, True, False])

    def test_text_skips_tables_when_asked(self):
        root = doc("<html><body><p>Before</p><table><tr><td>A</td></tr></table><p>After</p></body></html>")
        blocks = iter_blocks(root)
        text = extract_text(blocks, include_tables=False)
        self.assertEqual(text, "Before\n\nAfter")

    def test_normalize_whitespace(self):
        self.assertEqual(normalize_text(" a   b\n\t c "), "a b c")


class TableTests(unittest.TestCase):
    def test_matrix(self):
        root = doc(
            "<table>"
            "<tr><th>Name</th><th colspan='2'>Pay</th></tr>"
            "<tr><td rowspan='2'>Cook</td><td>2025</td><td>1</td></tr>"
            "<tr><td>2024</td><td>2</td></tr>"
            "</table>"
        )
        table = iter_tables(root)[0][0]
        self.assertEqual(
            table_matrix(table),
            [
                ["Name", "Pay", ""],
                ["Cook", "2025", "1"],
                ["Cook", "2024", "2"],
            ],
        )

    def test_nested_table_rows_do_not_leak_into_outer(self):
        root = doc(
            "<table><tr><td>outer1</td><td>outer2</td></tr>"
            "<tr><td>inner<table><tr><td>i1</td><td>i2</td></tr></table></td></tr></table>"
        )
        outer, inner = iter_tables(root)
        self.assertEqual(table_matrix(outer[0]), [["outer1", "outer2"], ["inner i1 i2"]])
        self.assertEqual(table_matrix(inner[0]), [["i1", "i2"]])

    def test_empty_columns_are_dropped(self):
        root = doc(
            "<table>"
            "<tr><td>Name</td><td></td><td>Pay</td></tr>"
            "<tr><td>Cook</td><td></td><td>1</td></tr>"
            "</table>"
        )
        table = iter_tables(root)[0][0]
        self.assertEqual(table_matrix(table), [["Name", "Pay"], ["Cook", "1"]])

    def test_context(self):
        root = doc("<body><div>Section A</div><p>Words</p><table><tr><td>1</td></tr></table></body>")
        blocks = iter_blocks(root)
        table = iter_tables(root)[0][0]
        self.assertEqual(table_context(blocks, table), "Words")


if __name__ == "__main__":
    unittest.main()
