"""Live SEC checks across annual reports, sections, tables, proxies and insiders."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

TICKERS = ["PDD", "DECK", "INFY", "BKE", "TME", "GGB", "GOOGL"]
ANNUAL_FORMS = ("10-K", "20-F")
REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "RevenueFromContractsWithCustomers",
    "Revenue",
    "Revenues",
    "SalesRevenueNet",
)


class Checker:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def run(self, *args: str, expect: int = 0) -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "edgar.cli.main", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            payload = {
                "ok": False,
                "error": {"code": "BAD_JSON", "message": (proc.stdout + proc.stderr)[:300]},
            }
        if proc.returncode != expect:
            raise AssertionError(f"{args}: exit {proc.returncode}, {payload}")
        return payload

    def check(self, ticker: str, name: str, fn) -> None:
        try:
            detail = fn()
            print(f"  PASS {ticker} {name}: {detail}")
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            self.failures.append(f"{ticker} {name}: {exc}")
            print(f"  FAIL {ticker} {name}: {exc}")


def main() -> int:
    checker = Checker()
    out = tempfile.mkdtemp(prefix="edgar-live-")
    os.environ.setdefault("EDGAR_CACHE_DIR", os.path.join(out, "cache"))

    for ticker in TICKERS:
        print(ticker)

        def company(t=ticker):
            payload = checker.run("company", t)
            data = payload["data"]
            annual = [form for form in ANNUAL_FORMS if form in data["latest"]]
            assert annual, f"no annual form in {list(data['latest'])}"
            return data["company"]["name"], annual[0]

        try:
            name, annual_form = company()
            print(f"  {name} {annual_form}")
        except Exception as exc:  # noqa: BLE001
            checker.failures.append(f"{ticker} company: {exc}")
            print(f"  FAIL {ticker} company: {exc}")
            continue

        def filing(t=ticker, form=annual_form):
            payload = checker.run("filing", t, "--form", form)
            return payload["data"]["filing"]

        annual = filing()
        accession = annual["accession"]
        document = annual["primary_document"]
        print(f"  {accession} {document}")

        def sections():
            payload = checker.run("sections", ticker, accession)
            ids = [section["id"] for section in payload["data"]["sections"]]
            assert ids, "no sections extracted"
            return f"{len(ids)} sections, first {ids[:3]}"

        checker.check(ticker, "sections", sections)

        def read_section(alias):
            payload = checker.run(
                "text", ticker, accession, "--section", alias, "--max-chars", "400"
            )
            text = payload["data"]["text"]
            assert len(text) > 50, f"{alias} empty"
            return f"{alias} {len(text)} chars"

        for alias in ("risk", "business", "mda"):
            checker.check(ticker, f"text:{alias}", lambda a=alias: read_section(a))

        def tables():
            payload = checker.run("tables", ticker, accession, "--limit", "5", "--rows", "2")
            found = payload["data"]["tables"]
            assert found, "no tables"
            assert "preview" in found[0] and "n_rows" in found[0]
            return f"{len(found)} tables"

        checker.check(ticker, "tables", tables)

        def facts():
            concepts = checker.run("concepts", ticker, "--query", "revenue", "--limit", "10")
            tags = [row["tag"] for row in concepts["data"]["concepts"]] + list(REVENUE_TAGS)
            for tag in dict.fromkeys(tags):
                try:
                    payload = checker.run(
                        "facts", ticker, "--concept", tag, "--period", "annual", "--limit", "5"
                    )
                except AssertionError:
                    continue
                groups = payload["data"]["groups"]
                if groups and groups[0]["facts"]:
                    return f"{tag} total={groups[0]['total']} last={groups[0]['last_end']}"
            raise AssertionError("no revenue facts")

        checker.check(ticker, "facts", facts)

        def insiders():
            payload = checker.run("insiders", ticker, "--limit", "1", "--parse")
            filing_row = payload["data"]["filings"][0]
            assert filing_row.get("insider"), "no parsed insider"
            return filing_row["form"]

        checker.check(ticker, "insiders", insiders)

        def search():
            payload = checker.run(
                "search", '"revenue"', "--ticker", ticker, "--limit", "2"
            )
            hits = payload["data"]["hits"]
            assert hits, "no hits"
            return f"{len(hits)} hits"

        checker.check(ticker, "search", search)

        def download():
            with tempfile.TemporaryDirectory() as target:
                payload = checker.run(
                    "download", ticker, accession, "--doc", document, "-o", target
                )
                files = payload["data"]["files"]
                assert files and os.path.getsize(files[0]["path"]) > 1000
                return f"{files[0]['bytes']} bytes"

        checker.check(ticker, "download", download)

        if annual_form == "10-K":

            def proxy():
                payload = checker.run("proxy", ticker, "--rows", "1")
                tables_found = payload["data"]["tables"]
                assert "summary-compensation-table" in tables_found, "no summary table"
                return f"{len(tables_found)} table sections"

            checker.check(ticker, "proxy", proxy)
        else:
            print(f"  SKIP {ticker} proxy: foreign private issuer")

    print()
    if checker.failures:
        print(f"{len(checker.failures)} failure(s):")
        for failure in checker.failures:
            print(f"  - {failure}")
        return 1
    print("ALL LIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
