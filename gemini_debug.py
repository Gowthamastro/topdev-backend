from google import genai
import os

key = os.getenv("GEMINI_API_KEY")
model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

print(f"DEBUG: Key starts with: {key[:8]}... Length: {len(key) if key else 0}")
print(f"DEBUG: Using model: {model}")

client = genai.Client(api_key=key)

try:
    response = client.models.generate_content(
        model=model,
        contents="Hello, say 'API Link OK'"
    )
    print(f"RESULT: {response.text}")
except Exception as e:
    print(f"ERROR: {e}")
