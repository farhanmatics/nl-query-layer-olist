import json
import logging
import requests
from datetime import datetime
from config import settings

logger = logging.getLogger(__name__)


async def process_question(question: str):
    """
    Main orchestration pipeline:
    1. Build system prompt with tool schemas
    2. Call Ollama to get tool name + args
    3. Validate arguments
    4. Execute parameterized query
    5. Format answer with Ollama
    6. Return structured response
    """
    try:
        logger.info(f"Starting orchestration for: {question}")

        from functions.registry import get_all_schemas

        tool_schemas = get_all_schemas()
        system_prompt = build_system_prompt(tool_schemas)

        tool_call = await call_llm_for_tool(question, system_prompt)
        logger.info(f"LLM selected tool: {tool_call.get('tool')}")

        if not tool_call or "error" in tool_call:
            return {
                "error": tool_call.get("error", "Failed to parse LLM response"),
                "operation": None,
                "filters": None,
                "result": None,
                "formatted_answer": None,
                "source": None,
            }

        tool_name = tool_call.get("tool")
        args = tool_call.get("args", {})

        result = await dispatch_function(tool_name, args)

        if "error" in result:
            return {
                "error": result.get("error"),
                "operation": tool_name,
                "filters": result.get("filters"),
                "result": None,
                "formatted_answer": None,
                "source": None,
            }

        formatted_answer = await format_answer(tool_name, result)

        return {
            "operation": tool_name,
            "filters": result.get("filters"),
            "result": {k: v for k, v in result.items() if k != "filters"},
            "formatted_answer": formatted_answer,
            "source": get_source_citation(tool_name),
            "error": None,
        }

    except Exception as e:
        logger.error(f"Orchestration failed: {e}", exc_info=True)
        return {
            "error": str(e),
            "operation": None,
            "filters": None,
            "result": None,
            "formatted_answer": None,
            "source": None,
        }


def build_system_prompt(tool_schemas: list[dict]) -> str:
    """Build the system prompt for the LLM with tool definitions"""
    schema_json = json.dumps(tool_schemas, indent=2)
    return f"""You are a helpful assistant that translates natural language questions into structured function calls.

You have access to the following tools:

{schema_json}

When given a question, respond with ONLY a valid JSON object in this format:
{{
  "tool": "<tool_name>",
  "args": {{
    "arg1": "value1",
    "arg2": "value2"
  }}
}}

Never respond with anything other than valid JSON. If you cannot determine the right tool, respond with:
{{"error": "Unable to understand the question or map to available tools"}}

For date ranges, use these tokens: 'today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'this_year', 'last_year'.
For cities, normalize to Portuguese lowercase (e.g., 'sao paulo', 'rio de janeiro').
For states, use Brazilian state codes (e.g., 'SP', 'RJ', 'MG').
"""


async def call_llm_for_tool(question: str, system_prompt: str) -> dict:
    """Call Ollama to translate question into a tool call"""
    try:
        payload = {
            "model": settings.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "stream": False,
            "format": "json",
        }

        response = requests.post(
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()

        result = response.json()
        content = result.get("message", {}).get("content", "")

        tool_call = json.loads(content)
        return tool_call

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM JSON response: {e}")
        return {"error": "LLM returned invalid JSON"}
    except requests.RequestException as e:
        logger.error(f"LLM request failed: {e}")
        return {"error": f"LLM service error: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error calling LLM: {e}")
        return {"error": str(e)}


async def dispatch_function(tool_name: str, args: dict) -> dict:
    """Dispatch to a specific function handler."""
    try:
        from functions.registry import get_function

        func_info = get_function(tool_name)
        execute_fn = func_info["execute"]

        result = await execute_fn(**args)
        return result

    except KeyError as e:
        logger.error(f"Unknown tool: {tool_name}")
        return {"error": f"Unknown tool: {tool_name}"}
    except TypeError as e:
        logger.error(f"Invalid arguments for {tool_name}: {e}")
        return {"error": f"Invalid arguments: {str(e)}"}
    except Exception as e:
        logger.error(f"Function execution failed: {e}", exc_info=True)
        return {"error": f"Function failed: {str(e)}"}


async def format_answer(tool_name: str, result: dict) -> str:
    """Format the result into a natural language answer using the LLM (Phase 1)."""
    if "error" in result:
        return result["error"]

    if tool_name == "get_order_status":
        status = result.get("order_status", "unknown")
        city = result.get("customer_city", "unknown")
        return f"Order {result.get('order_id')} is {status} for {city}."

    elif tool_name == "count_orders":
        count = result.get("count", 0)
        filters = result.get("filters", {})
        filter_str = " ".join(f"{k}: {v}" for k, v in filters.items() if v)
        if filter_str:
            return f"There were {count:,} orders ({filter_str})."
        return f"There were {count:,} orders."

    return "Query executed successfully."


def get_source_citation(tool_name: str) -> str:
    """Return the source citation for a query."""
    citations = {
        "get_order_status": "olist_orders_dataset JOIN olist_customers_dataset",
        "count_orders": "olist_orders_dataset JOIN olist_customers_dataset",
    }
    return citations.get(tool_name, "olist_orders_dataset")
