import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


ORDER_STATUSES = {
    "delivered",
    "shipped",
    "canceled",
    "processing",
    "invoiced",
    "unavailable",
    "approved",
    "created",
}

PAYMENT_TYPES = {
    "credit_card",
    "boleto",
    "voucher",
    "debit_card",
    "not_defined",
}


def validate_order_status(status: str) -> str:
    if status.lower() in ORDER_STATUSES:
        return status.lower()
    raise ValidationError(
        f"Invalid order status '{status}'. Allowed: {', '.join(sorted(ORDER_STATUSES))}"
    )


def validate_payment_type(payment_type: str) -> str:
    if payment_type.lower() in PAYMENT_TYPES:
        return payment_type.lower()
    raise ValidationError(
        f"Invalid payment type '{payment_type}'. Allowed: {', '.join(sorted(PAYMENT_TYPES))}"
    )
