from datetime import date
from decimal import Decimal

import pytest

from cwi_accountant.models import ProposedExpenseEntry


def test_amount_parsing_from_string() -> None:
    entry = ProposedExpenseEntry(amount="$1,234.56")
    assert entry.amount == Decimal("1234.56")


def test_amount_negative_rejected() -> None:
    with pytest.raises(ValueError):
        ProposedExpenseEntry(amount="-5")


def test_date_and_optional_fields() -> None:
    entry = ProposedExpenseEntry(date=date(2026, 1, 31), vendor="Vendor")
    assert entry.date.isoformat() == "2026-01-31"
    assert entry.vendor == "Vendor"
