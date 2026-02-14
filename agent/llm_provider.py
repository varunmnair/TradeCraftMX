import os
from google import genai
from typing import Optional

class LLMProvider:
    _client: Optional[genai.Client] = None

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable not set.")
            cls._client = genai.Client(api_key=api_key)
        return cls._client

    @classmethod
    def get_model(cls, model_name: str = "gemini-2.5-flash-preview-09-2025"):
        client = cls._get_client()
        return _ModelAdapter(client, model_name)

    @classmethod
    def list_models(cls):
        client = cls._get_client()
        return client.models.list()

class _ModelAdapter:
    def __init__(self, client: genai.Client, model_name: str):
        self.client = client
        self.model_name = model_name

    def generate_content(self, contents, config=None):
        return self.client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config
        )