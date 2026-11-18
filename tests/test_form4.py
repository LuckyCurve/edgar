import unittest

from edgar.base.errors import ParseError
from edgar.base.form4 import parse_form4

FORM4 = b"""<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport>2026-11-10</periodOfReport>
  <issuer>
    <issuerCik>0000320193</issuerCik>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001780525</rptOwnerCik>
      <rptOwnerName>Newstead Jennifer</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>false</isDirector>
      <isOfficer>true</isOfficer>
      <isTenPercentOwner>false</isTenPercentOwner>
      <officerTitle>SVP, GC and Government Affairs</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-11-10</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>200.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature>
        <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
      </ownershipNature>
      <natureOfOwnership><value>Direct</value></natureOfOwnership>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes>
    <footnote id="F1">Sold under a Rule 10b5-1 plan.</footnote>
  </footnotes>
</ownershipDocument>
"""


class Form4Tests(unittest.TestCase):
    def test_parse(self):
        result = parse_form4(FORM4)
        self.assertEqual(result["issuer"]["cik"], "0000320193")
        self.assertEqual(result["period"], "2026-11-10")
        self.assertEqual(result["owners"][0]["name"], "Newstead Jennifer")
        self.assertEqual(result["owners"][0]["officer_title"], "SVP, GC and Government Affairs")
        tx = result["transactions"][0]
        self.assertEqual(tx["security"], "Common Stock")
        self.assertEqual(tx["code"], "S")
        self.assertEqual(tx["shares"], "1000")
        self.assertEqual(tx["price"], "200.5")
        self.assertEqual(tx["acquired_disposed"], "D")
        self.assertEqual(tx["shares_after"], "5000")

    def test_bad_xml(self):
        with self.assertRaises(ParseError):
            parse_form4(b"<not xml")


if __name__ == "__main__":
    unittest.main()
