import asyncio
import os
import google.generativeai as genai

async def main():
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    print("Available Models:")
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(m.name)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
