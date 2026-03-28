from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def build_receipt_pdf(record, user, apparatus):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 50, "LabCab On-The-Go Borrow Receipt")

    c.setFont("Helvetica", 12)
    y = height - 90
    lines = [
        f"Transaction ID: {record.get('transaction_id')}",
        f"Borrower: {user.get('name')}",
        f"Apparatus: {apparatus.get('name')}",
        f"Quantity: {record.get('quantity')}",
        f"Date Borrowed: {record.get('borrow_date')}",
        f"Due Date: {record.get('due_date')}",
        f"Status: {record.get('status')}",
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
    ]

    for line in lines:
        c.drawString(50, y, line)
        y -= 20

    c.setFont("Helvetica-Oblique", 10)
    c.drawString(50, 50, "Please return apparatus on or before the due date.")

    c.showPage()
    c.save()

    buffer.seek(0)
    return buffer