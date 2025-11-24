# TradeCraftX: AI Enhancement Design and Incremental Plan

**Version:** 1.0
**Author:** Gemini Code Assist

## 1. Overview

This document outlines the design and phased implementation plan for integrating an Agentic AI framework into the `TradeCraftX` application. The goal is to enhance the application with conversational intelligence, allowing users to query their portfolio and execute strategies using natural language.

The core architectural principle is to treat the existing `TradeCraftX` business logic (e.g., `HoldingsAnalyzer`, `GTTManager`) as a set of **"Tools"** that a central AI "Agent" can use. This approach ensures modularity, security, and extensibility.

We will follow the **Perceive -> Reason -> Plan -> Act -> Interact** cycle for agent operations.

## 2. High-Level Architecture

The new components will be integrated alongside the existing structure. The user will interact with the Agent, which in turn uses the application's core logic, now exposed as tools.

```
+-----------------------------------------------------------------+
|                       TradeCraftX Application                   |
|                                                                 |
|  +---------------------+      +------------------------------+  |
|  |   menu_cli.py       |<---->|      Agentic Framework       |  |
|  | (User Interface)    |      | (New `agent/` directory)     |  |
|  +---------------------+      +-------------+----------------+  |
|                                             |                   |
|                                             v                   |
|                               +---------------------------+     |
|                               |     Agent Core (LLM)      |     |
|                               |   (Reasoning & Planning)  |     |
|                               +-------------+-------------+     |
|                                             |                   |
|         +-----------------------------------+-----------------------------------+
|         |                                   |                                   |
|         v                                   v                                   v
|  +----------------+              +----------------------+            +---------------------+
|  | Portfolio Tool |              |      GTT Tool        |            |   Strategy Tool     |
|  | (Wraps         |              | (Wraps               |            | (Wraps `core/`      |
|  | HoldingsAnalyzer)|            |  GTTManager)         |            |  strategy classes)  |
|  +----------------+              +----------------------+            +---------------------+
|         ^                                   ^                                   ^
|         |                                   |                                   |
|         +-----------------------------------+-----------------------------------+
|                                             |
|  +-----------------------------------------------------------------+
|  |                 Broker Interface (Existing)                     |
|  | (ZerodhaBroker, UpstoxBroker via BrokerFactory)                 |
|  +-----------------------------------------------------------------+
```

### Core Agent Components

1.  **Agent Core**: The "brain" of the agent, powered by an LLM (e.g., Google Gemini). It interprets user requests, reasons about them, and creates a step-by-step plan.
2.  **Tool Belt**: A collection of Python functions that serve as the agent's tools. These functions will be wrappers around your existing `core` logic.
3.  **Agent Executor**: This component receives the plan from the Agent Core and executes it by calling the appropriate tools with the correct parameters. It handles the "Act" phase.
4.  **UI Integration**: The entry point for the user to interact with the agent. Initially, this will be a new option in `menu_cli.py`.

## 3. Incremental Implementation Plan

We will follow the four milestones (MLP1-MLP4) you've defined.

### MLP1: Custom Agent Framework for Read-Only Analysis

**Goal:** Implement a minimal, custom agent that can answer a simple, read-only question. This establishes the foundational architecture.

**Use Case:** "Summarize my portfolio performance for last month."

**Tasks:**

1.  **Project Structure:**
    *   Create a new top-level directory: `agent/`.
    *   Inside `agent/`, create `core.py` (for the main agent logic), `tools.py` (for tool definitions), and `executor.py` (for the execution loop).

2.  **Create the First Tool:**
    *   In `agent/tools.py`, define a function `get_portfolio_summary(time_period: str) -> str`.
    *   This function will use the existing `HoldingsAnalyzer` to read `roi-data.csv`.
    *   It will use `pandas` to filter the data for the specified `time_period` (e.g., "last month").
    *   It will calculate key metrics (Total P&L, ROI %, best/worst performer) and return them as a structured string or JSON. This is the **Act** step.

3.  **Build the Custom Agent Core:**
    *   In `agent/core.py`, create an `Agent` class.
    *   The `Agent` will be initialized with an LLM client (e.g., from `google.generativeai`).
    *   It will have a `run(user_query: str)` method.
    *   Inside `run()`:
        *   **Perceive:** Take the `user_query`.
        *   **Reason/Plan:** Construct a prompt for the LLM. The prompt will include the user query and a description of the available tools (e.g., `get_portfolio_summary`). The prompt will ask the LLM to return the name of the tool to call and the parameters for it, formatted as a JSON object (e.g., `{"tool_name": "get_portfolio_summary", "parameters": {"time_period": "last month"}}`).

