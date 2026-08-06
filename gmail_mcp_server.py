"""
Gmail MCP Server
=================
An MCP (Model Context Protocol) server that retrieves emails from a Gmail
(or any IMAP-compatible) account.

Auth: Gmail App Password over IMAP (no Google Cloud project required).
Docs: https://support.google.com/accounts/answer/185833

Environment variables (set these before running, or put them in a .env
file / your MCP client's config "env" block):
    EMAIL_ADDRESS     - the mailbox to connect to, e.g. me@gmail.com
    EMAIL_APP_PASSWORD - a 16-character Gmail App Password
    IMAP_HOST         - optional, defaults to imap.gmail.com
    IMAP_PORT         - optional, defaults to 993

Tools exposed:
    list_folders        - list available mail folders/labels
    list_recent_emails   - list the N most recent emails in a folder
    search_emails        - search emails by sender/subject/date/keyword
    get_email             - fetch full content (headers + body) of one email
"""

import os
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

mcp = FastMCP("gmail-email-server")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect() -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP connection."""
    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        raise RuntimeError(
            "Missing credentials. Set the EMAIL_ADDRESS and "
            "EMAIL_APP_PASSWORD environment variables (use a Gmail "
            "App Password, not your normal password)."
        )
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(EMAIL_ADDRESS, EMAIL_APP_PASSWORD)
    return conn


def _decode(value: str | None) -> str:
    """Decode a MIME-encoded email header into a plain string."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _get_body(msg: email.message.Message) -> str:
    """Extract the best-effort plain-text body from an email message."""
    if msg.is_multipart():
        # Prefer text/plain; fall back to text/html (stripped) if needed.
        plain, html = None, None
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            if content_type == "text/plain" and plain is None:
                plain = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                plain = plain.decode(charset, errors="replace")
            elif content_type == "text/html" and html is None:
                html = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                html = html.decode(charset, errors="replace")
        if plain:
            return plain
        if html:
            return html
        return ""
    else:
        payload = msg.get_payload(decode=True)
        if payload is None:
            return msg.get_payload() or ""
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")


def _list_attachments(msg: email.message.Message) -> list[str]:
    names = []
    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                filename = part.get_filename()
                if filename:
                    names.append(_decode(filename))
    return names


def _summarize_message(uid: bytes, raw_headers: bytes) -> dict[str, Any]:
    msg = email.message_from_bytes(raw_headers)
    date_str = msg.get("Date")
    try:
        parsed_date = parsedate_to_datetime(date_str).isoformat() if date_str else None
    except Exception:
        parsed_date = date_str
    return {
        "id": uid.decode(),
        "from": _decode(msg.get("From")),
        "to": _decode(msg.get("To")),
        "subject": _decode(msg.get("Subject")),
        "date": parsed_date,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def list_folders() -> list[str]:
    """List all mail folders/labels available in the mailbox (e.g. INBOX,
    [Gmail]/Sent Mail, [Gmail]/All Mail, [Gmail]/Trash)."""
    conn = _connect()
    try:
        status, folders = conn.list()
        if status != "OK":
            raise RuntimeError(f"Failed to list folders: {status}")
        result = []
        for f in folders:
            # Typical line: b'(\\HasNoChildren) "/" "INBOX"'
            decoded = f.decode(errors="replace")
            name = decoded.split('"')[-2] if '"' in decoded else decoded
            result.append(name)
        return result
    finally:
        conn.logout()


@mcp.tool()
def list_recent_emails(folder: str = "INBOX", limit: int = 10) -> list[dict[str, Any]]:
    """List the most recent emails in a folder.

    Args:
        folder: mailbox/folder name, e.g. "INBOX" or "[Gmail]/Sent Mail".
        limit: maximum number of emails to return (most recent first).

    Returns:
        A list of email summaries: id, from, to, subject, date.
        Use get_email(id) to fetch the full body.
    """
    conn = _connect()
    try:
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open folder '{folder}'")

        status, data = conn.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("IMAP search failed")

        all_ids = data[0].split()
        selected_ids = list(reversed(all_ids))[:limit]  # most recent first

        results = []
        for uid in selected_ids:
            status, msg_data = conn.fetch(
                uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])"
            )
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw_headers = msg_data[0][1]
            results.append(_summarize_message(uid, raw_headers))
        return results
    finally:
        conn.logout()


@mcp.tool()
def search_emails(
    query: str = "",
    from_address: str = "",
    subject: str = "",
    folder: str = "INBOX",
    since: str = "",
    before: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search emails using one or more filters (all filters are combined
    with AND). Leave a field empty to skip that filter.

    Args:
        query: free-text keyword to search in the email body/subject.
        from_address: filter by sender address, e.g. "boss@company.com".
        subject: filter by text contained in the subject line.
        folder: mailbox/folder to search, e.g. "INBOX" or "[Gmail]/All Mail".
        since: only emails on/after this date, format "DD-Mon-YYYY" e.g. "01-Jan-2026".
        before: only emails before this date, format "DD-Mon-YYYY".
        limit: maximum number of results to return (most recent first).

    Returns:
        A list of matching email summaries: id, from, to, subject, date.
    """
    conn = _connect()
    try:
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open folder '{folder}'")

        criteria = []
        if query:
            criteria += ["TEXT", f'"{query}"']
        if from_address:
            criteria += ["FROM", f'"{from_address}"']
        if subject:
            criteria += ["SUBJECT", f'"{subject}"']
        if since:
            criteria += ["SINCE", since]
        if before:
            criteria += ["BEFORE", before]
        if not criteria:
            criteria = ["ALL"]

        status, data = conn.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("IMAP search failed - check filter formats")

        all_ids = data[0].split()
        selected_ids = list(reversed(all_ids))[:limit]

        results = []
        for uid in selected_ids:
            status, msg_data = conn.fetch(
                uid, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])"
            )
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw_headers = msg_data[0][1]
            results.append(_summarize_message(uid, raw_headers))
        return results
    finally:
        conn.logout()


@mcp.tool()
def get_email(email_id: str, folder: str = "INBOX") -> dict[str, Any]:
    """Fetch the full content of a single email, including its body text
    and a list of attachment filenames (if any).

    Args:
        email_id: the email's id, as returned by list_recent_emails or
            search_emails.
        folder: the folder the email lives in (must match the folder it
            was found in).

    Returns:
        A dict with from, to, cc, subject, date, body, attachments.
    """
    conn = _connect()
    try:
        status, _ = conn.select(folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Could not open folder '{folder}'")

        status, msg_data = conn.fetch(email_id.encode(), "(RFC822)")
        if status != "OK" or not msg_data or msg_data[0] is None:
            raise RuntimeError(f"Email with id '{email_id}' not found in '{folder}'")

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        date_str = msg.get("Date")
        try:
            parsed_date = parsedate_to_datetime(date_str).isoformat() if date_str else None
        except Exception:
            parsed_date = date_str

        return {
            "id": email_id,
            "from": _decode(msg.get("From")),
            "to": _decode(msg.get("To")),
            "cc": _decode(msg.get("Cc")),
            "subject": _decode(msg.get("Subject")),
            "date": parsed_date,
            "body": _get_body(msg),
            "attachments": _list_attachments(msg),
        }
    finally:
        conn.logout()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")