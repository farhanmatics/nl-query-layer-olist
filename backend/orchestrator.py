import copy
import json
import logging
import asyncio
from datetime import datetime
from typing import Optional
from config import settings
from cache import translation_cache, translation_key
from errors import client_error
from validation.scope import detect_unsupported_concept
from resolver import classify_turn, resolve as resolve_call, get_prior_state, store_state

logger = logging.getLogger(__name__)


def _empty_context() -> dict:
    return {"inherited": False, "from_operation": None, "carried": {}, "clarify": None}


async def _persist_turn(
    session_id: str,
    user_id: str,
    question: str,
    response: dict,
    resolved_args: Optional[dict] = None,
) -> None:
    """Persist a (user question, assistant response) pair to the durable
    session history. B3 prepares for B4: the assistant row's `resolved_call`
    is the *input-shaped* {operation, args} that the resolver needs to inherit
    on a follow-up (e.g. date_token="last_month", NOT the resolved
    date_range=[iso, iso] which isn't a re-dispatchable kwarg).

    `resolved_args` is supplied ONLY on a fully-resolved success turn — it is
    the same input-shaped dict the ephemeral B0 store keeps. Clarify/error/
    parse-fail turns pass nothing, so resolved_call stays NULL and
    `get_last_resolved_call` correctly skips them (per the plan).

    Ownership has already been verified by the caller; this helper writes
    to the session it was given.
    """
    import appdb
    try:
        await appdb.insert_message(
            session_id=session_id,
            role="user",
            question=question,
        )
        op = response.get("meta_operation") or response.get("operation")
        resolved_call = None
        if (
            resolved_args is not None
            and op
            and not response.get("error")
            and not (response.get("context") or {}).get("clarify")
        ):
            resolved_call = json.dumps({"operation": op, "args": resolved_args})
        await appdb.insert_message(
            session_id=session_id,
            role="assistant",
            response_json=json.dumps(response, default=str),
            resolved_call=resolved_call,
        )
        # Bump last_active_at so the session floats to the top of the sidebar.
        await appdb.touch_chat_session(session_id, user_id)
        # First message titles an untitled ("New chat") conversation. No-op if
        # the session already has a title. Done LAST: it's cosmetic and must
        # never abort the critical message/resolved_call writes above.
        await appdb.set_session_title_if_unset(
            session_id, user_id, appdb.derive_session_title(question)
        )
    except Exception as e:
        # Persistence is best-effort. The user already got their answer
        # (or an error). Log and move on; the next turn will create new
        # rows either way.
        logger.warning(f"Failed to persist turn for session {session_id}: {e}")


