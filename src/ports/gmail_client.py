"""
Gmail API client for reading, analyzing, and sending email.

Setup:
    pip install google-auth google-auth-oauthlib google-api-python-client

    1. Enable the Gmail API in Google Cloud Console and download
       `credentials.json` (OAuth client ID, "Desktop app" type).
    2. Put credentials.json next to this file (or pass a custom path).
    3. Run once interactively so the OAuth browser flow can complete
       and write token.json.

Scopes:
    - gmail.readonly / gmail.modify: read, label, archive, delete
    - gmail.send: send mail
    - gmail.modify does NOT include sending. If you need both read/modify
      and send, either request both scopes together or use the full
      "https://mail.google.com/" scope.
    NOTE: If you ever change SCOPES, delete token.json and re-authenticate,
    otherwise you'll get an insufficient-scope error.
"""

from __future__ import annotations

import base64
import logging
import os.path
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


@dataclass
class EmailMessage:
    """A parsed, human-readable view of a Gmail message."""
    id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    snippet: str
    body: str
    labels: list[str]


class GmailClient:
    """Wraps the Gmail API for reading, analysis, and sending."""

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
        scopes: list[str] | None = None,
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes or SCOPES
        self.service = self._authenticate()

    # ---------- Auth ----------

    def _authenticate(self):
        creds = None

        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Missing {self.credentials_path}. Download it from "
                        "Google Cloud Console (OAuth client, Desktop app type)."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, self.scopes
                )
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token:
                token.write(creds.to_json())

        logger.info("Authenticated with Gmail API.")
        return build("gmail", "v1", credentials=creds)

    # ---------- Reading ----------

    def list_message_ids(
        self,
        query: str = "",
        max_results: int = 10,
        user_email: str = "me",
    ) -> list[str]:
        """Return message IDs matching an optional Gmail search query,
        transparently paging until max_results is reached."""
        ids: list[str] = []
        page_token = None

        try:
            while len(ids) < max_results:
                request_size = min(500, max_results - len(ids))
                resp = (
                    self.service.users()
                    .messages()
                    .list(
                        userId=user_email,
                        q=query or None,
                        maxResults=request_size,
                        pageToken=page_token,
                    )
                    .execute()
                )
                ids.extend(m["id"] for m in resp.get("messages", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as e:
            logger.error("Failed to list messages: %s", e)
            raise

        return ids[:max_results]

    def get_message(self, message_id: str, user_email: str = "me") -> EmailMessage:
        """Fetch and parse a single message into a readable EmailMessage."""
        try:
            raw = (
                self.service.users()
                .messages()
                .get(userId=user_email, id=message_id, format="full")
                .execute()
            )
        except HttpError as e:
            logger.error("Failed to fetch message %s: %s", message_id, e)
            raise

        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }

        return EmailMessage(
            id=raw["id"],
            thread_id=raw.get("threadId", ""),
            subject=headers.get("subject", "(no subject)"),
            sender=headers.get("from", ""),
            to=headers.get("to", ""),
            date=headers.get("date", ""),
            snippet=raw.get("snippet", ""),
            body=self._extract_body(raw.get("payload", {})),
            labels=raw.get("labelIds", []),
        )

    def get_messages(
        self, query: str = "", max_results: int = 10, user_email: str = "me"
    ) -> list[EmailMessage]:
        """Convenience: list + fetch + parse in one call."""
        ids = self.list_message_ids(query, max_results, user_email)
        return [self.get_message(mid, user_email) for mid in ids]

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        """Recursively pull the plain-text body out of a message payload."""

        def decode(data: str) -> str:
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode(
                "utf-8", errors="replace"
            )

        # Simple message: body directly on payload
        body_data = payload.get("body", {}).get("data")
        if body_data and payload.get("mimeType", "").startswith("text/"):
            return decode(body_data)

        # Multipart: walk parts, preferring text/plain
        for part in payload.get("parts", []) or []:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return decode(data)

        # Fall back to text/html or nested multipart
        for part in payload.get("parts", []) or []:
            if part.get("mimeType") == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    return decode(data)
            if part.get("mimeType", "").startswith("multipart/"):
                nested = GmailClient._extract_body(part)
                if nested:
                    return nested

        return ""

    # ---------- Sending ----------

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        user_email: str = "me",
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict[str, Any]:
        """Send a plain-text email. Requires the gmail.send scope."""
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        try:
            result = (
                self.service.users()
                .messages()
                .send(userId=user_email, body={"raw": raw})
                .execute()
            )
        except HttpError as e:
            logger.error("Failed to send message: %s", e)
            raise

        logger.info("Sent message id=%s to %s", result.get("id"), to)
        return result


if __name__ == "__main__":
    client = GmailClient()

    recent = client.get_messages(max_results=5)
    for msg in recent:
        print(f"[{msg.date}] {msg.sender} -> {msg.subject}")
        print(f"  {msg.snippet}\n")

    # Example send (uncomment to test):
    # client.send_message(
    #     to="someone@example.com",
    #     subject="Test from GmailClient",
    #     body="Hello from my new Gmail tool.",
    # )