import os
import json
import google.generativeai as genai

class Agent:
    def __init__(self):
        self.llm = self._setup_llm()

    def _setup_llm(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel('gemini-2.5-flash-lite-preview-06-17')

    def run(self, user_query: str) -> dict:
        """
        Runs the agent to process a user query.

        Args:
            user_query (str): The user's query.

        Returns:
            dict: The tool call plan from the LLM.
        """
        prompt = self._construct_prompt(user_query)
        response = self.llm.generate_content(prompt)
        #print(f"LLM Raw Response: {response.text}")

        try:
            json_text = response.text
            # Handle markdown code blocks
            if '```json' in json_text:
                json_text = json_text.split('```json')[1].split('```')[0]
            elif '```' in json_text:
                json_text = json_text.split('```')[1].split('```')[0]

            # Find the first '{' and the last '}' to extract the JSON object
            start = json_text.find('{')
            end = json_text.rfind('}') + 1
            if start != -1 and end != 0:
                json_text = json_text[start:end]

            plan = json.loads(json_text)
            return plan
        except (json.JSONDecodeError, TypeError, IndexError):
            # Handle cases where the LLM doesn't return valid JSON
            return {"error": "Invalid JSON response from LLM", "raw_response": response.text}

    def _construct_prompt(self, user_query: str) -> str:
        """
        Constructs the prompt for the LLM.

        Args:
            user_query (str): The user's query.

        Returns:
            str: The prompt for the LLM.
        """
        # This is a simplified tool description. In a real application, you would
        # dynamically generate this from the available tools.
        tool_description = """
        {
            "tool_name": "get_portfolio_summary",
            "description": "Analyzes the portfolio for a given time period and returns a summary.",
            "parameters": {
                "time_period": {
                    "type": "str",
                    "description": "The time period to analyze (e.g., 'last month')."
                }
            }
        }
        """

        prompt = f"""
        You are an AI agent that helps users analyze their stock portfolio.
        Based on the user's query, choose the best tool to use and return the tool name and parameters as a JSON object.

        User Query: "{user_query}"

        Available Tools:
        {tool_description}

        Respond with a JSON object in the following format:
        {{
            "tool_name": "<tool_name>",
            "parameters": {{
                "<parameter_name>": "<parameter_value>"
            }}
        }}
        """
        return prompt