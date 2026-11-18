import unittest

from edgar.base.errors import NotFoundError
from edgar.base.submissions import (
    filing_documents,
    find_filing,
    list_filings,
    profile,
)

CIK = "0000320193"


def row(accession, form, filed, primary="doc.htm", report=""):
    return {
        "accessionNumber": accession,
        "filingDate": filed,
        "reportDate": report,
        "acceptanceDateTime": filed + "T12:00:00.000Z",
        "act": "33",
        "form": form,
        "fileNumber": "001-00001",
        "filmNumber": "123",
        "items": "",
        "size": 100,
        "isXBRL": 1,
        "isInlineXBRL": 1,
        "primaryDocument": primary,
        "primaryDocDescription": form,
    }


def submissions():
    return {
        "cik": CIK,
        "name": "Apple Inc.",
        "entityType": "operating",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "category": "Large accelerated filer",
        "fiscalYearEnd": "0925",
        "stateOfIncorporation": "CA",
        "phone": "408-996-1010",
        "website": "",
        "investorWebsite": "",
        "lei": None,
        "ein": "942404110",
        "formerNames": [{"name": "Apple Computer Inc", "from": "1994-01-01", "to": "2007-01-09"}],
        "addresses": {"business": {"city": "CUPERTINO", "stateOrCountry": "CA"}},
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-25-000079", "0000320193-25-000078"],
                "filingDate": ["2025-10-31", "2025-08-01"],
                "reportDate": ["2025-09-27", "2025-06-28"],
                "acceptanceDateTime": ["2025-10-31T18:00:00.000Z", "2025-08-01T18:00:00.000Z"],
                "act": ["33", "33"],
                "form": ["10-K", "10-Q"],
                "fileNumber": ["001-36743", "001-36743"],
                "filmNumber": ["1", "2"],
                "items": ["", ""],
                "size": [100, 50],
                "isXBRL": [1, 1],
                "isInlineXBRL": [1, 1],
                "primaryDocument": ["aapl-20250927.htm", "aapl-20250628.htm"],
                "primaryDocDescription": ["10-K", "10-Q"],
            },
            "files": [
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingCount": 1,
                    "filingFrom": "2019-01-01",
                    "filingTo": "2020-01-01",
                }
            ],
        },
    }


OLD = {
    "accessionNumber": ["0000320193-19-000001"],
    "filingDate": ["2019-11-01"],
    "reportDate": ["2019-09-28"],
    "acceptanceDateTime": ["2019-11-01T18:00:00.000Z"],
    "act": ["33"],
    "form": ["10-K"],
    "fileNumber": ["001-36743"],
    "filmNumber": ["3"],
    "items": [""],
    "size": [90],
    "isXBRL": [1],
    "isInlineXBRL": [0],
    "primaryDocument": ["aapl-20190928.htm"],
    "primaryDocDescription": ["10-K"],
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, ttl=0, refresh=False):
        self.calls.append(url)
        if url.endswith("CIK0000320193.json"):
            return submissions()
        if url.endswith("CIK0000320193-submissions-001.json"):
            return OLD
        if url.endswith("index.json"):
            return {
                "directory": {
                    "item": [
                        {"name": "aapl-20250927.htm", "size": "100", "type": "text.gif"},
                        {"name": "index.json", "size": "", "type": "text.gif"},
                    ]
                }
            }
        raise AssertionError(url)


class ProfileTests(unittest.TestCase):
    def test_profile(self):
        result = profile(FakeClient(), CIK)
        self.assertEqual(result["name"], "Apple Inc.")
        self.assertEqual(result["cik"], CIK)
        self.assertEqual(result["tickers"], ["AAPL"])
        self.assertEqual(result["former_names"][0]["name"], "Apple Computer Inc")
        self.assertNotIn("ein", result)


class FilingTests(unittest.TestCase):
    def test_list_recent(self):
        result = list_filings(FakeClient(), CIK, limit=10)
        self.assertEqual([f["accession"] for f in result["filings"]], [
            "0000320193-25-000079",
            "0000320193-25-000078",
            "0000320193-19-000001",
        ])
        self.assertEqual(result["page"]["total"], 3)
        self.assertTrue(result["complete"])

    def test_form_filter(self):
        result = list_filings(FakeClient(), CIK, forms=["10-Q"], limit=10)
        self.assertEqual([f["form"] for f in result["filings"]], ["10-Q"])

    def test_since_loads_supplemental(self):
        result = list_filings(FakeClient(), CIK, since="2019-01-01", limit=10)
        self.assertEqual(len(result["filings"]), 3)
        self.assertTrue(result["complete"])
        self.assertEqual(result["filings"][-1]["accession"], "0000320193-19-000001")

    def test_find_by_accession_in_supplemental(self):
        result = find_filing(FakeClient(), CIK, accession="0000320193-19-000001")
        self.assertEqual(result["form"], "10-K")

    def test_find_latest_by_form(self):
        result = find_filing(FakeClient(), CIK, form="10-K")
        self.assertEqual(result["accession"], "0000320193-25-000079")

    def test_find_missing(self):
        with self.assertRaises(NotFoundError):
            find_filing(FakeClient(), CIK, accession="0000000000-00-000000")

    def test_documents(self):
        result = filing_documents(FakeClient(), CIK, "0000320193-25-000079")
        self.assertEqual(result["primary_document"], "aapl-20250927.htm")
        self.assertEqual(len(result["documents"]), 2)
        self.assertIn("Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm", result["documents"][0]["url"])


if __name__ == "__main__":
    unittest.main()