async def process_question(
    question: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
):
    """
    Main orchestration pipeline:
    1. Build system prompt with tool schemas
    2. Call DashScope to get tool name + args
    3. Validate arguments
    4. Execute parameterized query
    5. Format answer with DashScope (fallback to templates on error)
    6. Return structured response

    session_id (optional): if provided, the backend resolves this turn
    against the prior turn's state in the same session (B0 conversational
    resolution). Absent = single-shot, no context.

    user_id (optional, B3+): when both user_id and session_id are present,
    the session is treated as a *durable* server-side conversation and the
    (user, assistant) pair is persisted to it. When session_id is absent
    or user_id is absent, the existing B0 ephemeral store is used. This
    lets F2-early (no auth) keep working unchanged.
    """
    durable = bool(user_id and session_id)
    try:
        logger.info(f"Starting orchestration for: {question}")

        # Out-of-scope guard: decline concepts the schema can't answer (returns,
        # refunds, profit, inventory, ...) instead of letting the model map them
        # onto a proxy and return a confidently wrong number.
        from schemas import get_active_config
        unsupported = detect_unsupported_concept(question)
        if unsupported:
            logger.info(f"Declining unsupported concept: {unsupported['concept']}")
            cfg = get_active_config()
            response = {
                "error": (
                    f"The {cfg.display_name} dataset doesn't track "
                    f"{unsupported['concept']}. "
                    f"{unsupported['suggestion']}"
                ),
                "operation": None,
                "filters": None,
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": False,
                "context": _empty_context(),
            }
            if durable:
                await _persist_turn(session_id, user_id, question, response)
            return response

        from functions.registry import get_all_schemas

        use_meta = settings.meta_tools_enabled
        use_planner = settings.planner_enabled and use_meta
        if use_meta:
            from meta_schemas import get_meta_tool_schemas

            tool_schemas = get_meta_tool_schemas()
            system_prompt = build_meta_system_prompt(tool_schemas)
            if use_planner:
                from planner_schemas import build_planner_system_prompt

                system_prompt = build_planner_system_prompt(system_prompt)
        else:
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
            if use_planner and isinstance(tool_call, dict) and "error" not in tool_call:
                from planner_schemas import normalize_plan

                plan = normalize_plan(tool_call)
                if plan.get("error"):
                    tool_call = plan
                elif len(plan.get("steps") or []) > 1 or plan.get("mode") == "chain":
                    chain_response = await _execute_chain_plan(
                        question, plan, from_cache=from_cache, durable=durable,
                        session_id=session_id, user_id=user_id,
                    )
                    return chain_response
                else:
                    step = (plan.get("steps") or [{}])[0]
                    tool_call = {
                        "tool": step.get("tool"),
                        "args": dict(step.get("args") or {}),
                    }
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
            response = {
                "error": tool_call.get("error", "Failed to parse LLM response"),
                "operation": None,
                "filters": None,
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
                "context": _empty_context(),
            }
            if durable:
                await _persist_turn(session_id, user_id, question, response)
            return response

        candidate = {"tool": tool_call.get("tool"), "args": dict(tool_call.get("args", {}) or {})}

        # B0 conversational resolution: classify FRESH vs FOLLOW_UP and merge
        # with prior state if applicable. After this, `tool_name` and `args`
        # are the final values the rest of the pipeline dispatches on.
        # When the session is durable, load prior state from the DB (B4 prep);
        # otherwise fall back to the B0 in-memory store.
        if durable:
            import appdb
            prior = await appdb.get_last_resolved_call(session_id)
        else:
            prior = get_prior_state(session_id)

        # Meta-mode: switching tool shape (count → rank) carries filters but does
        # not lock the user into the prior operation (B0 resolver would).
        if use_meta and prior and candidate.get("tool"):
            from meta_router import inherit_meta_filters

            prior_op = prior.get("operation")
            cand_tool = candidate.get("tool")
            if prior_op and cand_tool != prior_op:
                candidate = inherit_meta_filters(prior, candidate)
                carried = {
                    k: v
                    for k, v in (candidate.get("args") or {}).items()
                    if k in ("category", "city", "state", "date_token", "entity")
                }
                resolved = {
                    "operation": candidate["tool"],
                    "args": dict(candidate.get("args") or {}),
                    "context": {
                        "inherited": bool(carried),
                        "from_operation": prior_op,
                        "carried": carried,
                        "clarify": None,
                    },
                }
            else:
                classification = classify_turn(question, candidate.get("tool"))
                resolved = resolve_call(question, candidate, prior, classification)
        else:
            classification = classify_turn(question, candidate.get("tool"))
            resolved = resolve_call(question, candidate, prior, classification)

        meta_tool = resolved["operation"]
        meta_args = resolved["args"]
        context = resolved["context"]

        # Clarify path: the resolver declined (e.g. inherited op can't filter
        # by a named place). Return a response that the frontend renders as a
        # quick-reply prompt. Do NOT store this turn as new state.
        if context.get("clarify"):
            logger.info(
                f"Clarify: {context['clarify'].get('prompt')!r} "
                f"(inherited from {context.get('from_operation')})"
            )
            response = {
                "operation": None,
                "filters": None,
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
                "context": context,
            }
            if durable:
                # Persist the clarify turn too (so reload shows the prompt)
                # but with resolved_call=NULL so get_last_resolved_call skips it.
                await _persist_turn(session_id, user_id, question, response)
            return response

        # Meta-tool layer: map count/lookup shapes → internal executors.
        tool_name = meta_tool
        args = meta_args
        measure_meta = None

        if use_meta and meta_tool:
            from validation.entity_intent import build_count_clarify, detect_count_ambiguity
            from meta_router import apply_entity_intent, measure_for_tool, resolve_meta_call

            if meta_tool == "count":
                meta_args = apply_entity_intent(question, meta_args)
                if detect_count_ambiguity(question) and not meta_args.get("entity"):
                    clarify = build_count_clarify(meta_args.get("category"))
                    logger.info(f"Clarify (entity ambiguity): {clarify['prompt']!r}")
                    response = {
                        "operation": None,
                        "filters": None,
                        "result": None,
                        "formatted_answer": None,
                        "source": None,
                        "cached": from_cache,
                        "context": {**context, "clarify": clarify},
                    }
                    if durable:
                        await _persist_turn(session_id, user_id, question, response)
                    return response

            try:
                tool_name, args = resolve_meta_call(meta_tool, meta_args, question)
                logger.info(f"Meta route: {meta_tool} → {tool_name}")
            except ValueError as e:
                response = {
                    "error": str(e),
                    "operation": meta_tool,
                    "filters": meta_args,
                    "result": None,
                    "formatted_answer": None,
                    "source": None,
                    "cached": from_cache,
                    "context": context,
                }
                if durable:
                    await _persist_turn(session_id, user_id, question, response)
                return response

            measure_meta = measure_for_tool(tool_name)

        # Filter-faithfulness guard: catch filters the model dropped before they
        # turn into a confidently wrong answer (see validation/faithfulness.py).
        # SQL escape uses its own validator — skip the filter guard.
        guard = {"applied": [], "unresolved": []}
        if tool_name != "run_readonly_sql":
            guard = apply_filter_guard(question, tool_name, args)
        if guard.get("unresolved"):
            response = {
                "error": _build_guard_error(tool_name, guard),
                "operation": tool_name,
                "filters": args,
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
                "guard": guard,
                "context": context,
            }
            if durable:
                await _persist_turn(session_id, user_id, question, response)
            return response

        result = await dispatch_function(tool_name, args)

        if "error" in result:
            # Don't overwrite prior state on error.
            response = {
                "error": result.get("error"),
                "operation": tool_name,
                "filters": result.get("filters"),
                "result": None,
                "formatted_answer": None,
                "source": None,
                "cached": from_cache,
                "guard": guard,
                "context": context,
            }
            if durable:
                await _persist_turn(session_id, user_id, question, response)
            return response

        formatted_answer = await format_answer(
            question, tool_name, result.get("filters") or {}, result
        )

        # Persist successful turn for future follow-ups in the same session.
        # For durable sessions: write to the messages table. For ephemeral
        # (F2-early) sessions: keep the B0 in-memory store. BOTH persist the
        # same input-shaped args (date_token, not the resolved date_range) so a
        # follow-up can re-dispatch and the date isn't silently dropped.
        stored_args = {
            k: v for k, v in (meta_args if use_meta else args or {}).items()
            if v not in (None, "", [], {})
        }
        state_operation = meta_tool if use_meta else tool_name
        if durable:
            response = {
                "operation": tool_name,
                "meta_operation": meta_tool if use_meta else None,
                "filters": result.get("filters"),
                "result": {
                    k: v for k, v in result.items() if k != "filters"
                },
                "formatted_answer": formatted_answer,
                "source": get_source_citation(tool_name),
                "error": None,
                "cached": from_cache,
                "guard": guard,
                "context": context,
            }
            if measure_meta:
                response["measure"] = measure_meta
            await _persist_turn(
                session_id, user_id, question, response, resolved_args=stored_args
            )
            return response
        else:
            # B0 ephemeral state store.
            if session_id:
                store_state(session_id, state_operation, stored_args)
            ephemeral = {
                "operation": tool_name,
                "meta_operation": meta_tool if use_meta else None,
                "filters": result.get("filters"),
                "result": {k: v for k, v in result.items() if k != "filters"},
                "formatted_answer": formatted_answer,
                "source": get_source_citation(tool_name),
                "error": None,
                "cached": from_cache,
                "guard": guard,
                "context": context,
            }
            if measure_meta:
                ephemeral["measure"] = measure_meta
            return ephemeral

    except Exception as e:
        logger.error(f"Orchestration failed: {e}", exc_info=True)
        return {
            "error": client_error(e, "The query could not be processed."),
            "operation": None,
            "filters": None,
            "result": None,
            "formatted_answer": None,
            "source": None,
            "context": _empty_context(),
        }


