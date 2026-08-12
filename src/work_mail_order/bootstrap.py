"""
Composition root. The ONLY file allowed to import concrete adapters.
Everything else (use cases, other adapters) only ever sees the port.

To add IMAP later: write ImapMessageSource implementing MessageSource,
add one branch here. Nothing in application/ changes.
"""
from __future__ import annotations

import os

from work_mail_order.application.ports.message_source import MessageSource
from work_mail_order.application.use_cases.fetch_new_messages import FetchNewMessages


def build_message_source() -> MessageSource:
    source_type = os.getenv("MESSAGE_SOURCE", "gmail")

    if source_type == "gmail":
        from work_mail_order.adapters.gmail.gmail_message_source import GmailMessageSource
        return GmailMessageSource()

    # elif source_type == "imap":
    #     from work_mail_order.adapters.imap.imap_message_source import ImapMessageSource
    #     return ImapMessageSource()

    raise ValueError(f"Unknown MESSAGE_SOURCE: {source_type!r}")


def build_fetch_new_messages_use_case() -> FetchNewMessages:
    return FetchNewMessages(message_source=build_message_source())