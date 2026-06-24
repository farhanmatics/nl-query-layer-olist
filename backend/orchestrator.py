import json
import logging
import httpx
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
    """Build the system prompt for the LLM with tool definitions and few-shot examples."""
    schema_json = json.dumps(tool_schemas, indent=2)
    return f"""You are a data query assistant. Your ONLY job is to convert a natural language question into a single JSON function call. You must extract ALL filters mentioned in the question — never drop any.

TOOLS:
{schema_json}

OUTPUT RULES:
- Respond with ONLY valid JSON, nothing else.
- Always use the key "tool" for the function name and "args" for its arguments.
- Only include args that are explicitly mentioned in the question.
- If you cannot map to a tool, respond: {{"error": "Cannot map to available tools"}}

DATE TOKENS (use exactly these strings when the question mentions time):
- "today", "yesterday"
- "this_week", "last_week"
- "this_month", "last_month"
- "this_year", "last_year"
- OR an explicit range: {{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}}

CITY RULES: normalize to lowercase without accents (e.g., "São Paulo" → "sao paulo", "Rio de Janeiro" → "rio de janeiro").
STATE RULES: use 2-letter Brazilian UF codes (e.g., "SP", "RJ", "MG").

--- FEW-SHOT EXAMPLES ---

Q: "How many delivered orders did we have in São Paulo last month?"
A: {{"tool": "count_orders", "args": {{"city": "sao paulo", "status": "delivered", "date_token": "last_month"}}}}

Q: "How many canceled orders this year?"
A: {{"tool": "count_orders", "args": {{"status": "canceled", "date_token": "this_year"}}}}

Q: "How many orders in Rio de Janeiro last week?"
A: {{"tool": "count_orders", "args": {{"city": "rio de janeiro", "date_token": "last_week"}}}}

Q: "What is the status of order abc123?"
A: {{"tool": "get_order_status", "args": {{"order_id": "abc123"}}}}

Q: "How many shipped orders do we have?"
A: {{"tool": "count_orders", "args": {{"status": "shipped"}}}}

Q: "Total orders in SP this month?"
A: {{"tool": "count_orders", "args": {{"state": "SP", "date_token": "this_month"}}}}

--- END EXAMPLES ---

Now convert the following question. Extract EVERY filter (city, state, status, date). Do not drop any.
"""


async def call_llm_for_tool(question: str, system_prompt: str) -> dict:
    """Call Ollama to translate question into a tool call.

    Hardened against the realities of small models on CPU:
    - temperature=0 for deterministic, faster tool selection
    - a generous timeout (inference latency swings widely on CPU)
    - one retry on a timeout or unparseable response before giving up
    """
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }

    last_error = "LLM call failed"

    for attempt in range(1, settings.llm_max_attempts + 1):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json=payload,
                    timeout=settings.llm_timeout_seconds,
                )
                response.raise_for_status()

            content = response.json().get("message", {}).get("content", "")
            return json.loads(content)

        except json.JSONDecodeError as e:
            last_error = "LLM returned invalid JSON"
            logger.warning(f"Attempt {attempt}: failed to parse LLM JSON: {e}")
        except httpx.TimeoutException:
            last_error = (
                f"Model timed out after {settings.llm_timeout_seconds}s "
                "(slow inference on CPU) — please try again"
            )
            logger.warning(f"Attempt {attempt}: LLM request timed out")
        except httpx.RequestError as e:
            last_error = f"LLM service unreachable: {e!r}"
            logger.warning(f"Attempt {attempt}: LLM request failed: {e!r}")
        except Exception as e:
            last_error = str(e) or "Unexpected LLM error"
            logger.error(f"Attempt {attempt}: unexpected error calling LLM: {e!r}")

    logger.error(f"LLM failed after {settings.llm_max_attempts} attempts: {last_error}")
    return {"error": last_error}


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