def build_system_prompt(tool_schemas: list[dict]) -> str:
    """Build the system prompt for the LLM with tool definitions and few-shot examples.

    The dataset description, status/state/city/group_by rule text, the
    few-shot examples, and the source-citation strings are all read
    from the active SchemaConfig (so they automatically reflect
    whichever schema is selected via the `SCHEMA` env var).
    """
    from schemas import get_active_config
    cfg = get_active_config()
    prompt = cfg.prompt
    schema_json = json.dumps(tool_schemas, indent=2)

    examples_text = "\n\n".join(
        f'Q: "{q}"\nA: {a}'
        for q, a in prompt.few_shot_examples
    )

    return f"""You are a data query assistant. Your ONLY job is to convert a natural language question into a single JSON function call against the {cfg.display_name} dataset. You must extract ALL filters mentioned in the question — never drop any.

{prompt.dataset_description}

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

CITY RULES: {prompt.city_rule}
STATE RULES: {prompt.state_rule}
STATUS RULES: {prompt.status_rule}
GROUP_BY RULES: {prompt.group_by_rule}

--- FEW-SHOT EXAMPLES ---

{examples_text}

--- END EXAMPLES ---

Now convert the following question. Extract EVERY filter (city, state, status, date). Do not drop any.
"""


def build_meta_system_prompt(tool_schemas: list[dict]) -> str:
    """System prompt for the meta-tool surface (count, lookup, rank, …, query)."""
    from meta_schemas import META_FEW_SHOT_EXAMPLES
    from schemas import get_active_config

    cfg = get_active_config()
    prompt = cfg.prompt
    schema_json = json.dumps(tool_schemas, indent=2)
    examples_text = "\n\n".join(
        f'Q: "{q}"\nA: {a}' for q, a in META_FEW_SHOT_EXAMPLES
    )
    query_note = ""
    if settings.sql_escape_enabled:
        allowed = ", ".join(sorted(cfg.tables.values()))
        query_note = f"""
CRITICAL — query (SQL escape, last resort only):
- Use ONLY when count/rank/sum/list/breakdown/compare cannot answer.
- Emit a single PostgreSQL SELECT with LIMIT (max {settings.sql_escape_max_limit}).
- Allowlisted tables: {allowed}.
- Never INSERT/UPDATE/DELETE. Backend rejects unsafe SQL.
"""

    return f"""You are a data query assistant. Convert the question into ONE meta-tool JSON call.
The backend maps your call to exact SQL — you only choose the shape and filters.

Dataset: {cfg.display_name}. {prompt.dataset_description}

META-TOOLS (pick exactly one):
{schema_json}

CRITICAL — count.entity:
- "products" = rows in the PRODUCT CATALOG (how many SKUs we have).
- "orders" = distinct ORDERS sold / placed / delivered (transactions).
- "reviews" = low-scoring reviews.
- "payments" = payment transactions by type.
When the user asks "how many products we have" or "in the catalog", entity MUST be "products".
When they ask about orders sold or placed in a category, entity MUST be "orders".

CRITICAL — rank:
- Use for "best", "top", "worst", "highest rated".
- entity=products + by=revenue + limit=1 for "the best product".
- Always pass category and date_token when mentioned.

CRITICAL — sum / list / breakdown / compare:
- sum measure=revenue for total revenue; add group_by for "by state/category/month".
- list entity=orders for order lists; customer_orders needs customer_id.
- breakdown for histograms (order_status, review_score, payment_type, revenue_state, …).
- compare with dimension + values array for side-by-side seller/category/state.
{query_note}
OUTPUT: ONLY valid JSON with keys "tool" and "args".

DATE TOKENS: today, yesterday, this_week, last_week, this_month, last_month, this_year, last_year

CITY: {prompt.city_rule}
STATE: {prompt.state_rule}
STATUS: {prompt.status_rule}

--- EXAMPLES ---
{examples_text}
--- END ---

Extract every filter. Do not drop any.
"""


