import os
import json
import logging
import google.generativeai as genai
from agent.strategy_tools import StrategyTools

class EntryPilot:
    def __init__(self):
        self.tools = StrategyTools()
        self.llm = self._setup_llm()

    def _setup_llm(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')

    def run(self):
        print("\n🤖 EntryPilot: I'm ready to help you refine your entry strategy. (Type 'exit' to stop)")
        
        while True:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ['exit', 'quit', 'done']:
                print("🤖 EntryPilot: Goodbye!")
                break

            response = self._process_query(user_input)
            print(f"\n🤖 EntryPilot: {response}")

    def _process_query(self, user_query):
        """
        Orchestrates the Planner-Executor loop.
        """
        max_steps = 5
        step_count = 0
        
        # Initial Context
        last_observation = "Starting session. Plan loaded."

        while step_count < max_steps:
            step_count += 1
            
            # 1. Get Current Plan State
            current_plan = self.tools.get_working_plan()
            plan_summary = []
            if current_plan:
                # Summarize to save tokens
                for o in current_plan[:20]: # Limit to 20 for prompt context
                    plan_summary.append({k: o[k] for k in ['symbol', 'price', 'ltp', 'entry', 'qty'] if k in o})
            
            plan_context = json.dumps(plan_summary, indent=2) if plan_summary else "Plan is empty."
            if len(current_plan) > 20:
                plan_context += f"\n... ({len(current_plan) - 20} more orders)"

            # 2. Construct Prompt
            prompt = f"""
            You are EntryPilot, an intelligent trading orchestrator.
            
            **Goal:** "{user_query}"
            
            **Current State:**
            - Plan Summary: {self.tools.get_plan_stats()}
            - Last Observation: {last_observation}
            - Plan Data (Sample):
            ```json
            {plan_context}
            ```

            **Available Tools:**
            1. `filter_by_query(query: str)`: Filter plan using pandas query syntax (e.g., "entry == 'E1'", "price < 500", "(price - ltp)/ltp > 0.05").
            2. `undo_last_action()`: Revert to previous plan state.
            3. `reset_to_baseline()`: Reload original plan.
            4. `apply_risk_management()`: Apply risk rules.
            5. `show_plan()`: Print the current plan table to the console.
            6. `place_orders()`: Execute the plan (Final Action).

            **Instructions:**
            - Decide the NEXT step to achieve the Goal.
            - If the user asks to "place orders", you MUST use the `place_orders` tool.
            - If the user asks to "show" or "display" the plan, you MUST use the `show_plan()` tool. Do not add extra filters unless explicitly asked.
            - If the goal is met or you need user input, set "stop": true.
            - Provide a "reason" for your action.
            
            **Output JSON Schema:**
            {{
              "tool": "tool_name" or null,
              "parameters": {{ "param": "value" }} or null,
              "reason": "Why you are taking this step",
              "next_goal": "What comes after this step",
              "stop": boolean,
              "user_message": "Message to user if stopping"
            }}
            """

            # 3. Call LLM
            try:
                logging.debug(f"EntryPilot Step {step_count} Prompt Sent")
                response = self.llm.generate_content(prompt)
                text = response.text
                
                # Robust JSON Parsing
                if '```json' in text:
                    text = text.split('```json')[1].split('```')[0]
                elif '```' in text:
                    text = text.split('```')[1].split('```')[0]
                
                try:
                    plan = json.loads(text)
                except json.JSONDecodeError:
                    logging.error(f"JSON Decode Error: {text}")
                    return "Error: Could not understand AI response."

                # 4. Extract Plan
                tool_name = plan.get("tool")
                if tool_name: tool_name = tool_name.strip()
                params = plan.get("parameters") or {}
                reason = plan.get("reason", "")
                stop = plan.get("stop", False)
                user_msg = plan.get("user_message", "")

                # 5. Log Plan
                print(f"\n[Step {step_count}] Plan → Tool: {tool_name} | Reason: {reason}")

                if stop and not tool_name:
                    # If the goal is met and no tool is needed, stop here.
                    return user_msg or "Goal achieved."

                # 6. Act (Execute Tool)
                tool_result = "No tool executed."
                if tool_name == "filter_by_query":
                    tool_result = self.tools.filter_by_query(params.get("query"))
                elif tool_name == "undo_last_action":
                    tool_result = self.tools.undo_last_action()
                elif tool_name == "reset_to_baseline":
                    tool_result = self.tools.reset_to_baseline()
                elif tool_name == "apply_risk_management":
                    tool_result = self.tools.apply_risk_management()
                elif tool_name == "show_plan":
                    tool_result = self.tools.show_plan()
                elif tool_name == "place_orders":
                    tool_result = self.tools.place_orders()
                    stop = True # Force stop after placing orders
                
                # 7. Observe
                last_observation = tool_result
                print(f"[Step {step_count}] Act  → {tool_result}")
                print(f"[Step {step_count}] Obs  → {self.tools.get_plan_stats()}")

                if stop:
                    if tool_name == "place_orders":
                        return "Order placement cycle complete. See execution details above."
                    elif tool_name == "show_plan":
                        return user_msg or "Displayed plan details as requested above."
                    else:
                        return user_msg or "Final step completed."

            except Exception as e:
                logging.error(f"Loop Error: {e}")
                return f"Error in processing loop: {e}"
        
        return "Max steps reached. Please refine your request."