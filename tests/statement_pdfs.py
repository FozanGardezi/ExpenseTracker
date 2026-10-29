"""Builds statement PDFs for the tests, laid out like typical Pakistani bank and
card statements. They're synthetic: when a real statement is misread, add a
layout like it here (with personal details removed)."""

from fpdf import FPDF
from fpdf.enums import EncryptionMethod


def make_pdf(pages: list[list[tuple[float, float, str]]], password: str | None = None) -> bytes:
    """Each page is a list of (x mm, y mm, text) placements."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_font("Helvetica", size=9)
    for placements in pages:
        pdf.add_page()
        for x, y, text in placements:
            pdf.text(x, y, text)
    if password:
        pdf.set_encryption(owner_password="owner", user_password=password,
                           encryption_method=EncryptionMethod.AES_128)
    return bytes(pdf.output())


def table(rows: list[tuple[str, ...]], columns: list[float], top: float, gap: float = 5) -> list:
    """Place rows of cells at the given column x positions; cells may be "" (empty)."""
    placed = []
    for i, row in enumerate(rows):
        for x, text in zip(columns, row):
            if text:
                placed.append((x, top + i * gap, text))
    return placed


BANK_COLUMNS = [10, 32, 54, 120, 140, 165, 188]  # Txn date, value date, description, cheque, debit, credit, balance
BANK_HEADER = ("Txn Date", "Value Date", "Description", "Cheque No", "Debit", "Credit", "Balance")


def bank_statement(password: str | None = None) -> bytes:
    intro = [
        (10, 15, "MEEZAN BANK LIMITED - ACCOUNT STATEMENT"),
        (10, 22, "Statement Period: 01-Sep-2026 to 30-Sep-2026"),
        (10, 28, "Account No: 0101-0012345678"),
    ]
    page_one = intro + table([
        BANK_HEADER,
        ("01-Sep-2026", "01-Sep-2026", "Opening Balance", "", "", "", "52,000.00"),
        ("02-Sep-2026", "02-Sep-2026", "POS FOODPANDA PK", "", "1,884.99", "", "50,115.01"),
        ("03-Sep-2026", "03-Sep-2026", "IBFT TO AHMED KHAN", "", "5,000.00", "", "45,115.01"),
    ], BANK_COLUMNS, top=40) + [
        (54, 59, "REF 7712345 MOBILE APP"),  # second line of the IBFT description
    ] + table([
        ("05-Sep-2026", "05-Sep-2026", "CHEQUE PAID", "10456321", "12,000.00", "", "33,115.01"),
    ], BANK_COLUMNS, top=64)
    page_two = table([
        BANK_HEADER,
        ("25-Sep-2026", "25-Sep-2026", "SALARY ACME TECHNOLOGIES", "", "", "285,000.00", "318,115.01"),
        ("28-Sep-2026", "28-Sep-2026", "K-ELECTRIC BILL PAYMENT", "", "14,250.50", "", "303,864.51"),
        ("30-Sep-2026", "", "Closing Balance", "", "", "", "303,864.51"),
    ], BANK_COLUMNS, top=20) + [(90, 285, "Page 2 of 2")]
    return make_pdf([page_one, page_two], password)


def card_statement() -> bytes:
    columns = [10, 40, 75, 170]
    return make_pdf([[
        (10, 15, "CREDIT CARD STATEMENT"),
        (10, 22, "Statement Period 06/09/2026 - 05/10/2026"),
    ] + table([
        ("Transaction Date", "Posting Date", "Description", "Amount (PKR)"),
        ("07/09/2026", "08/09/2026", "NETFLIX.COM", "2,800.00"),
        ("12/09/2026", "13/09/2026", "PAYMENT RECEIVED - THANK YOU", "50,000.00 CR"),
        ("20/09/2026", "21/09/2026", "DARAZ.PK", "6,499.00"),
        ("25/09/2026", "25/09/2026", "REFUND DARAZ.PK", "(1,200.00)"),
    ], columns, top=35)])


def headerless_statement() -> bytes:
    lines = [
        "Balance B/F 10,000.00",
        "02 Sep POS IMTIAZ SUPER MARKET 2,500.00 7,500.00",
        "04 Sep IBFT IN ALI RAZA 3,000.00 10,500.00",
        "06 Sep ATM CASH WITHDRAWAL 5,000.00 5,500.00",
    ]
    return make_pdf([[(10, 15, "Statement from 01 Sep 2026 to 30 Sep 2026")]
                     + [(10, 30 + 6 * i, line) for i, line in enumerate(lines)]])
