"""Enum validators — schema-aware.

Reads allowed values from the active SchemaConfig. Validation
behavior (case-insensitive normalize, ValidationError on miss) is
identical across schemas; the value set varies.
"""
import logging

from schemas import get_active_config

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


def _get_enum_values(name: str) -> set:
    """Return the active schema's allowed values for an enum, as a
    plain set. Raises KeyError if the schema doesn't define this enum."""
    cfg = get_active_config()
    values = cfg.get_enum(name)
    if values is None:
        # Schema marks this enum as freeform (e.g. Shopify's payment_type).
        return set()  # any value passes
    return set(values)


def validate_order_status(status: str) -> str:
    allowed = _get_enum_values("status")
    if not allowed:
        # Freeform: accept anything, normalized.
        return status.lower().strip()
    if status.lower() in allowed:
        return status.lower()
    raise ValidationError(
        f"Invalid order status '{status}'. Allowed: {', '.join(sorted(allowed))}"
    )


def validate_payment_type(payment_type: str) -> str:
    allowed = _get_enum_values("payment_type")
    if not allowed:
        return payment_type.lower().strip()
    if payment_type.lower() in allowed:
        return payment_type.lower()
    raise ValidationError(
        f"Invalid payment type '{payment_type}'. Allowed: {', '.join(sorted(allowed))}"
    )
