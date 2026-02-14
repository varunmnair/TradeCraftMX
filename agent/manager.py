from agent.core import Agent
from agent.executor import execute_plan
from agent.tools import ToolRegistry

class AgentManager:
    def __init__(self, broker):
        self.agent = Agent()
        self.tool_registry = ToolRegistry(broker)

    def ask(self, user_query: str) -> str:
        """
        Handles a single user query to the AI analyst.
        """
        try:
            definitions = self.tool_registry.get_definitions()
            plan = self.agent.run(user_query, tool_definitions=definitions)
            if plan.get("error"):
                return f"❌ Error from AI: {plan['error']}"

            # The executor will now get tools from the registry
            result = execute_plan(plan, self.tool_registry)
            if isinstance(result, dict) and result.get("error"):
                return f"❌ Error executing plan: {result['error']}"

            # Pass the result back to the LLM for a natural language summary
            summary_prompt = f'''
            Based on the following data, provide a natural language summary:

            Data: {result}
            '''
            summary_response = self.agent.llm.generate_content(summary_prompt)
            return f"\n🤖 AI Analyst:\n{summary_response.text}"

        except Exception as e:
            return f"❌ An unexpected error occurred: {e}"