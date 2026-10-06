"""Form 8825 line definitions (Rev. December 2025).

Single source of truth for which line code maps to which JSON key. Everything
else (layout, validation, DB, UI) is driven from these tables so adding a line
or supporting a new revision means editing one file.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineDef:
    code: str        # line number as printed on the form ("2a", "14", ...)
    key: str         # key used in the JSON output
    section: str     # income | expense | total | reserved | summary
    label: str       # human readable label (UI)


# Per-property grid, lines 2a-19, in the order they appear on the form.
PROPERTY_LINES: list[LineDef] = [
    LineDef("2a", "gross_rents", "income", "Gross rents"),
    LineDef("2b", "other_income", "income", "Other income related to rental activity"),
    LineDef("2c", "total_rental_income", "total", "Total rental real estate income (2a + 2b)"),
    LineDef("3", "advertising", "expense", "Advertising"),
    LineDef("4", "auto_travel", "expense", "Auto and travel"),
    LineDef("5", "cleaning_maintenance", "expense", "Cleaning and maintenance"),
    LineDef("6", "commissions", "expense", "Commissions"),
    LineDef("7", "insurance", "expense", "Insurance"),
    LineDef("8", "interest", "expense", "Interest"),
    LineDef("9", "legal_professional", "expense", "Legal and other professional fees"),
    LineDef("10", "real_estate_taxes", "expense", "Real estate taxes"),
    LineDef("11", "repairs", "expense", "Repairs"),
    LineDef("12", "utilities", "expense", "Utilities"),
    LineDef("13", "wages_salaries", "expense", "Wages and salaries"),
    LineDef("14", "depreciation", "expense", "Depreciation"),
    LineDef("15", "reserved_15", "reserved", "Reserved for future use"),
    LineDef("16", "reserved_16", "reserved", "Reserved for future use"),
    LineDef("17", "other_deductions", "expense", "Other deductions"),
    LineDef("18", "total_expenses", "total", "Total expenses (lines 3 through 17)"),
    LineDef("19", "net_income", "total", "Income or (loss) (2c - 18)"),
]

# Form-level lines 20a-23 (page 1 only, single amount column).
SUMMARY_LINES: list[LineDef] = [
    LineDef("20a", "total_rental_income_all", "summary", "Total rental real estate income (all properties)"),
    LineDef("20b", "total_expenses_all", "summary", "Total rental real estate expenses (all properties)"),
    LineDef("21", "net_gain_form_4797", "summary", "Net gain (loss) from Form 4797, Part II, line 17"),
    LineDef("22a", "net_income_passthrough", "summary", "Net income (loss) from partnerships, estates, trusts"),
    LineDef("23", "net_rental_real_estate_income", "summary", "Net rental real estate income (loss)"),
]

LINES_BY_CODE = {d.code: d for d in PROPERTY_LINES + SUMMARY_LINES}
INCOME_LINES = [d for d in PROPERTY_LINES if d.section == "income"]
EXPENSE_LINES = [d for d in PROPERTY_LINES if d.section == "expense"]
RESERVED_LINES = [d for d in PROPERTY_LINES if d.section == "reserved"]

# The three per-property totals and the JSON keys used for them.
TOTAL_INCOME, TOTAL_EXPENSES, NET_INCOME = "2c", "18", "19"
