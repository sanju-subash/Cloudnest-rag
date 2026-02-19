from pathlib import Path
from tempfile import gettempdir

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import (
    INVOICE_LOGO_HEIGHT,
    INVOICE_LOGO_PATH,
    INVOICE_LOGO_WIDTH,
    RESTAURANT_ADDRESS,
    RESTAURANT_EMAIL,
    RESTAURANT_GSTIN,
    RESTAURANT_NAME,
    RESTAURANT_PHONE,
    RESTAURANT_WEBSITE,
)
from app.rag_engine import ask_question, get_latest_bill

app = FastAPI(title="CloudNest Restaurant Bot")

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = BASE_DIR / "index.html"
MENU_IMAGES_DIR = BASE_DIR / "data" / "menu_images"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MENU_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/menu-images", StaticFiles(directory=str(MENU_IMAGES_DIR)), name="menu-images")


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1)
    session_id: str = Field(default="default")


@app.get("/")
def home():
    if INDEX_FILE.exists():
        return FileResponse(INDEX_FILE)
    return JSONResponse(
        status_code=404,
        content={"error": "index.html not found in project root."},
    )


@app.post("/ask")
def ask(request: QuestionRequest):
    return ask_question(request.question, session_id=request.session_id)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/bill/pdf")
def bill_pdf(session_id: str):
    bill = get_latest_bill(session_id)
    if not bill:
        return JSONResponse(status_code=404, content={"error": "No generated bill found for this session."})

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return JSONResponse(
            status_code=500,
            content={"error": "Missing reportlab dependency. Run: pip install reportlab"},
        )

    bill_id = str(bill["bill_id"])
    pdf_path = Path(gettempdir()) / f"{bill_id}.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    y = height - 50

    # Header with optional logo and business details.
    logo_x = 50
    if INVOICE_LOGO_PATH and Path(INVOICE_LOGO_PATH).exists():
        try:
            c.drawImage(
                INVOICE_LOGO_PATH,
                logo_x,
                y - INVOICE_LOGO_HEIGHT + 6,
                width=INVOICE_LOGO_WIDTH,
                height=INVOICE_LOGO_HEIGHT,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    title_x = 50 + int(INVOICE_LOGO_WIDTH) + 10
    c.setFont("Helvetica-Bold", 16)
    c.drawString(title_x, y, RESTAURANT_NAME)
    y -= 16

    c.setFont("Helvetica", 10)
    c.drawString(title_x, y, RESTAURANT_ADDRESS)
    y -= 14
    c.drawString(title_x, y, f"Phone: {RESTAURANT_PHONE} | GSTIN: {RESTAURANT_GSTIN}")
    y -= 14
    c.drawString(title_x, y, f"Email: {RESTAURANT_EMAIL} | Web: {RESTAURANT_WEBSITE}")
    y -= 20

    c.setLineWidth(0.8)
    c.line(50, y, width - 50, y)
    y -= 18

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, "Tax Invoice")
    y -= 20

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Bill ID: {bill_id}")
    y -= 16
    c.drawString(50, y, f"Issued At: {bill['issued_at']}")
    y -= 16

    def ensure_space(current_y: float, min_y: float = 120) -> float:
        if current_y >= min_y:
            return current_y
        c.showPage()
        c.setFont("Helvetica", 10)
        return height - 70

    mode = str(bill.get("mode", "") or "").strip().lower()
    if mode == "dine_in":
        y = ensure_space(y)
        c.drawString(50, y, "Order Type: Dine-In")
        y -= 16
        slot = str(bill.get("slot", "") or "").strip()
        if slot:
            y = ensure_space(y)
            c.drawString(50, y, f"Dine-In Slot: {slot}")
            y -= 16
    elif mode == "delivery":
        y = ensure_space(y)
        c.drawString(50, y, "Order Type: Online Delivery")
        y -= 16
        address_lines = bill.get("address_lines")
        if not isinstance(address_lines, list):
            address = str(bill.get("address", "") or "").strip()
            if address:
                address_lines = [part.strip() for part in address.split(",") if part.strip()] or [address]
            else:
                address_lines = []

        if address_lines:
            y = ensure_space(y)
            c.drawString(50, y, "Delivery Address:")
            y -= 16
            for line in address_lines:
                y = ensure_space(y)
                c.drawString(64, y, f"- {line}")
                y -= 14

    y -= 24

    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "Item")
    c.drawString(290, y, "Qty")
    c.drawString(350, y, "Unit Price")
    c.drawString(460, y, "Total")
    y -= 14

    c.setFont("Helvetica", 10)
    for item in bill["items"]:
        if y < 120:
            c.showPage()
            y = height - 70
            c.setFont("Helvetica-Bold", 11)
            c.drawString(50, y, "Item")
            c.drawString(290, y, "Qty")
            c.drawString(350, y, "Unit Price")
            c.drawString(460, y, "Total")
            y -= 14
            c.setFont("Helvetica", 10)
        c.drawString(50, y, str(item["name"]))
        c.drawString(290, y, str(item["quantity"]))
        c.drawString(350, y, f"Rs {item['unit_price']}")
        c.drawString(460, y, f"Rs {item['line_total']}")
        y -= 14

    y -= 12
    c.setFont("Helvetica-Bold", 11)
    c.drawString(350, y, f"Subtotal: Rs {bill['subtotal']}")
    y -= 16
    c.drawString(350, y, f"GST (5%): Rs {bill['gst']}")
    y -= 16
    c.drawString(350, y, f"Total: Rs {bill['total']}")
    y -= 28

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(50, y, "Thank you for ordering with us.")
    y -= 12
    c.drawString(50, y, "This is a system-generated invoice.")

    c.showPage()
    c.save()

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{bill_id}.pdf",
    )
