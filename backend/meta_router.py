"""Map meta-tool calls (count, lookup, rank, …) to internal function names + args."""
from __future__ import annotations

import logging
import re
from typing import Optional

from validation.entity_intent import detect_entity_for_count, has_catalog_signal

logger = logging.getLogger(__name__)

_BEST_RE = re.compile(r"\b(best|top|#1|number one|leading)\b", re.IGNORECASE)
_WORST_RE = re.compile(r"\b(worst|bottom|lowest)\b", re.IGNORECASE)

# Shared filter keys carried across meta-tool turns (e.g. count → rank).
_META_CARRY_KEYS = ("category", "city", "state", "date_token", "seller_id", "entity")

_LOOKUP_MAP = {
    "order": ("get_order_status", {"order_id": "id"}),
    "customer": ("get_customer_info", {"customer_id": "id"}),
    "product": ("get_product_info", {"product_id": "id"}),
    "seller": ("get_seller_info", {"seller_id": "id"}),
}

# Internal tool → (measure_id, human definition) for API responses.
MEASURE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "count_products": (
        "product_count",
        "Products in the product catalog (olist_products_dataset)",
    ),
    "count_orders": (
        "order_count",
        "Distinct orders matching the filters",
    ),
    "count_by_status": (
        "order_count",
        "Orders with the given status",
    ),
    "count_by_category": (
        "order_count",
        "Distinct orders that include at least one item in the category",
    ),
    "count_by_payment_type": (
        "order_count",
        "Distinct orders paid with the given payment type",
    ),
    "count_low_reviews": (
        "review_count",
        "Reviews with score at or below the threshold",
    ),
    "top_products": (
        "product_ranking",
        "Products ranked by units sold or revenue in order items",
    ),
    "products_by_rating": (
        "product_rating_ranking",
        "Products ranked by average review score",
    ),
    "top_sellers": (
        "seller_ranking",
        "Sellers ranked by orders or revenue",
    ),
    "top_categories": (
        "category_ranking",
        "Product categories ranked by units sold or revenue",
    ),
    "customer_lifetime_value": (
        "customer_ltv_ranking",
        "Top customers by total payment value",
    ),
    "get_revenue": ("revenue_total", "Total payment revenue"),
    "revenue_by_state": ("revenue_by_state", "Revenue grouped by customer state"),
    "revenue_by_category": ("revenue_by_category", "Revenue grouped by product category"),
    "revenue_trend": ("revenue_by_month", "Monthly revenue time series"),
    "revenue_by_seller": ("revenue_by_seller", "Revenue grouped by seller"),
    "revenue_by_payment_type": (
        "revenue_by_payment_type",
        "Revenue grouped by payment type",
    ),
    "on_time_delivery_rate": (
        "on_time_delivery_rate",
        "Share of delivered orders on or before estimated delivery date",
    ),
    "repeat_customer_rate": (
        "repeat_customer_rate",
        "Share of customers with more than one order",
    ),
    "average_delivery_days": (
        "avg_delivery_days",
        "Average days from purchase to delivery (delivered orders only)",
    ),
    "seller_concentration": (
        "seller_concentration",
        "Revenue share of top-10 sellers",
    ),
    "list_orders": ("order_list", "Paginated list of orders matching filters"),
    "customer_order_history": (
        "customer_order_list",
        "Paginated orders for one customer",
    ),
    "fulfillment_status_breakdown": (
        "order_status_breakdown",
        "Order count per fulfillment status",
    ),
    "review_score_distribution": (
        "review_score_histogram",
        "Review count per star rating (1-5)",
    ),
    "payment_type_breakdown": (
        "payment_type_mix",
        "Orders and revenue per payment type",
    ),
    "sellers_by_state": (
        "sellers_by_state",
        "Seller activity grouped by seller state",
    ),
    "review_sentiment_trend": (
        "review_sentiment_trend",
        "Average review score by month",
    ),
    "average_rating_by_category": (
        "category_rating_avg",
        "Average review score per product category",
    ),
    "seller_comparison": ("seller_comparison", "Side-by-side seller metrics"),
    "category_comparison": ("category_comparison", "Side-by-side category metrics"),
    "state_comparison": ("state_comparison", "Side-by-side state metrics"),
    "run_readonly_sql": (
        "ad_hoc_sql",
        "Validated read-only SELECT against allowlisted tables",
    ),
}


def _pick(args: dict, *keys: str) -> dict:
    out = {}
    for k in keys:
        if k in args and args[k] not in (None, "", [], {}):
            out[k] = args[k]
    return out


