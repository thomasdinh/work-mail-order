"""
Rule-based email classification.

Categories: order, complaint, help, reminder, other.

This is intentionally simple (keyword/pattern matching, no ML/API calls)
so it's fast and free to run on every incoming email. It's tuned to be
easy to extend: add/adjust keywords per category, or add new categories,
without touching the matching logic.

If you later find keyword matching isn't accurate enough for some
categories, you can swap in an LLM-based classifier for just those
borderline cases while keeping this as a cheap first pass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class EmailCategory(str, Enum):
    ORDER = "order"
    COMPLAINT = "complaint"
    HELP = "help"
    REMINDER = "reminder"
    OTHER = "other"


# Keyword lists, lowercased. Word-boundary matched, so "order" won't
# match "disorder". Edit these freely to tune accuracy for your inbox.
CATEGORY_KEYWORDS: dict[EmailCategory, list[str]] = {
    EmailCategory.COMPLAINT: [
        "complaint", "complain", "unhappy", "disappointed", "refund",
        "not working", "broken", "terrible", "unacceptable", "poor service",
        "escalate", "dissatisfied", "angry", "worst", "never again",
    ],
    EmailCategory.ORDER: [
        "order confirmation", "order number", "purchase", "invoice",
        "receipt", "your order", "order #", "checkout", "payment received",
        "shipped", "shipping confirmation", "order placed",
    ],
    EmailCategory.HELP: [
        "help", "support", "how do i", "question", "issue with",
        "trouble", "can't", "cannot", "assistance", "not sure how",
        "guide me", "instructions",
    ],
    EmailCategory.REMINDER: [
        "reminder", "don't forget", "upcoming", "due soon", "expires",
        "expiring", "renew", "follow up", "following up", "just checking in",
        "deadline",
    ],
}

# Category priority when multiple match (most specific/urgent first).
# A complaint mentioning an order number should still be flagged as a
# complaint, not filed away as a routine order.
CATEGORY_PRIORITY = [
    EmailCategory.COMPLAINT,
    EmailCategory.HELP,
    EmailCategory.ORDER,
    EmailCategory.REMINDER,
]


@dataclass
class ClassificationResult:
    category: EmailCategory
    matched_keywords: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)


def _count_matches(text: str, keywords: list[str]) -> list[str]:
    matched = []
    for kw in keywords:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, text):
            matched.append(kw)
    return matched


def classify_email(subject: str, body: str) -> ClassificationResult:
    """Classify an email into one of EmailCategory based on subject+body text."""
    text = f"{subject}\n{body}".lower()

    matches: dict[EmailCategory, list[str]] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        found = _count_matches(text, keywords)
        if found:
            matches[category] = found

    if not matches:
        return ClassificationResult(category=EmailCategory.OTHER)

    # Pick by priority first, then by number of keyword hits as tiebreaker
    for category in CATEGORY_PRIORITY:
        if category in matches:
            best = category
            break
    else:
        best = max(matches, key=lambda c: len(matches[c]))

    return ClassificationResult(
        category=best,
        matched_keywords=matches[best],
        scores={c.value: len(kw) for c, kw in matches.items()},
    )
