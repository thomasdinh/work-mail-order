from __future__ import annotations

import logging
from typing import Optional

from work_mail_order.adapters.gmail.gmail_client import GmailClient
from work_mail_order.application.ports.message_source import Message, MessageSource

logger = logging.getLogger(__name__)


class GmailMessageSource(MessageSource):
    def __init__(self, gmail_client: Optional[GmailClient] = None):
        super().__init__(service_type="email", service_name="gmail")
        self.gmail_client = gmail_client or GmailClient()

    def get_message(self, message_id: str) -> Optional[Message]:
        try:
            raw = self.gmail_client.get_message(message_id)
        except Exception:
            logger.exception("Failed to fetch message %s", message_id)
            return None

        # translation happens HERE, once -- the use case never sees EmailMessage
        return Message(
            id=raw.id,
            source=self.service_name,
            sender=raw.sender,
            subject=raw.subject,
            body=raw.body,
            received_at=raw.date,
        )

    def list_new_message_ids(self, max_results: int = 20) -> list[str]:
        return self.gmail_client.list_message_ids(max_results=max_results)

if __name__ == "__main__":
    source = GmailMessageSource()
    recent = source.gmail_client.get_messages(max_results=20)
    for msg in recent:
        print(f"[{msg.date}] {msg.sender} -> {msg.subject}")
        print(f"  {msg.snippet}\n")  