def apply_entity_intent(question: str, meta_args: dict) -> dict:
    """Merge deterministic entity detection into meta count args."""
    args = dict(meta_args or {})
    if args.get("entity"):
        # If LLM said orders but catalog phrasing is dominant, override.
        if args["entity"] == "orders" and has_catalog_signal(question):
            if not any(k in args for k in ("status", "date_token", "payment_type")):
                logger.info("Entity intent override: orders → products (catalog signal)")
                args["entity"] = "products"
        return args

    detected = detect_entity_for_count(question)
    if detected:
        args["entity"] = detected
        logger.info(f"Entity intent detected: entity={detected}")
    return args


def inherit_meta_filters(prior: Optional[dict], candidate: dict) -> dict:
    """Carry shared filters when the user shifts meta-tool shape on a follow-up."""
    if not prior:
        return candidate
    prior_args = dict(prior.get("args") or {})
    out = {
        "tool": candidate.get("tool"),
        "args": dict(candidate.get("args") or {}),
    }
    args = out["args"]
    for key in _META_CARRY_KEYS:
        if prior_args.get(key) and not args.get(key):
            args[key] = prior_args[key]
    # count(entity=products) → rank should default entity=products when category set.
    if (
        prior.get("operation") == "count"
        and prior_args.get("entity") == "products"
        and out.get("tool") == "rank"
        and not args.get("entity")
    ):
        args["entity"] = "products"
    return out


def apply_rank_defaults(question: str, meta_args: dict) -> dict:
    """Fill sensible rank defaults from question phrasing."""
    args = dict(meta_args or {})
    if not args.get("entity"):
        if re.search(r"\bsellers?\b", question, re.I):
            args["entity"] = "sellers"
        elif re.search(r"\bcategor", question, re.I) and not args.get("category"):
            args["entity"] = "categories"
        else:
            args["entity"] = "products"

    by = str(args.get("by") or "").lower().strip()
    if not by:
        if re.search(r"\b(rating|rated|stars?)\b", question, re.I):
            args["by"] = "rating"
        elif _WORST_RE.search(question) and re.search(r"\bunits?\b", question, re.I):
            args["by"] = "count"
        else:
            args["by"] = "revenue"

    if not args.get("sort"):
        args["sort"] = "worst" if _WORST_RE.search(question) else "best"

    if args.get("limit") is None:
        if _BEST_RE.search(question) and not re.search(r"\btop\s+\d+", question, re.I):
            args["limit"] = 1
        else:
            m = re.search(r"\btop\s+(\d+)\b", question, re.I)
            args["limit"] = int(m.group(1)) if m else 10

    return args


def _resolve_rank(args: dict) -> tuple[str, dict]:
    entity = str(args.get("entity", "")).lower().strip()
    by = str(args.get("by", "revenue")).lower().strip()
    sort = str(args.get("sort", "best")).lower().strip()

    if entity == "products":
        if by == "rating":
            internal_args = _pick(args, "category", "limit", "min_reviews")
            if "limit" not in internal_args:
                internal_args["limit"] = args.get("limit", 10)
            internal_args["sort"] = sort
            return "products_by_rating", internal_args
        internal_args = _pick(args, "category", "date_token", "limit", "by")
        if "by" not in internal_args:
            internal_args["by"] = by if by in ("count", "revenue") else "revenue"
        if "limit" not in internal_args:
            internal_args["limit"] = args.get("limit", 10)
        return "top_products", internal_args

    if entity == "categories":
        internal_args = _pick(args, "date_token", "limit", "by")
        if "by" not in internal_args:
            internal_args["by"] = by if by in ("count", "revenue") else "revenue"
        if "limit" not in internal_args:
            internal_args["limit"] = args.get("limit", 10)
        return "top_categories", internal_args

    if entity == "sellers":
        internal_args = _pick(args, "date_token", "state", "limit", "by")
        if "by" not in internal_args:
            internal_args["by"] = "orders" if by == "count" else "revenue"
        if "limit" not in internal_args:
            internal_args["limit"] = args.get("limit", 10)
        return "top_sellers", internal_args

    if entity == "customers":
        internal_args = _pick(args, "city", "state", "limit", "min_orders")
        if "limit" not in internal_args:
            internal_args["limit"] = args.get("limit", 10)
        return "customer_lifetime_value", internal_args

    raise ValueError(f"Unknown rank entity: {entity!r}")


