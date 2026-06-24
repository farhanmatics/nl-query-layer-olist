"""
Function registry: maps tool names to executable handlers and JSON schemas.
"""

from functions import get_order_status, count_orders

FUNCTIONS = {
    "get_order_status": {
        "schema": get_order_status.SCHEMA,
        "execute": get_order_status.execute,
    },
    "count_orders": {
        "schema": count_orders.SCHEMA,
        "execute": count_orders.execute,
    },
}


def get_function(name: str):
    """Get a function handler by name. Raises KeyError if not found."""
    if name not in FUNCTIONS:
        raise KeyError(f"Unknown function: {name}")
    return FUNCTIONS[name]


def get_all_schemas():
    """Get JSON schemas for all registered functions."""
    return [FUNCTIONS[name]["schema"] for name in sorted(FUNCTIONS.keys())]


def list_functions():
    """List all registered function names."""
    return sorted(FUNCTIONS.keys())
