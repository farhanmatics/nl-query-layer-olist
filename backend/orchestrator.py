import copy
import json
import logging
import httpx
from datetime import datetime
from config import settings
from cache import translation_cache, translation_key

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

        # Layer 1 cache: reuse a prior translation of this question (no data is
        # cached — the query below still runs against the live DB).
        cache_key = translation_key(question, system_prompt)
        cached_call = (
            translation_cache.get(cache_key) if settings.llm_cache_enabled else None
        )
        if cached_call is not None:
            from_cache = True
            tool_call = copy.deepcopy(cached_call)
            logger.info(f"Translation cache HIT: {question}")
        else:
            from_cache = False
            tool_call = await call_llm_for_tool(question, system_prompt)
            # Only cache a clean, usable tool call — never a transient error.
            if (
                settings.llm_cache_enabled
                and isinstance(tool_call, dict)
                and "error" not in tool_call
                and tool_call.get("tool")
            ):
                translation_cache.set(cache_key, copy.deepcopy(tool_call))

        logger.info(f"LLM selected tool: {tool_call.get('tool')}")

        if not tool_call or "error" in tool_call:
            return {
                "error": tool_call.get("error", "Failed to parse LLM response"),
                "operation": None,
                "filters": None,
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
            }

        tool_name = tool_call.get("tool")
        args = dict(tool_call.get("args", {}) or {})

        # Filter-faithfulness guard: catch filters the model dropped before they
        # turn into a confidently wrong answer (see validation/faithfulness.py).
        guard = apply_filter_guard(question, tool_name, args)
        if guard.get("unresolved"):
            missing = ", ".join(guard["unresolved"])
            return {
                "error": (
                    f"Your question seems to reference {missing}, but I couldn't "
                    "apply it reliably. Please rephrase so the filter is explicit."
                ),
                "operation": tool_name,
                "filters": args,
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
                "guard": guard,
            }

        result = await dispatch_function(tool_name, args)

        if "error" in result:
            return {
                "error": result.get("error"),
                "operation": tool_name,
                "filters": result.get("filters"),
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
                "guard": guard,
            }

        formatted_answer = await format_answer(tool_name, result)

        return {
            "operation": tool_name,
            "filters": result.get("filters"),
            "result": {k: v for k, v in result.items() if k != "filters"},
            "formatted_answer": formatted_answer,
            "source": get_source_citation(tool_name),
            "error": None,
            "cached": from_cache,
            "guard": guard,
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
STATUS RULES: valid order statuses are delivered, shipped, canceled, processing, invoiced, unavailable, approved, created. Pass the status verbatim from this list.
GROUP_BY RULES: when a question says "by X" / "broken down by X" / "grouped by X" / "per X" (X = state, category, or month), set group_by to that dimension.

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

Q: "What was our total revenue last month?"
A: {{"tool": "get_revenue", "args": {{"date_token": "last_month"}}}}

Q: "Revenue by state this year"
A: {{"tool": "get_revenue", "args": {{"date_token": "this_year", "group_by": "state"}}}}

Q: "Show revenue broken down by category"
A: {{"tool": "get_revenue", "args": {{"group_by": "category"}}}}

Q: "Total revenue in MG last year"
A: {{"tool": "get_revenue", "args": {{"state": "MG", "date_token": "last_year"}}}}

Q: "How much revenue did the health_beauty category make?"
A: {{"tool": "get_revenue", "args": {{"category": "health_beauty"}}}}

Q: "How many approved orders last year?"
A: {{"tool": "count_orders", "args": {{"status": "approved", "date_token": "last_year"}}}}

Q: "How many low reviews did we get last month?"
A: {{"tool": "count_low_reviews", "args": {{"date_token": "last_month"}}}}

Q: "How many 1-star or 2-star reviews in Sao Paulo?"
A: {{"tool": "count_low_reviews", "args": {{"score_max": 2, "city": "sao paulo"}}}}

Q: "What are our best-selling products?"
A: {{"tool": "top_products", "args": {{"by": "count", "limit": 10}}}}

Q: "Top 5 products by revenue this year"
A: {{"tool": "top_products", "args": {{"by": "revenue", "limit": 5, "date_token": "this_year"}}}}

Q: "Show me delivered orders in Sao Paulo"
A: {{"tool": "list_orders", "args": {{"city": "sao paulo", "status": "delivered"}}}}

Q: "List the next 20 canceled orders"
A: {{"tool": "list_orders", "args": {{"status": "canceled", "limit": 20}}}}

Q: "List 30 shipped orders in MG"
A: {{"tool": "list_orders", "args": {{"state": "MG", "status": "shipped", "limit": 30}}}}

--- END EXAMPLES ---

Now convert the following question. Extract EVERY filter (city, state, status, date). Do not drop any.
"""


def _extract_json(content: str) -> dict:
    """Best-effort parse of an LLM tool call.

    Ollama's format=json usually returns a clean object, but small models
    occasionally wrap it in prose or ```json fences. Try a strict parse first,
    then fall back to the outermost {...} span. Raises json.JSONDecodeError if
    nothing parseable is found.
    """
    text = (content or "").strip()
    if text.startswith("```"):
        # strip a leading ```json / ``` fence and any trailing fence
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


async def call_llm_for_tool(question: str, system_prompt: str) -> dict:
    """Call Ollama to translate question into a tool call.

    Hardened against the realities of small models on CPU:
    - temperature=0 on the first pass for deterministic, fast tool selection
    - a generous timeout (inference latency swings widely on CPU)
    - retry on timeout or unparseable output; because temp=0 is deterministic,
      a parse-failure retry raises the temperature so the resample differs
    """
    base_payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "format": "json",
    }

    last_error = "LLM call failed"

    for attempt in range(1, settings.llm_max_attempts + 1):
        # First attempt greedy (temp=0); later attempts sample so a deterministic
        # bad output doesn't simply repeat.
        temperature = 0 if attempt == 1 else 0.4
        payload = {**base_payload, "options": {"temperature": temperature}}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json=payload,
                    timeout=settings.llm_timeout_seconds,
                )
                response.raise_for_status()

            content = response.json().get("message", {}).get("content", "")
            return _extract_json(content)

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


