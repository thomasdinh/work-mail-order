# work-mail-order
# Gmail MCP Server

An MCP (Model Context Protocol) server that lets an AI client (Claude Desktop,
Claude Code, etc.) read your Gmail inbox — list folders, list recent emails,
search, and fetch full email content.

It connects over **IMAP** using a **Gmail App Password**, so there's no
Google Cloud project or OAuth consent screen to set up.

## 1. Set up a Gmail App Password

1. Turn on 2-Step Verification on your Google account, if not already on:
   https://myaccount.google.com/security
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password (name it e.g. "MCP Server") and copy the
   16-character code. This is what you'll use as `EMAIL_APP_PASSWORD` —
   **not** your regular Google password.
4. Make sure IMAP is enabled: Gmail → Settings → "See all settings" →
   "Forwarding and POP/IMAP" → Enable IMAP.

(Works with any IMAP mailbox, not just Gmail — just set `IMAP_HOST`
accordingly, e.g. `imap.mail.yahoo.com` or `outlook.office365.com`.)

## 2. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> Note: `pip install mcp` alone may pull a newer major version (2.x) of the
> SDK with a different API. `requirements.txt` pins `mcp<2.0.0`, which is
> the version this server is written against.

## 3. Configure credentials

Set these environment variables (however you normally do — a `.env` file
with `python-dotenv`, your shell profile, or your MCP client's config):

| Variable              | Required | Description                              |
|-----------------------|----------|-------------------------------------------|
| `EMAIL_ADDRESS`       | yes      | your mailbox address, e.g. `me@gmail.com` |
| `EMAIL_APP_PASSWORD`  | yes      | the 16-char app password from step 1      |
| `IMAP_HOST`           | no       | defaults to `imap.gmail.com`              |
| `IMAP_PORT`           | no       | defaults to `993`                         |

## 4. Run it standalone (sanity check)

```bash
EMAIL_ADDRESS=me@gmail.com EMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx python3 gmail_mcp_server.py
```

It should sit and wait, communicating over stdio — that's normal for an
MCP server; it's meant to be launched by an MCP client, not used directly
in a terminal.

## 5. Connect it to Claude Desktop

Add this to your `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gmail": {
      "command": "/absolute/path/to/venv/bin/python3",
      "args": ["/absolute/path/to/gmail_mcp_server.py"],
      "env": {
        "EMAIL_ADDRESS": "me@gmail.com",
        "EMAIL_APP_PASSWORD": "xxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Restart Claude Desktop. You should see a 🔨 tools icon showing the four
tools below available in chat.

## Tools exposed

| Tool | Description |
|---|---|
| `list_folders()` | List available mail folders/labels (INBOX, Sent, etc.) |
| `list_recent_emails(folder="INBOX", limit=10)` | Most recent emails, headers only |
| `search_emails(query, from_address, subject, folder, since, before, limit)` | Filtered search |
| `get_email(email_id, folder="INBOX")` | Full body + attachment list for one email |

Typical flow: call `list_recent_emails` or `search_emails` to get an `id`,
then call `get_email(id)` to read the full message.

## Security notes

- The app password only grants mail access, but treat it like a real
  credential — don't commit it, don't hardcode it in the script.
- This server opens a **read-only** IMAP session (`readonly=True` on
  select) — it cannot delete, send, or modify email, only read it.
- If you want the AI to also **send** email, that's a separate,
  higher-risk tool (SMTP) intentionally not included here — happy to add
  it as an explicit, separately-confirmed tool if you want it.