"""
Pulls recent Gmail messages, classifies each one, and for anything
classified as an order, extracts it into the orders table.

This is meant to run on a schedule (cron, Task Scheduler, etc.) so new
mail keeps flowing into the tool automatically. It's separate from the
API so it can run as a background job independent of who's using the
web app.

Usage:
    python ingest_gmail.py --query "newer_than:1d" --max 50
"""

from __future__ import annotations

import argparse
import re

from app.db import SessionLocal, init_db
from app.email_classifier import EmailCategory, classify_email
from app.order_extractor import build_order_from_email
from gmail_client import GmailClient  # from the earlier Gmail helper


def _extract_email_address(header_value: str) -> str:
    """'Jane Doe <jane@acme.com>' -> 'jane@acme.com'"""
    match = re.search(r"<([^>]+)>", header_value)
    return match.group(1) if match else header_value.strip()


def _extract_name(header_value: str) -> str:
    match = re.match(r"^\s*([^<]+?)\s*<", header_value)
    return match.group(1).strip() if match else header_value


def ingest(query: str, max_results: int) -> None:
    init_db()
    gmail = GmailClient()
    session = SessionLocal()

    try:
        messages = gmail.get_messages(query=query, max_results=max_results)
        print(f"Fetched {len(messages)} messages matching query={query!r}")

        for msg in messages:
            result = classify_email(msg.subject, msg.body)
            print(f"[{result.category.value:10s}] {msg.subject[:60]}")

            if result.category != EmailCategory.ORDER:
                continue  # complaints/help/reminders aren't orders --
                # route those to your ticketing flow separately if needed

            order = build_order_from_email(
                session,
                email_id=msg.id,
                subject=msg.subject,
                body=msg.body,
                sender_email=_extract_email_address(msg.sender),
                sender_name=_extract_name(msg.sender),
                recipient_email=_extract_email_address(msg.to),
            )
            flag = " (NEEDS REVIEW)" if order.needs_review else ""
            print(f"    -> order created: {order.amount} {order.currency}{flag}")

        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default="newer_than:1d", help="Gmail search query")
    parser.add_argument("--max", type=int, default=50, dest="max_results")
    args = parser.parse_args()

    ingest(args.query, args.max_results)
