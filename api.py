"""
FastAPI app so the whole support team can use this tool over the
network instead of each person running scripts locally.

Run with:
    uvicorn app.api:app --reload --host 0.0.0.0 --port 8000

Then e.g.:
    POST /orders/manual        -- log an order by hand
    POST /emails/classify      -- classify a chunk of email text
    POST /billing/preview      -- see what a billing run would produce
    POST /billing/finalize     -- lock it in (marks orders invoiced)
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from . import billing
from .db import get_session, init_db
from .email_classifier import classify_email
from .models import Company, Order, OrderStatus, OrderType, Person
from .schemas import (
    BillingRequest,
    ClassifyEmailIn,
    ClassifyEmailOut,
    InvoiceLine,
    ManualOrderIn,
    PersonInvoiceOut,
)

app = FastAPI(title="Order Tracking & Billing Tool")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.post("/orders/manual", response_model=dict)
def create_manual_order(payload: ManualOrderIn, session: Session = Depends(get_session)):
    person = session.query(Person).filter_by(email=payload.person_email).one_or_none()
    if not person:
        person = Person(name=payload.person_name, email=payload.person_email)
        session.add(person)
        session.flush()

    company = None
    if payload.order_type == OrderType.company:
        if not payload.company_name:
            raise HTTPException(400, "company_name is required for company orders")
        company = session.query(Company).filter_by(name=payload.company_name).one_or_none()
        if not company:
            company = Company(name=payload.company_name)
            session.add(company)
            session.flush()
        person.company_id = company.id

    order = Order(
        person_id=person.id,
        order_type=payload.order_type,
        company_id=company.id if company else None,
        description=payload.description,
        currency=payload.currency,
        order_date=payload.order_date or __import__("datetime").datetime.utcnow(),
        status=OrderStatus.pending,
        source="manual",
        created_by=payload.created_by,
    )
    order.amount = payload.amount

    session.add(order)
    session.commit()
    return {"id": order.id, "status": "created"}


@app.post("/emails/classify", response_model=ClassifyEmailOut)
def classify(payload: ClassifyEmailIn):
    result = classify_email(payload.subject, payload.body)
    return ClassifyEmailOut(
        category=result.category.value,
        matched_keywords=result.matched_keywords,
    )


@app.post("/billing/preview", response_model=list[PersonInvoiceOut])
def billing_preview(payload: BillingRequest, session: Session = Depends(get_session)):
    invoices = billing.generate_billing(
        session,
        payload.window_start,
        payload.window_end,
        order_type=payload.order_type,
        include_needs_review=payload.include_needs_review,
    )
    return [
        PersonInvoiceOut(
            person_name=inv.person_name,
            person_email=inv.person_email,
            order_type=inv.order_type,
            company_name=inv.company_name,
            currency=inv.currency,
            total=inv.total,
            orders=[
                InvoiceLine(
                    order_id=o.id,
                    description=o.description,
                    amount=o.amount,
                    currency=o.currency,
                    order_date=o.order_date,
                )
                for o in inv.orders
            ],
        )
        for inv in invoices
    ]


@app.post("/billing/finalize", response_model=dict)
def billing_finalize(
    payload: BillingRequest,
    created_by: str,
    session: Session = Depends(get_session),
):
    invoices = billing.generate_billing(
        session,
        payload.window_start,
        payload.window_end,
        order_type=payload.order_type,
        include_needs_review=payload.include_needs_review,
    )
    run = billing.finalize_billing_run(
        session,
        payload.window_start,
        payload.window_end,
        invoices,
        order_type_filter=payload.order_type,
        created_by=created_by,
    )
    return {
        "billing_run_id": run.id,
        "invoices_count": len(invoices),
        "total_amount": run.total_amount_cents / 100,
    }


@app.get("/orders/needs_review", response_model=list[dict])
def orders_needing_review(session: Session = Depends(get_session)):
    orders = session.query(Order).filter(Order.needs_review == 1).all()
    return [
        {
            "id": o.id,
            "person_id": o.person_id,
            "description": o.description,
            "amount": o.amount,
            "email_id": o.email_id,
        }
        for o in orders
    ]
