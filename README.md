# Order Tracking & Billing Tool

Tracks orders (from Gmail + manual entry), classifies incoming email
(order/complaint/help/reminder), tags orders as private vs company,
and bills people grouped by a chosen time window.

## Setup

    cd order_billing_tool
    pip install -r requirements.txt

Point at a shared Postgres database (recommended for a team):

    export DATABASE_URL="postgresql+psycopg2://user:pass@host:5432/orders"

Or, for local testing only (not multi-user safe):

    export DATABASE_URL="sqlite:///./orders_dev.db"

## Run the API (for the support team)

    uvicorn app.api:app --reload --host 0.0.0.0 --port 8000

Docs at http://localhost:8000/docs (FastAPI auto-generates a UI to try
every endpoint).

## Register companies

Before automatic company detection works, add each company's email
domain, e.g. via a quick Python shell:

    from app.db import SessionLocal, init_db
    from app.models import Company
    init_db()
    s = SessionLocal()
    s.add(Company(name="Acme Inc", domain="acme.com", billing_email="billing@acme.com"))
    s.commit()

Any order email from/to an @acme.com address will now be auto-tagged
as a company order for Acme Inc; everything else defaults to private.

## Ingest Gmail automatically

Needs credentials.json (see gmail_client.py docstring) in this folder.

    python ingest_gmail.py --query "newer_than:1d" --max 50

Run this on a schedule (cron / Task Scheduler) to keep pulling in new
order emails. Non-order emails (complaints/help/reminders) are
classified but not turned into orders -- route those to your ticketing
system separately if you want that automated too.

## Review before billing

Orders the extractor couldn't confidently parse (e.g. no amount found)
are flagged `needs_review=1` and excluded from billing by default.
Check them via `GET /orders/needs_review` and correct/clear them first.

## Run billing

    POST /billing/preview   -- see invoices for a window without committing
    POST /billing/finalize  -- lock it in, marks those orders "invoiced"

Each person gets a separate invoice per order_type, so someone who
ordered both privately and via their company in the same window gets
two invoices, not one mixed one.

## What's still a design choice for you

- Mixed currencies per person in one window aren't auto-converted --
  flagged as "MIXED" so you handle it deliberately.
- The email keyword lists in app/email_classifier.py are a starting
  point; tune them against your real inbox traffic.
- No auth on the API yet -- add something (even basic auth behind a
  VPN) before exposing it beyond localhost.