import unittest

from edgar.base.compensation import map_tables_to_sections
from edgar.base.html import iter_blocks, iter_tables, parse_document
from edgar.base.sections import extract_sections

HTML = """
<html><body>
<div>Compensation Discussion and Analysis</div><p>CD&amp;A text.</p>
<div>Summary Compensation Table—2025</div>
<table><tr><th>Name</th><th>Salary</th><th>Total</th></tr>
<tr><td>Cook</td><td>1</td><td>2</td></tr></table>
<div>Outstanding Equity Awards—2025</div>
<table><tr><th>Name</th><th>Shares</th><th>Value</th></tr>
<tr><td>Cook</td><td>3</td><td>4</td></tr></table>
<div>Equity Compensation Plan Information</div>
<table><tr><th>Plan</th><th>Shares</th><th>Weighted</th></tr>
<tr><td>A</td><td>5</td><td>6</td></tr></table>
</body></html>
"""


class CompensationTests(unittest.TestCase):
    def test_mapping(self):
        doc = parse_document(HTML.encode("utf-8"))
        blocks = iter_blocks(doc)
        tables = iter_tables(doc)
        sections = extract_sections(blocks, "DEF 14A")
        mapping = map_tables_to_sections(blocks, tables, sections)
        self.assertEqual(mapping["summary-compensation-table"][0]["rows"][1][0], "Cook")
        self.assertEqual(mapping["summary-compensation-table"][0]["rows"][1][1], "1")
        self.assertEqual(mapping["outstanding-equity-awards"][0]["rows"][0], ["Name", "Shares", "Value"])
        self.assertNotIn("compensation-discussion-and-analysis", mapping)
        self.assertEqual(mapping["equity-compensation-plan-information"][0]["n_rows"], 2)

    def test_footnote_tables_are_skipped(self):
        html = """
        <html><body>
        <div>Summary Compensation Table—2025</div>
        <table><tr><th>Name</th><th>Salary</th><th>Total</th></tr>
        <tr><td>Cook</td><td>1</td><td>2</td></tr></table>
        <p>(1) Amounts reflect salary.</p>
        <table><tr><th>Note</th><th>Text</th><th>More</th></tr>
        <tr><td>(1)</td><td>Footnote</td><td>x</td></tr></table>
        </body></html>
        """
        doc = parse_document(html.encode("utf-8"))
        blocks = iter_blocks(doc)
        tables = iter_tables(doc)
        sections = extract_sections(blocks, "DEF 14A")
        mapping = map_tables_to_sections(blocks, tables, sections)
        self.assertEqual(len(mapping["summary-compensation-table"]), 1)

    def test_row_cap(self):
        doc = parse_document(HTML.encode("utf-8"))
        blocks = iter_blocks(doc)
        tables = iter_tables(doc)
        sections = extract_sections(blocks, "DEF 14A")
        mapping = map_tables_to_sections(blocks, tables, sections, max_rows=1)
        summary = mapping["summary-compensation-table"][0]
        self.assertEqual(summary["n_rows"], 2)
        self.assertTrue(summary["truncated"])
        self.assertEqual(len(summary["rows"]), 1)


if __name__ == "__main__":
    unittest.main()