def apply_filter_guard(question: str, tool_name: str, args: dict) -> dict:
    """Run the faithfulness guard for a tool call and repair the args in place.

    Looks up which parameters the chosen tool accepts, detects filters that are
    present in the question but missing from the model's args, and merges any
    safe repairs into `args`. Returns the guard report ({applied, unresolved})
    for auditability; on any internal error it degrades to a no-op so a guard
    bug can never block an otherwise-valid query.
    """
    try:
        from functions.registry import get_function
        from validation.cities import get_known_cities
        from validation.faithfulness import check_filter_faithfulness

        schema = get_function(tool_name)["schema"]
        supported = set(schema.get("parameters", {}).get("properties", {}).keys())
    except Exception:
        return {"applied": [], "unresolved": []}

    report = check_filter_faithfulness(
        question, supported, args, get_known_cities()
    )
    if report["repairs"]:
        args.update(report["repairs"])
        logger.info(
            f"Faithfulness guard repaired dropped filters: {report['applied']}"
        )
    return {"applied": report["applied"], "unresolved": report["unresolved"]}


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
        filter_str = _filter_str(result.get("filters", {}))
        if filter_str:
            return f"There were {count:,} orders ({filter_str})."
        return f"There were {count:,} orders."

    elif tool_name == "get_revenue":
        if "breakdown" in result:
            group_by = result.get("group_by", "group")
            rows = result.get("breakdown", [])
            top = ", ".join(
                f"{r.get(group_by, '?')}: {r.get('revenue', 0):,.2f}" for r in rows[:5]
            )
            return f"Revenue by {group_by} — {top}" if top else "No revenue found."
        revenue = result.get("revenue", 0) or 0
        filter_str = _filter_str(result.get("filters", {}))
        if filter_str:
            return f"Total revenue was R$ {revenue:,.2f} ({filter_str})."
        return f"Total revenue was R$ {revenue:,.2f}."

    elif tool_name == "count_low_reviews":
        count = result.get("count", 0)
        filter_str = _filter_str(result.get("filters", {}))
        if filter_str:
            return f"There were {count:,} low reviews ({filter_str})."
        return f"There were {count:,} low reviews."

    elif tool_name == "top_products":
        products = result.get("products", [])
        by = result.get("by", "count")
        if not products:
            return "No products found for those filters."
        lines = []
        for i, p in enumerate(products, 1):
            val = p.get("value", 0)
            val_str = f"R$ {val:,.2f}" if by == "revenue" else f"{val:,} sold"
            lines.append(f"{i}. {p.get('category') or p.get('product_id')} ({val_str})")
        return f"Top {len(products)} products by {by}: " + "; ".join(lines)

    elif tool_name == "list_orders":
        total = result.get("total_count", 0)
        orders = result.get("orders", [])
        offset = result.get("offset", 0)
        filter_str = _filter_str(result.get("filters", {}))
        suffix = f" ({filter_str})" if filter_str else ""
        return (
            f"Showing {len(orders)} of {total:,} matching orders "
            f"(from #{offset + 1}){suffix}."
        )

    return "Query executed successfully."


def _filter_str(filters: dict) -> str:
    """Render a compact 'k: v' summary of non-empty filters."""
    return " ".join(f"{k}: {v}" for k, v in (filters or {}).items() if v)


def get_source_citation(tool_name: str) -> str:
    """Return the source citation for a query."""
    citations = {
        "get_order_status": "olist_orders_dataset JOIN olist_customers_dataset",
        "count_orders": "olist_orders_dataset JOIN olist_customers_dataset",
        "get_revenue": "olist_order_payments_dataset / olist_order_items_dataset JOIN olist_orders_dataset",
        "count_low_reviews": "olist_order_reviews_dataset JOIN olist_orders_dataset",
        "top_products": "olist_order_items_dataset JOIN olist_products_dataset, product_category_name_translation",
        "list_orders": "olist_orders_dataset JOIN olist_customers_dataset",
    }
    return citations.get(tool_name, "olist_orders_dataset")
