import unittest

from edgar.base.errors import NotFoundError
from edgar.base.facts import detect_taxonomy, list_concepts, select_facts


def facts_fixture():
    return {
        "cik": 1,
        "entityName": "Example Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "description": "Revenue from sales.",
                    "units": {
                        "USD": [
                            {
                                "start": "2023-01-01",
                                "end": "2023-12-31",
                                "val": 90,
                                "accn": "a0",
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-02-01",
                                "frame": "CY2023",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 100,
                                "accn": "a1",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                                "frame": "CY2024",
                            },
                            {
                                "start": "2024-01-01",
                                "end": "2024-12-31",
                                "val": 110,
                                "accn": "a2",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K/A",
                                "filed": "2025-03-01",
                            },
                            {
                                "start": "2025-01-01",
                                "end": "2025-03-31",
                                "val": 30,
                                "accn": "a3",
                                "fy": 2025,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2025-05-01",
                            },
                        ]
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                "end": "2024-12-31",
                                "val": 500,
                                "accn": "a4",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2025-02-01",
                            }
                        ]
                    },
                },
            }
        },
    }


def ifrs_fixture():
    return {
        "cik": 2,
        "entityName": "Foreign Example Ltd",
        "facts": {
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": []}}},
            "ifrs-full": {
                "Revenue": {
                    "label": "Revenue",
                    "units": {
                        "USD": [
                            {
                                "start": "2025-01-01",
                                "end": "2025-12-31",
                                "val": 42,
                                "accn": "f1",
                                "form": "20-F",
                                "filed": "2026-03-01",
                            }
                        ]
                    },
                }
            },
        },
    }


class TaxonomyTests(unittest.TestCase):
    def test_prefers_us_gaap_when_present(self):
        self.assertEqual(detect_taxonomy(facts_fixture()), "us-gaap")

    def test_falls_back_to_ifrs(self):
        self.assertEqual(detect_taxonomy(ifrs_fixture()), "ifrs-full")

    def test_ifrs_concepts_and_facts(self):
        result = list_concepts(ifrs_fixture(), query="revenue", taxonomy="ifrs-full")
        self.assertEqual([c["tag"] for c in result], ["Revenue"])
        selected = select_facts(ifrs_fixture(), ["Revenue"], taxonomy="ifrs-full", period="annual")
        self.assertEqual(selected["groups"][0]["facts"][0]["val"], 42)


class ConceptTests(unittest.TestCase):
    def test_search_by_label(self):
        result = list_concepts(facts_fixture(), query="rev")
        self.assertEqual([c["tag"] for c in result], ["Revenues"])
        self.assertNotIn("description", result[0])

    def test_search_detail(self):
        result = list_concepts(facts_fixture(), query="rev", include_description=True)
        self.assertEqual(result[0]["description"], "Revenue from sales.")


class FactTests(unittest.TestCase):
    def test_annual_dedupes_to_latest_filing(self):
        result = select_facts(facts_fixture(), ["Revenues"], period="annual")
        group = result["groups"][0]
        values = [(f["end"], f["val"]) for f in group["facts"]]
        self.assertEqual(values, [("2023-12-31", 90), ("2024-12-31", 110)])

    def test_all_keeps_duplicates(self):
        result = select_facts(facts_fixture(), ["Revenues"], period="annual", dedupe=False)
        self.assertEqual(len(result["groups"][0]["facts"]), 3)

    def test_quarterly(self):
        result = select_facts(facts_fixture(), ["Revenues"], period="quarterly")
        self.assertEqual([f["val"] for f in result["groups"][0]["facts"]], [30])

    def test_instant(self):
        result = select_facts(facts_fixture(), ["Assets"], period="instant")
        self.assertEqual([f["val"] for f in result["groups"][0]["facts"]], [500])

    def test_since(self):
        result = select_facts(facts_fixture(), ["Revenues"], period="annual", since="2024-01-01")
        self.assertEqual([f["val"] for f in result["groups"][0]["facts"]], [110])

    def test_form_filter(self):
        result = select_facts(facts_fixture(), ["Revenues"], period="annual", forms=["10-K/A"])
        self.assertEqual([f["val"] for f in result["groups"][0]["facts"]], [110])

    def test_case_insensitive_concept(self):
        result = select_facts(facts_fixture(), ["revenues"], period="annual")
        self.assertEqual(result["groups"][0]["tag"], "Revenues")

    def test_missing_concept_suggests(self):
        with self.assertRaises(NotFoundError) as ctx:
            select_facts(facts_fixture(), ["Revenue"])
        self.assertIn("Revenues", str(ctx.exception))

    def test_partial_missing(self):
        result = select_facts(facts_fixture(), ["Revenues", "Nope"], period="annual")
        self.assertEqual(result["missing"], ["Nope"])
        self.assertEqual(len(result["groups"]), 1)

    def test_unit_filter(self):
        result = select_facts(facts_fixture(), ["Revenues"], unit="EUR")
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["missing"], ["Revenues"])


if __name__ == "__main__":
    unittest.main()
