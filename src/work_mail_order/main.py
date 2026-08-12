"""
Run with:  python -m work_mail_order.main
"""
from __future__ import annotations

import logging

from work_mail_order.bootstrap import build_fetch_new_messages_use_case


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    use_case = build_fetch_new_messages_use_case()
    messages = use_case.execute(max_results=10)

    for msg in messages:
        print(f"[{msg.received_at}] ({msg.source}) {msg.sender} -> {msg.subject}")
        print(f"  {msg.body[:60]}...\n")


if __name__ == "__main__":
    main()