def apply_sum_defaults(question: str, meta_args: dict) -> dict:
    args = dict(meta_args or {})
    if not args.get("measure"):
        q = question.lower()
        if re.search(r"\b(on[- ]time|delivered on time)\b", q):
            args["measure"] = "on_time_delivery_rate"
        elif re.search(r"\brepeat customer", q):
            args["measure"] = "repeat_customer_rate"
        elif re.search(r"\b(average|avg).{0,20}delivery days?\b", q):
            args["measure"] = "avg_delivery_days"
        elif re.search(r"\bconcentrat", q) and re.search(r"\bsellers?\b", q):
            args["measure"] = "seller_concentration"
        else:
            args["measure"] = "revenue"
    if not args.get("group_by"):
        if re.search(r"\bby state\b|\bper state\b|\beach state\b", question, re.I):
            args["group_by"] = "state"
        elif re.search(r"\bby categor", question, re.I):
            args["group_by"] = "category"
        elif re.search(r"\bby month\b|\bmonthly\b|\bper month\b", question, re.I):
            args["group_by"] = "month"
        elif re.search(r"\bby seller\b|\bper seller\b", question, re.I):
            args["group_by"] = "seller"
        elif re.search(r"\bby payment\b|\bpayment type\b", question, re.I):
            args["group_by"] = "payment_type"
    return args


def _resolve_sum(args: dict) -> tuple[str, dict]:
    measure = str(args.get("measure", "revenue")).lower().strip()
    group_by = args.get("group_by")

    if measure == "on_time_delivery_rate":
        return "on_time_delivery_rate", _pick(args, "state", "date_token")
    if measure == "repeat_customer_rate":
        return "repeat_customer_rate", _pick(args, "date_token")
    if measure == "avg_delivery_days":
        return "average_delivery_days", _pick(
            args, "state", "category", "seller_id", "date_token"
        )
    if measure == "seller_concentration":
        return "seller_concentration", _pick(args, "date_token")

    # revenue
    if group_by == "state":
        return "revenue_by_state", _pick(args, "date_token")
    if group_by == "category":
        return "revenue_by_category", _pick(args, "date_token", "limit")
    if group_by == "month":
        return "revenue_trend", _pick(args, "date_token")
    if group_by == "seller":
        return "revenue_by_seller", _pick(args, "date_token", "state", "limit")
    if group_by == "payment_type":
        return "revenue_by_payment_type", _pick(args, "date_token")
    return "get_revenue", _pick(args, "date_token", "city", "state", "category")


def _resolve_list(args: dict) -> tuple[str, dict]:
    entity = str(args.get("entity", "orders")).lower().strip()
    if entity == "customer_orders":
        if not args.get("customer_id"):
            raise ValueError("list entity=customer_orders requires customer_id")
        return "customer_order_history", _pick(
            args, "customer_id", "limit", "offset"
        )
    return "list_orders", _pick(
        args, "city", "state", "status", "date_token", "limit", "offset"
    )


_BREAKDOWN_MAP = {
    "order_status": ("fulfillment_status_breakdown", ("date_token",)),
    "review_score": (
        "review_score_distribution",
        ("date_token", "state", "seller_id"),
    ),
    "payment_type": ("payment_type_breakdown", ("date_token",)),
    "seller_state": ("sellers_by_state", ("date_token", "by")),
    "review_trend": ("review_sentiment_trend", ("date_token",)),
    "revenue_state": ("revenue_by_state", ("date_token",)),
    "revenue_category": ("revenue_by_category", ("date_token", "limit")),
    "revenue_month": ("revenue_trend", ("date_token",)),
    "category_rating": ("average_rating_by_category", ()),
}


def apply_breakdown_defaults(question: str, meta_args: dict) -> dict:
    args = dict(meta_args or {})
    if args.get("dimension"):
        return args
    q = question.lower()
    if re.search(r"\bstatus\b|\bfulfillment\b", q):
        args["dimension"] = "order_status"
    elif re.search(r"\breview score\b|\bstar rating\b|\b1[- ]star", q):
        args["dimension"] = "review_score"
    elif re.search(r"\bpayment type\b|\bpayment method\b", q):
        args["dimension"] = "payment_type"
    elif re.search(r"\bseller.{0,10}state\b", q):
        args["dimension"] = "seller_state"
    elif re.search(r"\bsentiment\b|\bsatisfaction trend\b", q):
        args["dimension"] = "review_trend"
    elif re.search(r"\brevenue by state\b", q):
        args["dimension"] = "revenue_state"
    elif re.search(r"\brevenue by categor", q):
        args["dimension"] = "revenue_category"
    elif re.search(r"\brevenue by month\b|\bmonthly revenue\b", q):
        args["dimension"] = "revenue_month"
    elif re.search(r"\brating by categor", q):
        args["dimension"] = "category_rating"
    return args


