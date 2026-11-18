import unittest

from edgar.base.errors import AmbiguousError, NotFoundError, UsageError
from edgar.base.refs import (
    accession_nodash,
    filing_doc_url,
    filing_index_url,
    lookup,
    normalize_accession,
    normalize_cik,
    pick_company,
)


class FakeClient:
    def __init__(self, tickers):
        self.tickers = tickers

    def get_json(self, url, ttl=0, refresh=False):
        assert url.endswith("company_tickers.json")
        return self.tickers


def ticker_rows():
    return {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
        "2": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."},
        "3": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    }


class RefTests(unittest.TestCase):
    def test_normalize_cik(self):
        self.assertEqual(normalize_cik(320193), "0000320193")
        self.assertEqual(normalize_cik("320193"), "0000320193")
        self.assertEqual(normalize_cik("CIK0000320193"), "0000320193")
        with self.assertRaises(UsageError):
            normalize_cik("AAPL")

    def test_accession(self):
        self.assertEqual(normalize_accession("000032019326000026"), "0000320193-26-000026")
        self.assertEqual(normalize_accession("0000320193-26-000026"), "0000320193-26-000026")
        self.assertEqual(accession_nodash("0000320193-26-000026"), "000032019326000026")
        with self.assertRaises(UsageError):
            normalize_accession("nope")

    def test_urls(self):
        self.assertEqual(
            filing_index_url("320193", "0000320193-26-000026"),
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/index.json",
        )
        self.assertEqual(
            filing_doc_url("320193", "0000320193-26-000026", "aapl.htm"),
            "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/aapl.htm",
        )

    def test_lookup_exact_ticker_and_dedupe(self):
        result = lookup(FakeClient(ticker_rows()), "googl")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["cik"], "0001652044")
        self.assertEqual(result[0]["tickers"], ["GOOG", "GOOGL"])

    def test_lookup_name(self):
        result = lookup(FakeClient(ticker_rows()), "apple")
        self.assertEqual(result[0]["cik"], "0000320193")

    def test_lookup_not_found(self):
        self.assertEqual(lookup(FakeClient(ticker_rows()), "ZZZZ"), [])

    def test_pick_ambiguous(self):
        with self.assertRaises(AmbiguousError):
            pick_company(FakeClient(ticker_rows()), "inc")

    def test_pick_not_found(self):
        with self.assertRaises(NotFoundError):
            pick_company(FakeClient(ticker_rows()), "ZZZZ")


if __name__ == "__main__":
    unittest.main()
