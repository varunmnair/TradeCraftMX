from abc import ABC, abstractmethod
from agent.llm_provider import LLMProvider

class BaseAgent(ABC):
    def __init__(self, model_name: str):
        self.llm = LLMProvider.get_model(model_name)

    @abstractmethod
    def run(self, *args, **kwargs):
        pass
