# adapters/sources/gmail_message_source.py
import logging
from typing import Optional

from googleapiclient.errors import HttpError

from gmail_client import GmailClient, EmailMessage
from message_source import MessageSource


logger = logging.getLogger(__name__)


class GmailMessageSource(MessageSource):
    def __init__(self, gmail_client: Optional[GmailClient] = None):
        super().__init__(service_type="email", service_name="gmail")
        # lazy construction — avoids the shared-default-instance bug
        self.gmail_client = gmail_client or GmailClient()

    def get_message(self, message_id: str, user_email: str = "me") -> EmailMessage:
        try:
            return self.gmail_client.get_message(message_id, user_email=user_email)
        except HttpError as e:
            logger.error(f"Failed to fetch message {message_id}: {e}")
            return None

    def list_new_message_ids(self, max_results: int = 20) -> list[str]:
        return self.gmail_client.list_message_ids(max_results=max_results)


if __name__ == "__main__":
    source = GmailMessageSource()
    recent = source.gmail_client.get_messages(max_results=10)
    for msg in recent:
            print(f"[{msg.date}] {msg.sender} -> {msg.subject}")
            print(f"  {msg.snippet}\n")