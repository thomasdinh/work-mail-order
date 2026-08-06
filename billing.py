"""
Billing: group orders by person within a chosen time window, and
generate invoice-ready summaries. Private and company orders are kept
separate, since they're billed to different entities (the individual
vs. the company).

Only orders with status=pending are billed by default, so re-running a
billing window doesn't double-charge orders that were already invoiced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from .models import BillingRun, Order, OrderStatus, OrderType, Person


@dataclass
class PersonInvoice:
    person_id: int
    person_name: str
    person_email: str
    order_type: OrderType
    company_name: str | None
    orders: list[Order] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(o.amount for o in self.orders)

    @property
    def currency(self) -> str:
        # Assumes a single currency per invoice; flag mixed-currency
        # orders for manual handling if that's not true for you.
        currencies = {o.currency for o in self.orders}
        return currencies.pop() if len(currencies) == 1 else "MIXED"


def generate_billing(
    session: Session,
    window_start: datetime,
    window_end: datetime,
    order_type: OrderType | None = None,
    include_needs_review: bool = False,
) -> list[PersonInvoice]:
    """Group pending orders in [window_start, window_end) by person.

    order_type=None bills both private and company orders (still kept
    as separate invoices per person). Pass OrderType.private or
    OrderType.company to bill only one kind.

    Orders flagged needs_review are excluded by default -- review and
    clear them first (see models.Order.needs_review) so you don't bill
    an amount the extractor wasn't confident about.
    """
    query = (
        session.query(Order)
        .filter(Order.order_date >= window_start)
        .filter(Order.order_date < window_end)
        .filter(Order.status == OrderStatus.pending)
    )
    if order_type is not None:
        query = query.filter(Order.order_type == order_type)
    if not include_needs_review:
        query = query.filter(Order.needs_review == 0)

    orders = query.all()

    # group by (person_id, order_type) so a person with both private
    # and company orders in the window gets two separate invoices
    groups: dict[tuple[int, OrderType], PersonInvoice] = {}
    for order in orders:
        key = (order.person_id, order.order_type)
        if key not in groups:
            person: Person = order.person
            groups[key] = PersonInvoice(
                person_id=person.id,
                person_name=person.name,
                person_email=person.email,
                order_type=order.order_type,
                company_name=order.company.name if order.company else None,
            )
        groups[key].orders.append(order)

    return sorted(groups.values(), key=lambda inv: (-inv.total))


def finalize_billing_run(
    session: Session,
    window_start: datetime,
    window_end: datetime,
    invoices: list[PersonInvoice],
    order_type_filter: OrderType | None = None,
    created_by: str | None = None,
) -> BillingRun:
    """Mark all billed orders as invoiced and record the run. Call this
    only after you're happy with the invoices from generate_billing()
    -- it mutates order status."""
    total_cents = 0
    for invoice in invoices:
        for order in invoice.orders:
            order.status = OrderStatus.invoiced
            total_cents += order.amount_cents

    run = BillingRun(
        window_start=window_start,
        window_end=window_end,
        order_type_filter=order_type_filter,
        created_by=created_by,
        total_amount_cents=total_cents,
    )
    session.add(run)
    session.commit()
    return run