def _extract_json(content: str) -> dict:
    """Best-effort parse of an LLM tool call.

    Ollama's format=json usually returns a clean object, but models
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


async def _execute_chain_plan(
    question: str,
    plan: dict,
    *,
    from_cache: bool,
    durable: bool,
    session_id: Optional[str],
    user_id: Optional[str],
) -> dict:
    """Run a multi-step planner chain and return a formatted response."""
    from chain_executor import execute_plan
    from meta_router import measure_for_tool, resolve_meta_call

    out = await execute_plan(
        plan,
        question=question,
        resolve_meta_call=resolve_meta_call,
        dispatch_function=dispatch_function,
        apply_filter_guard=apply_filter_guard,
    )
    if out.get("error"):
        response = {
            "error": out["error"],
            "operation": out.get("operation"),
            "filters": out.get("filters"),
            "result": None,
            "formatted_answer": None,
            "source": None,
            "cached": from_cache,
            "context": _empty_context(),
            "plan": plan,
        }
        if durable and session_id:
            await _persist_turn(session_id, user_id, question, response)
        return response

    final_op = out["final_operation"]
    final_result = dict(out["final_result"] or {})
    final_filters = out.get("final_filters") or {}
    formatted_answer = await format_answer(
        question, final_op, final_filters, {**final_result, "filters": final_filters}
    )
    measure_meta = measure_for_tool(final_op) if final_op else None
    response = {
        "operation": final_op,
        "meta_operation": "chain",
        "filters": final_filters,
        "result": final_result,
        "formatted_answer": formatted_answer,
        "source": get_source_citation(final_op) if final_op else None,
        "error": None,
        "cached": from_cache,
        "context": {**_empty_context(), "plan_mode": plan.get("mode"), "steps": len(out.get("steps") or [])},
        "plan": plan,
        "chain": out.get("steps"),
    }
    if measure_meta:
        response["measure"] = measure_meta
    if durable and session_id:
        await _persist_turn(session_id, user_id, question, response)
    return response


async def call_llm_for_tool(question: str, system_prompt: str) -> dict:
    """Call DashScope to translate question into a tool call (JSON).

    Retries on parse failure with higher temperature so a bad output doesn't
    simply repeat. Timeout is enforced at the orchestrator level via asyncio.
    """
    from model_client import get_model_client
    from model_client.dashscope_client import DashScopeError

    client = get_model_client()
    last_error = "LLM call failed"

    for attempt in range(1, settings.llm_max_attempts + 1):
        temperature = 0 if attempt == 1 else 0.4
        try:
            content = await asyncio.wait_for(
                client.complete_json(system_prompt, question, temperature=temperature),
                timeout=settings.llm_timeout_seconds,
            )
            return _extract_json(content)
        except json.JSONDecodeError as e:
            last_error = "LLM returned invalid JSON"
            logger.warning(f"Attempt {attempt}: failed to parse LLM JSON: {e}")
        except TimeoutError:
            last_error = (
                f"Model timed out after {settings.llm_timeout_seconds}s — please try again"
            )
            logger.warning(f"Attempt {attempt}: LLM request timed out")
        except DashScopeError as e:
            last_error = str(e) or "DashScope API error"
            logger.warning(f"Attempt {attempt}: DashScope error: {e!r}")
        except Exception as e:
            last_error = str(e) or "Unexpected LLM error"
            logger.error(f"Attempt {attempt}: unexpected error calling LLM: {e!r}")

    logger.error(f"LLM failed after {settings.llm_max_attempts} attempts: {last_error}")
    return {"error": last_error}


def _build_guard_error(tool_name: str, guard: dict) -> str:
    """Human-readable decline when the question names a filter the tool can't use."""
    unresolved = guard.get("unresolved") or []
    missing = ", ".join(unresolved)
    try:
        from functions.registry import get_function

        desc = get_function(tool_name)["schema"].get("description", tool_name)
    except Exception:
        desc = tool_name

    hints: list[str] = []
    joined = missing.lower()
    if "city" in joined or "state" in joined:
        hints.append("order counts or revenue for that location")
    if "status" in joined:
        hints.append("a count or list filtered by order status")
    if "category" in joined:
        hints.append("product counts in the catalog vs orders by category")
    if "date" in joined:
        hints.append("an explicit date range (e.g. last month, 2018)")
    hint = hints[0] if hints else "a query type that supports those filters"

    return (
        f"Your question references {missing}, but `{tool_name}` does not support "
        f"that filter ({desc}). I won't return a number that ignores it — try "
        f"rephrasing, for example ask for {hint}."
    )


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
        question, supported, args, get_known_cities(), tool_name=tool_name
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
        return {"error": client_error(e, "The request could not be processed with the given arguments.")}
    except Exception as e:
        logger.error(f"Function execution failed: {e}", exc_info=True)
        return {"error": client_error(e, "The query could not be completed.")}


