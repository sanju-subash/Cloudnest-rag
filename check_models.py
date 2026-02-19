import os

from google import genai

api_key = os.getenv("GEMINI_API_KEY", "").strip()

if not api_key:
    print("ERROR: GEMINI_API_KEY is not set in environment.")
    raise SystemExit(1)

client = genai.Client(api_key=api_key)

print("Checking available models:")
try:
    found = False
    for model in client.models.list():
        found = True
        print(f"FOUND: {model.name}")
    if not found:
        print("No models visible for this API key.")
except Exception as exc:
    print(f"ERROR: {exc}")
