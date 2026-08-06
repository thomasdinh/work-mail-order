"""
Turns an email that was classified as EmailCategory.ORDER into a
structured Order record.

Amount and order-id extraction are heuristic (regex-based) since order
confirmation emails vary a lot in format. Anything the extractor isn't
confident about is flagged with needs_review=1 so a support agent can
check it before it's included in a billing run, rather than silently
billing the wrong amount.

Private vs company detection: if the sender or recipient email domain
matches a known Company.domain in the database, the order is tagged
"company" and linked to that company. Otherwise it's "private".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from .models import Company, Order, OrderSource, OrderType, Person

# Matches amounts like "$1,234.56", "1234.56 EUR", "€99.90", "99,90 €"
AMOUNT_PATTERN = re.compile(
    r"""
    (?:(?P<symbol1>[€$£])\s?(?P<amount1>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?))
    |
    (?:(?P<amount2>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s?(?P<symbol2>[€$£]|EUR|USD|GBP))
    """,
    re.VERBOSE | re.IGNORECASE,
)

ORDER_ID_PATTERN = re.compile(
    r"(?:order|invoice|receipt)\s*#?\s*[:\-]?\s*"
    r"((?=[A-Z0-9\-]*\d)[A-Z0-9\-]{4,20})",  # must contain at least one digit
    re.IGNORECASE,
)

CURRENCY_MAP = {"€": "EUR", "$": "USD", "£": "GBP", "eur": "EUR", "usd": "USD", "gbp": "GBP"}


@dataclass
class ExtractedOrder:
    amount: float | None
    currency: str
    order_ref: str | None
    needs_review: bool
    review_reason: str | None = None


def _parse_amount_str(raw: str) -> float:
    """Normalize '1.234,56' or '1,234.56' style numbers to a float."""
    raw = raw.strip()
    if "," in raw and "." in raw:
        # whichever separator appears last is the decimal separator
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # ambiguous: "1,234" (thousands) vs "12,34" (decimal). Assume
        # decimal only if exactly 2 digits follow the comma.
        if re.match(r"^\d+,\d{2}$", raw):
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    return float(raw)


def extract_order_fields(subject: str, body: str) -> ExtractedOrder:
    """Pull amount, currency, and order reference out of email text."""
    text = f"{subject}\n{body}"

    amount = None
    currency = "EUR"
    match = AMOUNT_PATTERN.search(text)
    if match:
        raw_amount = match.group("amount1") or match.group("amount2")
        symbol = match.group("symbol1") or match.group("symbol2")
        try:
            amount = _parse_amount_str(raw_amount)
        except ValueError:
            amount = None
        currency = CURRENCY_MAP.get(symbol.lower(), currency) if symbol else currency

    order_ref = None
    id_match = ORDER_ID_PATTERN.search(text)
    if id_match:
        order_ref = id_match.group(1)

    needs_review = amount is None
    reason = "Could not find an amount in the email body" if needs_review else None

    return ExtractedOrder(
        amount=amount,
        currency=currency,
        order_ref=order_ref,
        needs_review=needs_review,
        review_reason=reason,
    )


def _domain_of(email: str) -> str:
    return email.split("@")[-1].lower().strip() if "@" in email else ""


def get_or_create_person(session: Session, name: str, email: str) -> Person:
    person = session.query(Person).filter_by(email=email).one_or_none()
    if person:
        return person
    person = Person(name=name or email, email=email)
    session.add(person)
    session.flush()
    return person


def detect_company(session: Session, sender_email: str, recipient_email: str) -> Company | None:
    """Look up a Company by matching sender/recipient domain against
    known company domains."""
    for email in (sender_email, recipient_email):
        domain = _domain_of(email)
        if not domain:
            continue
        company = session.query(Company).filter_by(domain=domain).one_or_none()
        if company:
            return company
    return None


def build_order_from_email(
    session: Session,
    *,
    email_id: str,
    subject: str,
    body: str,
    sender_email: str,
    sender_name: str,
    recipient_email: str,
    order_date: datetime | None = None,
) -> Order:
    """Create (but don't commit) an Order from a classified order email."""
    extracted = extract_order_fields(subject, body)
    person = get_or_create_person(session, sender_name, sender_email)
    company = detect_company(session, sender_email, recipient_email)

    order = Order(
        person_id=person.id,
        order_type=OrderType.company if company else OrderType.private,
        company_id=company.id if company else None,
        description=extracted.order_ref or subject[:255],
        currency=extracted.currency,
        order_date=order_date or datetime.utcnow(),
        source=OrderSource.email,
        email_id=email_id,
        needs_review=1 if extracted.needs_review else 0,
    )
    order.amount = extracted.amount or 0.0

    session.add(order)
    return order