def _resolve_breakdown(args: dict) -> tuple[str, dict]:
    dimension = str(args.get("dimension", "")).lower().strip()
    if dimension not in _BREAKDOWN_MAP:
        raise ValueError(f"Unknown breakdown dimension: {dimension!r}")
    internal, keys = _BREAKDOWN_MAP[dimension]
    internal_args = _pick(args, *keys)
    if dimension == "seller_state" and "by" not in internal_args:
        internal_args["by"] = args.get("by", "revenue")
    return internal, internal_args


def _resolve_compare(args: dict) -> tuple[str, dict]:
    dimension = str(args.get("dimension", "")).lower().strip()
    values = args.get("values")
    if not values or not isinstance(values, list):
        raise ValueError("compare requires values (array of 2-5 items)")
    if dimension == "seller":
        return "seller_comparison", {
            "seller_ids": values,
            **_pick(args, "date_token"),
        }
    if dimension == "category":
        return "category_comparison", {
            "categories": values,
            **_pick(args, "date_token"),
        }
    if dimension == "state":
        return "state_comparison", {
            "states": values,
            **_pick(args, "date_token"),
        }
    raise ValueError(f"Unknown compare dimension: {dimension!r}")


def resolve_meta_call(
    meta_tool: str,
    meta_args: dict,
    question: str = "",
) -> tuple[str, dict]:
    """Resolve meta tool + args → (internal_tool_name, internal_args)."""
    args = dict(meta_args or {})

    if meta_tool == "lookup":
        entity = str(args.get("entity", "")).lower().strip()
        entity_id = args.get("id")
        if entity not in _LOOKUP_MAP:
            raise ValueError(f"Unknown lookup entity: {entity!r}")
        if not entity_id:
            raise ValueError("lookup requires id")
        internal, id_map = _LOOKUP_MAP[entity]
        internal_args = {param: entity_id for param in id_map}
        return internal, internal_args

    if meta_tool == "count":
        args = apply_entity_intent(question, args)
        entity = str(args.get("entity", "")).lower().strip()
        if not entity:
            raise ValueError("count requires entity (products, orders, reviews, or payments)")

        if entity == "products":
            return "count_products", _pick(args, "category")

        if entity == "reviews":
            internal_args = _pick(args, "city", "date_token", "score_max")
            if "score_max" not in internal_args:
                internal_args["score_max"] = 2
            return "count_low_reviews", internal_args

        if entity == "payments":
            if not args.get("payment_type"):
                raise ValueError("count entity=payments requires payment_type")
            return "count_by_payment_type", _pick(
                args, "payment_type", "state", "date_token"
            )

        # entity == orders
        if args.get("category"):
            return "count_by_category", _pick(
                args, "category", "state", "seller_id", "date_token"
            )
        if args.get("payment_type"):
            return "count_by_payment_type", _pick(
                args, "payment_type", "state", "date_token"
            )
        if args.get("status") and not args.get("city") and not args.get("state"):
            return "count_by_status", _pick(args, "status", "date_token")
        return "count_orders", _pick(
            args, "city", "state", "status", "date_token"
        )

    if meta_tool == "rank":
        args = apply_rank_defaults(question, args)
        entity = str(args.get("entity", "")).lower().strip()
        if not entity:
            raise ValueError("rank requires entity (products, categories, sellers, or customers)")
        return _resolve_rank(args)

    if meta_tool == "sum":
        args = apply_sum_defaults(question, args)
        measure = args.get("measure")
        if not measure:
            raise ValueError("sum requires measure")
        return _resolve_sum(args)

    if meta_tool == "list":
        entity = args.get("entity", "orders")
        if not entity:
            raise ValueError("list requires entity (orders or customer_orders)")
        return _resolve_list(args)

    if meta_tool == "breakdown":
        args = apply_breakdown_defaults(question, args)
        if not args.get("dimension"):
            raise ValueError("breakdown requires dimension")
        return _resolve_breakdown(args)

    if meta_tool == "compare":
        if not args.get("dimension"):
            raise ValueError("compare requires dimension (seller, category, or state)")
        return _resolve_compare(args)

    if meta_tool == "query":
        from config import settings

        if not settings.sql_escape_enabled:
            raise ValueError("SQL escape hatch is disabled")
        sql = args.get("sql")
        if not sql or not str(sql).strip():
            raise ValueError("query requires sql (a single SELECT statement)")
        return "run_readonly_sql", {"sql": str(sql).strip()}

    raise ValueError(f"Unknown meta tool: {meta_tool!r}")


def measure_for_tool(internal_tool: str) -> Optional[dict[str, str]]:
    """Return measure metadata for the API response, if defined."""
    pair = MEASURE_DEFINITIONS.get(internal_tool)
    if not pair:
        return None
    mid, definition = pair
    return {"id": mid, "definition": definition}
