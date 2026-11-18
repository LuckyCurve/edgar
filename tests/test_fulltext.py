import unittest

from edgar.base.fulltext import search


class FakeClient:
    def __init__(self):
        self.url = None

    def get_json(self, url, ttl=0, refresh=False):
        self.url = url
        return {
            "took": 12,
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_id": "0000320193-26-000026:aapl-20260926.htm",
                        "_score": 9.5,
                        "_source": {
                            "adsh": "0000320193-26-000026",
                            "ciks": ["0000320193"],
                            "form": "10-K",
                            "file_date": "2026-11-03",
                            "period_ending": "2026-09-26",
                            "display_names": ["Apple Inc.  (AAPL)  (CIK 0000320193)"],
                            "file_type": "10-K",
                            "file_description": "10-K",
                        },
                    }
                ],
            },
        }


class SearchTests(unittest.TestCase):
    def test_search(self):
        client = FakeClient()
        result = search(client, '"artificial intelligence"', forms=["10-K"], cik="320193",
                        since="2025-01-01", until="2026-11-18", limit=5)
        self.assertIn("q=%22artificial+intelligence%22", client.url)
        self.assertIn("forms=10-K", client.url)
        self.assertIn("ciks=0000320193", client.url)
        self.assertEqual(result["total"]["value"], 1)
        hit = result["hits"][0]
        self.assertEqual(hit["accession"], "0000320193-26-000026")
        self.assertEqual(hit["form"], "10-K")
        self.assertTrue(hit["document_url"].endswith("/aapl-20260926.htm"))


if __name__ == "__main__":
    unittest.main()