4.  **Build the Executor:**
    *   In `agent/executor.py`, create a function `execute_plan(plan: dict)`.
    *   This function will take the JSON plan from the LLM, find the corresponding tool function in `agent/tools.py`, and call it with the provided parameters.

5.  **Integrate with CLI:**
    *   In `menu_cli.py`, add a new menu option: "Ask AI Analyst".
    *   This option will prompt the user for a question, call the `agent.run()` method to get the plan, pass the plan to the `executor.execute_plan()` to get the tool's output, and finally, pass that output back to the LLM to generate a natural language summary for the user (**Interact**).

### MLP2: Add Action-Oriented Tools

**Goal:** Expand the agent's capabilities to include planning actions, such as suggesting exit strategies, without executing them.

**Use Case:** "Suggest an exit strategy for my holdings in 'RELIANCE'."

**Tasks:**

1.  **Create New "Strategy" Tools:**
    *   In `agent/tools.py`, add a new function `suggest_exit_strategy(stock_symbol: str) -> str`.
    *   This function will use logic from `HoldingsAnalyzer` and potentially new logic to determine if the stock is profitable.
    *   It will generate a suggested plan, such as "Place a GTT order with a trigger price 5% above the current LTP."
    *   Crucially, this tool **only suggests** the plan as a string; it does not place any orders.

2.  **Update Agent:**
    *   The agent's core prompt will be updated to include the description of the new `suggest_exit_strategy` tool. No other architectural changes are needed, demonstrating the design's extensibility.

### MLP3: Integrate a Robust Framework (LangChain/LlamaIndex)

**Goal:** Replace our custom agent loop with a mature framework to simplify tool management, prompt engineering, and execution. This will make adding more complex, multi-step logic easier.

**Use Case:** Refactor the existing use cases using LangChain.

**Tasks:**

1.  **Add Dependencies:** Add `langchain` and `langchain-google-genai` to `requirements.txt`.

2.  **Refactor Tools:**
    *   Modify the tool functions in `agent/tools.py` to be decorated with LangChain's `@tool` decorator. This makes them easily discoverable by the framework.

3.  **Refactor Agent Core:**
    *   Replace the custom `Agent` class in `agent/core.py`.
    *   Use LangChain's agent creation functions (e.g., `create_tool_calling_agent`) to bind the LLM, a prompt template, and the decorated tools.
    *   The complex logic of parsing LLM output and deciding which tool to call is now handled by LangChain's `AgentExecutor`.

4.  **Implement Human-in-the-Loop for Actions:**
    *   For tools that will eventually perform actions (like placing orders), we will now add a `place_gtt_order` tool.
    *   The agent will generate the plan to call this tool. The `AgentExecutor` will be configured to **stop** before executing this specific tool and return the planned action to the CLI.
    *   The CLI will then explicitly ask the user for confirmation before proceeding to execute that final step.

### MLP4: Integrate External Data Protocols (A2A/MCP)

**Goal:** Prepare `TradeCraftX` to act as a specialized agent in a larger ecosystem, capable of interacting with external data sources or other agents.

**Use Case:** "Analyze the market sentiment for 'TATAMOTORS' and then suggest an exit strategy."

**Tasks:**

1.  **Conceptual Shift:** View the entire `TradeCraftX` agent as a potential **A2A Server**. Its "skills" are the tools we have built.

2.  **MCP for External Tools:**
    *   To fetch external data like market sentiment, we will add a new tool, e.g., `get_market_sentiment(stock_symbol: str)`.
    *   Initially, this tool might use a simple web search library or a direct API call.
    *   This interaction (agent-to-API) is conceptually aligned with the **Model Context Protocol (MCP)**. The agent is using a well-defined external resource.

3.  **A2A for Agent Collaboration (Future):**
    *   Create an `agent_card.json` file in the project's `docs/` or root directory. This file will describe our `TradeCraftX` agent's capabilities (its "skills"), following the A2A specification.
    *   Expose the agent's functionality via a simple FastAPI endpoint. This endpoint would receive a request (e.g., from another A2A Client agent), translate it into a query for our LangChain agent, and return the result.
    *   This makes `TradeCraftX` an interoperable, specialist "Trading Agent" that other, more general-purpose agents can delegate tasks to.

This incremental plan provides a clear path from a simple, custom agent to a robust, framework-driven, and interoperable system, all while delivering value at each stage.

This document will now serve as our central reference. Our immediate next step will be to implement **MLP1**.

<!--
[PROMPT_SUGGESTION]Create the initial file structure and placeholder code for MLP1.[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]Write the Python code for the `get_portfolio_summary` tool as described in MLP1.[/PROMPT_SUGGESTION]