_FORMAT_SYSTEM_PROMPT = (
    "You are a data assistant. Given a query operation, its filters, and the "
    "database result, write ONE clear sentence answering the user's question. "
    "Use the exact numbers from the result — never estimate or round differently. "
    "Mention key filters naturally. Keep it under 2 sentences."
)


def _sanitize_result_for_llm(tool_name: str, result: dict) -> dict:
    """Collapse result payloads before sending aggregates to the cloud model."""
    if tool_name == "list_orders":
        orders = result.get("orders") or []
        return {
            "total_count": result.get("total_count", 0),
            "showing": len(orders),
            "offset": result.get("offset", 0),
            "sample": orders[:3],
        }
    if tool_name == "run_readonly_sql":
        rows = result.get("rows") or []
        return {
            "columns": result.get("columns", []),
            "row_count": result.get("row_count", len(rows)),
            "sample": rows[:5],
        }
    if tool_name == "top_products":
        return {
            k: v for k, v in result.items()
            if k != "filters"
        }
    return {k: v for k, v in result.items() if k != "filters"}


async def call_llm_for_format(
    question: str,
    tool_name: str,
    filters: dict,
    result: dict,
) -> str:
    """Ask DashScope to turn aggregates into a natural-language sentence."""
    from model_client import get_model_client
    from model_client.dashscope_client import DashScopeError

    payload = json.dumps(
        {
            "question": question,
            "operation": tool_name,
            "filters": filters,
            "result": _sanitize_result_for_llm(tool_name, result),
        },
        default=str,
    )
    client = get_model_client()
    text = await asyncio.wait_for(
        client.complete_text(_FORMAT_SYSTEM_PROMPT, payload, temperature=0.3),
        timeout=settings.llm_timeout_seconds,
    )
    if not text or not text.strip():
        raise DashScopeError("Empty formatted answer from DashScope")
    return text.strip()


