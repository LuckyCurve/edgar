import unittest

from edgar.base.html import iter_blocks, parse_document
from edgar.base.sections import extract_sections, find_section


TEN_K = """
<html><body>
<table>
  <tr><td>Item 1. Business 5</td></tr>
  <tr><td>Item 1A. Risk Factors 10</td></tr>
  <tr><td>Item 7. MD&amp;A 20</td></tr>
</table>
<div>PART I</div>
<div>Item 1. Business</div>
<p>Apple designs things.</p>
<div>Item 1A. Risk Factors</div>
<p>Risks here.</p>
<div>PART II</div>
<div>Item 7. Management's Discussion and Analysis</div>
<p>MD&amp;A text.</p>
<div>Item 8. Financial Statements</div>
<p>Statements.</p>
</body></html>
"""

TEN_Q = """
<html><body>
<div>PART I</div>
<div>Item 1. Financial Statements</div><p>FS text.</p>
<div>Item 2. Management's Discussion and Analysis</div><p>Quarterly MD&amp;A.</p>
<div>PART II</div>
<div>Item 1. Legal Proceedings</div><p>Legal text.</p>
</body></html>
"""

PROXY = """
<html><body>
<div>Compensation Discussion and Analysis</div><p>CD&amp;A text.</p>
<div>Summary Compensation Table—2025</div>
<table><tr><th>Name</th><th>Pay</th></tr><tr><td>Cook</td><td>1</td></tr></table>
<div>Outstanding Equity Awards—2025</div>
<table><tr><th>Name</th><th>Shares</th></tr><tr><td>Cook</td><td>2</td></tr></table>
<div>Pay versus Performance</div><p>PvP text.</p>
<div>Equity Compensation Plan Information</div>
<table><tr><th>Plan</th><th>Shares</th></tr><tr><td>A</td><td>3</td></tr></table>
</body></html>
"""


def sections(html, form):
    doc = parse_document(html.encode("utf-8"))
    return extract_sections(iter_blocks(doc), form)


class TenKTests(unittest.TestCase):
    def test_toc_table_is_ignored(self):
        result = sections(TEN_K, "10-K")
        self.assertEqual([s["id"] for s in result], ["item-1", "item-1a", "item-7", "item-8"])
        item1 = find_section(result, "item-1")
        self.assertIn("Apple designs things.", item1["text"])
        self.assertNotIn("Item 1A", item1["text"])

    def test_alias(self):
        result = sections(TEN_K, "10-K")
        self.assertEqual(find_section(result, "mda")["id"], "item-7")
        self.assertEqual(find_section(result, "risk")["id"], "item-1a")
        self.assertEqual(find_section(result, "business")["id"], "item-1")

    def test_text_stops_at_next_item(self):
        result = sections(TEN_K, "10-K")
        item1a = find_section(result, "item-1a")
        self.assertIn("Risks here.", item1a["text"])
        self.assertNotIn("PART II", item1a["text"])


class TenQTests(unittest.TestCase):
    def test_part_qualified_ids(self):
        result = sections(TEN_Q, "10-Q")
        self.assertEqual(
            [s["id"] for s in result],
            ["part-i-item-1", "part-i-item-2", "part-ii-item-1"],
        )

    def test_aliases_choose_right_part(self):
        result = sections(TEN_Q, "10-Q")
        self.assertEqual(find_section(result, "mda")["id"], "part-i-item-2")
        self.assertEqual(find_section(result, "legal")["id"], "part-ii-item-1")


class ProxyTests(unittest.TestCase):
    def test_known_sections(self):
        result = sections(PROXY, "DEF 14A")
        ids = [s["id"] for s in result]
        self.assertIn("summary-compensation-table", ids)
        self.assertIn("pay-versus-performance", ids)

    def test_proxy_section_text_is_prose_only(self):
        result = sections(PROXY, "DEF 14A")
        summary = find_section(result, "summary-compensation-table")
        self.assertNotIn("Cook | 1", summary["text"])

    def test_unsupported_form(self):
        self.assertEqual(sections("<html><body><p>x</p></body></html>", "8-K"), [])

    def test_major_heading_ends_proxy_section(self):
        html = """
        <html><body>
        <div>Summary Compensation Table—2025</div>
        <p>Table intro.</p>
        <h2>Some Other Major Section</h2>
        <p>Unrelated text.</p>
        </body></html>
        """
        result = sections(html, "DEF 14A")
        summary = find_section(result, "summary-compensation-table")
        self.assertIn("Table intro.", summary["text"])
        self.assertNotIn("Unrelated text.", summary["text"])


if __name__ == "__main__":
    unittest.main()
