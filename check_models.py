from dotenv import load_dotenv
from agent.llm_provider import LLMProvider

load_dotenv()

print(f"{'Model Name':<50} {'Input Limit':<15} {'Output Limit':<15}")
print("-" * 80)

try:
    for m in LLMProvider.list_models():
      if 'generateContent' in m.supported_generation_methods:
        print(f"{m.name:<50} {m.input_token_limit:<15} {m.output_token_limit:<15}")
except Exception as e:
    print(f"Error listing models: {e}")
