from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from edgar.base.errors import ParseError

_WS = re.compile(r"\s+")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(element, name: str):
    if element is None:
        return None
    for child in element:
        if isinstance(child.tag, str) and _local(child.tag) == name:
            return child
    return None


def _find_all(element, name: str) -> list:
    if element is None:
        return []
    return [child for child in element if isinstance(child.tag, str) and _local(child.tag) == name]


def _text(element) -> str | None:
    if element is None:
        return None
    value = _WS.sub(" ", "".join(element.itertext())).strip()
    return value or None


def _value(element, *path: str) -> str | None:
    node = element
    for name in path:
        node = _find(node, name)
        if node is None:
            return None
    inner = _find(node, "value")
    return _text(inner if inner is not None else node)


def _bool(element, *path: str) -> bool | None:
    raw = _value(element, *path)
    if raw is None:
        raw = _text(element)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in {"true", "1", "y", "yes"}:
        return True
    if lowered in {"false", "0", "n", "no"}:
        return False
    return None


def _footnote_ids(element) -> list[str]:
    ids = []
    for node in element.iter():
        if isinstance(node.tag, str) and _local(node.tag) == "footnoteId":
            value = node.get("id")
            if value:
                ids.append(value)
    return sorted(set(ids))


def _transaction(element, is_derivative: bool) -> dict:
    amounts = _find(element, "transactionAmounts")
    post = _find(element, "postTransactionAmounts")
    ownership = _find(element, "ownershipNature")
    coding = _find(element, "transactionCoding")
    underlying = _find(element, "underlyingSecurity")
    return {
        "type": "derivative" if is_derivative else "non-derivative",
        "security": _value(element, "securityTitle"),
        "date": _value(element, "transactionDate"),
        "code": _value(coding, "transactionCode") if coding is not None else None,
        "equity_swap": _value(coding, "equitySwapInvolved") if coding is not None else None,
        "shares": _value(amounts, "transactionShares") if amounts is not None else None,
        "price": _value(amounts, "transactionPricePerShare") if amounts is not None else None,
        "acquired_disposed": (
            _value(amounts, "transactionAcquiredDisposedCode") if amounts is not None else None
        ),
        "shares_after": (
            _value(post, "sharesOwnedFollowingTransaction") if post is not None else None
        ),
        "direct_or_indirect": (
            _value(ownership, "directOrIndirectOwnership") if ownership is not None else None
        ),
        "nature_of_ownership": (
            _value(ownership, "natureOfOwnership") if ownership is not None else None
        ),
        "nature_of_transaction": _value(element, "natureOfTransaction"),
        "conversion_or_exercise_price": _value(element, "conversionOrExercisePrice"),
        "exercise_date": _value(element, "exerciseDate"),
        "expiration_date": _value(element, "expirationDate"),
        "underlying_security": _value(underlying, "underlyingSecurityTitle")
        if underlying is not None
        else None,
        "underlying_shares": _value(underlying, "underlyingSecurityShares")
        if underlying is not None
        else None,
        "footnote_ids": _footnote_ids(element),
    }


def parse_form4(content: bytes | str) -> dict:
    if isinstance(content, str):
        content = content.encode("utf-8")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ParseError("Could not parse the Form 3/4/5 XML.") from exc
    if _local(root.tag) != "ownershipDocument":
        raise ParseError("This filing is not an ownership document (Form 3/4/5).")

    issuer = _find(root, "issuer")
    owners = []
    for owner in _find_all(root, "reportingOwner"):
        identity = _find(owner, "reportingOwnerId")
        relationship = _find(owner, "reportingOwnerRelationship")
        owners.append(
            {
                "cik": _text(_find(identity, "rptOwnerCik")) if identity is not None else None,
                "name": _text(_find(identity, "rptOwnerName")) if identity is not None else None,
                "is_director": _bool(relationship, "isDirector") if relationship is not None else None,
                "is_officer": _bool(relationship, "isOfficer") if relationship is not None else None,
                "is_ten_percent_owner": _bool(relationship, "isTenPercentOwner")
                if relationship is not None
                else None,
                "is_other": _bool(relationship, "isOther") if relationship is not None else None,
                "officer_title": _value(relationship, "officerTitle")
                if relationship is not None
                else None,
                "other_text": _value(relationship, "otherText")
                if relationship is not None
                else None,
            }
        )

    transactions = []
    for table_name, is_derivative in (("nonDerivativeTable", False), ("derivativeTable", True)):
        table = _find(root, table_name)
        if table is None:
            continue
        transaction_name = "nonDerivativeTransaction" if not is_derivative else "derivativeTransaction"
        for transaction in _find_all(table, transaction_name):
            transactions.append(_transaction(transaction, is_derivative))

    footnotes = {}
    footnote_root = _find(root, "footnotes")
    for footnote in _find_all(footnote_root, "footnote"):
        footnote_id = footnote.get("id")
        if footnote_id:
            footnotes[footnote_id] = _text(footnote)

    return {
        "document_type": _text(_find(root, "documentType")),
        "period": _text(_find(root, "periodOfReport")),
        "issuer": {
            "cik": _text(_find(issuer, "issuerCik")) if issuer is not None else None,
            "name": _text(_find(issuer, "issuerName")) if issuer is not None else None,
            "ticker": _text(_find(issuer, "issuerTradingSymbol")) if issuer is not None else None,
        },
        "owners": owners,
        "transactions": transactions,
        "footnotes": footnotes,
    }
