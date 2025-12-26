import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    raise ValueError("Please set the GEMINI_API_KEY environment variable.")
genai.configure(api_key=api_key)

print(f"{'Model Name':<50} {'Input Limit':<15} {'Output Limit':<15}")
print("-" * 80)

for m in genai.list_models():
  if 'generateContent' in m.supported_generation_methods:
    print(f"{m.name:<50} {m.input_token_limit:<15} {m.output_token_limit:<15}")