def _format_answer_deterministic(tool_name: str, result: dict) -> str:
    """Fallback templates when cloud formatting is unavailable."""
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

    elif tool_name == "run_readonly_sql":
        count = result.get("row_count", 0)
        cols = result.get("columns") or []
        return f"Query returned {count} row(s) with columns: {', '.join(cols) or 'none'}."

    return "Query executed successfully."


async def format_answer(
    question: str,
    tool_name: str,
    filters: dict,
    result: dict,
) -> str:
    """Format the result into a natural language answer via DashScope.

    Falls back to deterministic templates if the cloud call fails so a
    correct number is never blocked by a formatting error.
    """
    if "error" in result:
        return result["error"]

    try:
        return await call_llm_for_format(question, tool_name, filters, result)
    except Exception as e:
        logger.warning(f"Cloud format failed, using deterministic fallback: {e!r}")
        merged = {**result, "filters": filters}
        return _format_answer_deterministic(tool_name, merged)


def _format_date_range(value) -> Optional[str]:
    """Render a [start_iso, end_iso] pair as a human-readable range.

    Examples: "Jul 1–31, 2018" (same month), "Jul 1 – Aug 5, 2018" (same year),
    "Dec 1, 2017 – Jan 31, 2018" (spans years). Returns None if unparseable.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        start = datetime.fromisoformat(str(value[0]))
        end = datetime.fromisoformat(str(value[1]))
    except (ValueError, TypeError):
        return None
    if start.year == end.year and start.month == end.month and start.day == end.day:
        return f"{start:%b} {start.day}, {start.year}"
    if start.year == end.year and start.month == end.month:
        return f"{start:%b} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return f"{start:%b} {start.day} – {end:%b} {end.day}, {start.year}"
    return f"{start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}"


def _filter_str(filters: dict) -> str:
    """Render a clean, human-readable summary of the active filters.

    Drops structural/pagination keys, title-cases city names, formats the date
    range as a readable span, and omits the raw key labels so the result reads
    naturally inside an answer sentence.
    """
    parts = []
    for key, value in (filters or {}).items():
        if value in (None, "", [], {}):
            continue
        if key in ("limit", "offset", "by", "group_by"):
            continue
        if key == "date_range":
            rendered = _format_date_range(value)
            if rendered:
                parts.append(rendered)
        elif key == "city":
            parts.append(str(value).title())
        elif key == "score_max":
            parts.append(f"score ≤ {value}")
        else:
            parts.append(str(value))
    return ", ".join(parts)


def get_source_citation(tool_name: str) -> str:
    """Return the source citation for a query.

    Reads from the active SchemaConfig's `source_citations` dict. If a
    tool doesn't have an entry (e.g. a stub schema where the function
    isn't wired), falls back to a generic "this dataset" string so
    the citation surface is never empty.
    """
    from schemas import get_active_config
    cfg = get_active_config()
    citations = cfg.prompt.source_citations
    return citations.get(tool_name, f"{cfg.display_name} (source unspecified)")
