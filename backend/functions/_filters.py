"""Shared filter resolution for schema-aware function factories.

Centralizes city/state/status/date/category/payment_type validation and
builds parameterized SQL condition fragments for the orders↔customers path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from config import settings
from validation.cities import resolve_city
from validation.dates import parse_date_range
from validation.enums import ValidationError, validate_order_status, validate_payment_type


@dataclass
class FilterBuild:
    """Result of resolving optional filters into SQL fragments."""

    filters: dict = field(default_factory=dict)
    params: list = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    error: Optional[dict] = None

    def add_param(self, value) -> str:
        self.params.append(value)
        return f"${len(self.params)}"


async def resolve_order_filters(
    *,
    city: Optional[str] = None,
    state: Optional[str] = None,
    status: Optional[str] = None,
    date_token: Optional[str] = None,
    category: Optional[str] = None,
    payment_type: Optional[str] = None,
    seller_id: Optional[str] = None,
    col_city=None,
    col_state=None,
    col_status=None,
    col_purchase=None,
    col_payment_type=None,
    col_seller_id=None,
    alias_o: str = "o",
    alias_c: str = "c",
    alias_p: Optional[str] = None,
    alias_oi: Optional[str] = None,
    require_status: bool = False,
) -> FilterBuild:
    """Build filters/params/conditions for orders joined to customers.

    Optional aliases for payments (p) and order_items (oi) enable
    payment-type and seller-id filters when those joins are present.
    """
    out = FilterBuild()

    if city:
        try:
            normalized = await resolve_city(city)
            if not normalized:
                return FilterBuild(
                    error={
                        "error": f"City '{city}' not found in database",
                        "filters": {"city": city},
                    }
                )
            out.filters["city"] = normalized
            out.conditions.append(
                f"{alias_c}.{col_city.column} = {out.add_param(normalized)}"
            )
        except Exception as e:
            return FilterBuild(error={"error": f"City validation failed: {str(e)}", "filters": {}})

    if state:
        normalized_state = state.upper().strip()
        out.filters["state"] = normalized_state
        out.conditions.append(
            f"{alias_c}.{col_state.column} = {out.add_param(normalized_state)}"
        )

    if status:
        try:
            normalized_status = validate_order_status(status)
            out.filters["status"] = normalized_status
            out.conditions.append(
                f"{alias_o}.{col_status.column} = {out.add_param(normalized_status)}"
            )
        except ValidationError as e:
            return FilterBuild(error={"error": str(e), "filters": out.filters})

    elif require_status:
        return FilterBuild(
            error={"error": "status is required for this query", "filters": out.filters}
        )

    if date_token:
        try:
            date_range = parse_date_range(date_token, settings.reference_datetime)
            if date_range:
                out.filters["date_range"] = [
                    date_range[0].isoformat(),
                    date_range[1].isoformat(),
                ]
                out.conditions.append(
                    f"{alias_o}.{col_purchase.column} >= {out.add_param(date_range[0])}"
                )
                out.conditions.append(
                    f"{alias_o}.{col_purchase.column} <= {out.add_param(date_range[1])}"
                )
        except Exception as e:
            return FilterBuild(
                error={"error": f"Date validation failed: {str(e)}", "filters": out.filters}
            )

    if category:
        normalized_category = str(category).lower().strip().replace("_", " ")
        out.filters["category"] = normalized_category

    if payment_type and col_payment_type and alias_p:
        try:
            normalized_pt = validate_payment_type(payment_type)
            out.filters["payment_type"] = normalized_pt
            out.conditions.append(
                f"{alias_p}.{col_payment_type.column} = {out.add_param(normalized_pt)}"
            )
        except ValidationError as e:
            return FilterBuild(error={"error": str(e), "filters": out.filters})

    if seller_id and col_seller_id and alias_oi:
        sid = str(seller_id).strip()
        out.filters["seller_id"] = sid
        out.conditions.append(
            f"{alias_oi}.{col_seller_id.column} = {out.add_param(sid)}"
        )

    return out


def clamp_limit(limit, default: int = 10, max_limit: int = 25) -> int:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(max_limit, limit))


def where_clause(conditions: list[str]) -> str:
    return " AND ".join(["1=1"] + conditions) if conditions else "1=1"
