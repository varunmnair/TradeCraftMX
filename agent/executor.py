
def execute_plan(plan: dict, tool_registry):
    """
    Executes a tool call plan.

    Args:
        plan (dict): The tool call plan from the LLM.
        tool_registry: An instance of ToolRegistry.

    Returns:
        The result of the tool call.
    """
    tool_name = plan.get("tool_name")
    parameters = plan.get("parameters", {})

    if not tool_name:
        return {"error": "No tool name provided in the plan."}

    try:
        tools = tool_registry.get_tools()
        if tool_name not in tools:
            return {"error": f"Tool '{tool_name}' not found."}
        
        tool_function = tools[tool_name]
        result = tool_function(**parameters)
        return result
    except Exception as e:
        return {"error": f"Error executing tool '{tool_name}': {e}"}
