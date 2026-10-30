
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise RuntimeError("Missing GEMINI_API_KEY")

client = genai.Client(
    api_key=api_key,
    http_options=types.HttpOptions(
        timeout=60000
    )
)

# Test a lighter model without tools.
model = "gemini-3.5-flash-lite"

print(f"Testing: {model}", flush=True)
start = time.monotonic()

try:
    response = client.models.generate_content(
        model=model,
        contents="Say: ChainPilot connected successfully."
    )

    print("Response:", response.text)

except Exception as exc:
    print("ERROR TYPE:", type(exc).__name__)
    print("ERROR:", str(exc))

finally:
    print(
        f"Elapsed: {time.monotonic()-start:.1f}s"
    )
    client.close()
