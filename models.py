"""
Database models for the order tracking / billing tool.

Design notes:
- OrderType distinguishes private (billed to an individual) vs company
  (billed to an organization the person belongs to) orders.
- Orders can arrive from two sources: parsed automatically from an
  incoming email (source="email", email_id set) or entered by hand by
  a support agent (source="manual", created_by set).
- Amount is stored in cents (integer) to avoid floating point issues
  with money. currency is a 3-letter ISO code.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class OrderType(str, enum.Enum):
    private = "private"
    company = "company"


class OrderStatus(str, enum.Enum):
    pending = "pending"          # captured, not yet billed
    invoiced = "invoiced"        # included in a billing run
    paid = "paid"
    cancelled = "cancelled"


class OrderSource(str, enum.Enum):
    email = "email"
    manual = "manual"


class Person(Base):
    """A customer or employee who places orders."""

    __tablename__ = "people"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)

    company = relationship("Company", back_populates="people")
    orders = relationship("Order", back_populates="person")


class Company(Base):
    """An organization. Orders tagged 'company' are billed to this entity,
    but still tracked per-person so you know who ordered what."""

    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    billing_email = Column(String(255), nullable=True)
    domain = Column(String(255), nullable=True, index=True)  # e.g. "acme.com"
    # used to auto-detect company orders by sender/recipient domain

    people = relationship("Person", back_populates="company")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("people.id"), nullable=False)

    order_type = Column(Enum(OrderType), nullable=False, default=OrderType.private)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    # company_id is set when order_type == company

    description = Column(Text, nullable=True)
    amount_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String(3), nullable=False, default="EUR")

    order_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)

    source = Column(Enum(OrderSource), nullable=False, default=OrderSource.manual)
    email_id = Column(String(255), nullable=True, index=True)  # Gmail message id
    created_by = Column(String(255), nullable=True)  # support agent, for manual entries
    created_at = Column(DateTime, server_default=func.now())

    # If this order was auto-extracted from an email, extraction may be
    # uncertain (amount not found, ambiguous type, etc). Flag it so a
    # human can review before it's included in a billing run.
    needs_review = Column(Integer, nullable=False, default=0)  # 0/1 as bool

    person = relationship("Person", back_populates="orders")
    company = relationship("Company")

    @property
    def amount(self) -> float:
        return self.amount_cents / 100

    @amount.setter
    def amount(self, value: float) -> None:
        self.amount_cents = round(value * 100)


class BillingRun(Base):
    """Record of a billing run so you can see what was already invoiced
    and avoid double-billing the same orders."""

    __tablename__ = "billing_runs"

    id = Column(Integer, primary_key=True)
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    order_type_filter = Column(Enum(OrderType), nullable=True)  # null = both
    created_at = Column(DateTime, server_default=func.now())
    created_by = Column(String(255), nullable=True)
    total_amount_cents = Column(Integer, nullable=False, default=0)
    notes = Column(Text, nullable=True)
