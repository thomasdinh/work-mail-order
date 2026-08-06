from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr

from .models import OrderType


class ManualOrderIn(BaseModel):
    person_name: str
    person_email: EmailStr
    order_type: OrderType
    company_name: str | None = None  # required if order_type == company
    description: str | None = None
    amount: float
    currency: str = "EUR"
    order_date: datetime | None = None
    created_by: str  # which support agent entered this


class ClassifyEmailIn(BaseModel):
    subject: str
    body: str


class ClassifyEmailOut(BaseModel):
    category: str
    matched_keywords: list[str]


class BillingRequest(BaseModel):
    window_start: datetime
    window_end: datetime
    order_type: OrderType | None = None
    include_needs_review: bool = False


class InvoiceLine(BaseModel):
    order_id: int
    description: str | None
    amount: float
    currency: str
    order_date: datetime


class PersonInvoiceOut(BaseModel):
    person_name: str
    person_email: str
    order_type: OrderType
    company_name: str | None
    currency: str
    total: float
    orders: list[InvoiceLine]
