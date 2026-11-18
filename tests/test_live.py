import json
import os
import subprocess
import sys
import unittest

from edgar.base.env import get_user_agent


def has_contact() -> bool:
    return "@" in get_user_agent()


def run(*args):
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "edgar.cli.main", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
    )
    payload = json.loads(proc.stdout)
    if not payload.get("ok"):
        raise AssertionError(f"{args} failed: {payload}")
    return payload


@unittest.skipUnless(os.environ.get("EDGAR_LIVE") == "1", "set EDGAR_LIVE=1 to run live SEC checks")
@unittest.skipUnless(has_contact(), "set a User-Agent with a contact email")
class LiveSmoke(unittest.TestCase):
    def test_end_to_end(self):
        company = run("company", "AAPL")
        self.assertEqual(company["data"]["company"]["name"], "Apple Inc.")
        accession = company["data"]["latest"]["10-K"]["accession"]

        sections = run("sections", "AAPL", accession)
        ids = [section["id"] for section in sections["data"]["sections"]]
        self.assertIn("item-7", ids)

        text = run("text", "AAPL", accession, "--section", "mda", "--max-chars", "300")
        self.assertGreater(len(text["data"]["text"]), 100)
        self.assertTrue(text["data"]["page"]["has_more"])

        facts = run(
            "facts",
            "AAPL",
            "--concept",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "--period",
            "annual",
            "--limit",
            "5",
        )
        self.assertGreaterEqual(facts["data"]["groups"][0]["total"], 5)

        proxy = run("proxy", "AAPL", "--rows", "1")
        self.assertIn("summary-compensation-table", proxy["data"]["tables"])

        search = run("search", '"artificial intelligence"', "--ticker", "AAPL", "--form", "10-K", "--limit", "2")
        self.assertGreaterEqual(len(search["data"]["hits"]), 1)

        insiders = run("insiders", "AAPL", "--limit", "1", "--parse")
        self.assertEqual(len(insiders["data"]["filings"]), 1)
        self.assertIn("insider", insiders["data"]["filings"][0])


if __name__ == "__main__":
    unittest.main()
