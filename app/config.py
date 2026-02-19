import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash")
DATA_PATH = os.getenv("DATA_PATH", str(BASE_DIR / "data" / "restaurant.txt"))
TOP_K_CONTEXT_LINES = int(os.getenv("TOP_K_CONTEXT_LINES", "12"))

# Invoice branding configuration
RESTAURANT_NAME = os.getenv("RESTAURANT_NAME", "CloudNest Restaurant")
RESTAURANT_ADDRESS = os.getenv(
    "RESTAURANT_ADDRESS",
    "India",
)
RESTAURANT_PHONE = os.getenv("RESTAURANT_PHONE", "+91 98765 43210")
RESTAURANT_GSTIN = os.getenv("RESTAURANT_GSTIN", "29ABCDE1234F1Z5")
RESTAURANT_EMAIL = os.getenv("RESTAURANT_EMAIL", "support@cloudnest.example")
RESTAURANT_WEBSITE = os.getenv("RESTAURANT_WEBSITE", "www.cloudnest.example")
INVOICE_LOGO_PATH = os.getenv(
    "INVOICE_LOGO_PATH",
    str(BASE_DIR / "data" / "invoice_logo.png"),
).strip()
INVOICE_LOGO_WIDTH = float(os.getenv("INVOICE_LOGO_WIDTH", "42"))
INVOICE_LOGO_HEIGHT = float(os.getenv("INVOICE_LOGO_HEIGHT", "42"))
