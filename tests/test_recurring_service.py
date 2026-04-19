import sqlite3

from cwi_accountant.services.recurring_service import RecurringService


def test_expense_name_handles_dict_and_sqlite_row() -> None:
    assert RecurringService._expense_name({"description": "Monthly Hosting Invoice"}) == "Monthly Hosting Invoice"

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("create table docs(description text, document_type text)")
    conn.execute("insert into docs(description, document_type) values (?, ?)", ("", "subscription_renewal"))
    row = conn.execute("select description, document_type from docs").fetchone()

    assert RecurringService._expense_name(row) == "subscription renewal"
