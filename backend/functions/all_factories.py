"""Central registry of all schema-aware function factories.

Imported by schemas/olist/config.py at startup. Keeps the per-schema
config readable while the catalog grows.
"""


def all_factories() -> tuple:
    from functions.comparative import (
        make_category_comparison,
        make_payment_type_breakdown,
        make_seller_comparison,
        make_state_comparison,
    )
    from functions.count_low_reviews import make_count_low_reviews
    from functions.count_orders import make_count_orders
    from functions.count_variants import (
        make_count_by_category,
        make_count_by_payment_type,
        make_count_by_status,
    )
    from functions.customer_analytics import (
        make_customer_cohort_analysis,
        make_customer_lifetime_value,
        make_customer_order_history,
        make_customers_by_city,
        make_repeat_customer_rate,
    )
    from functions.delivery_metrics import (
        make_average_delivery_days,
        make_fulfillment_status_breakdown,
        make_late_deliveries,
        make_on_time_delivery_rate,
    )
    from functions.entity_lookups import (
        make_get_customer_info,
        make_get_product_info,
        make_get_seller_info,
    )
    from functions.get_order_status import make_get_order_status
    from functions.get_revenue import make_get_revenue
    from functions.list_orders import make_list_orders
    from functions.product_analytics import (
        make_count_products,
        make_products_by_rating,
        make_top_categories,
    )
    from functions.quality_metrics import (
        make_average_rating_by_category,
        make_average_rating_by_product,
        make_average_rating_by_seller,
        make_review_score_distribution,
        make_review_sentiment_trend,
    )
    from functions.revenue_breakdowns import (
        make_revenue_by_category,
        make_revenue_by_payment_type,
        make_revenue_by_seller,
        make_revenue_by_state,
        make_revenue_by_trend,
    )
    from functions.seller_analytics import (
        make_seller_concentration,
        make_seller_metrics,
        make_sellers_by_state,
        make_top_sellers,
    )
    from functions.top_products import make_top_products
    from functions.sql_escape import make_run_readonly_sql

    return (
        # Original MVP (6)
        make_get_order_status,
        make_count_orders,
        make_get_revenue,
        make_count_low_reviews,
        make_top_products,
        make_list_orders,
        # Category A — entity lookups
        make_get_customer_info,
        make_get_product_info,
        make_get_seller_info,
        # Category B — count variants
        make_count_by_status,
        make_count_by_payment_type,
        make_count_by_category,
        # Category C — revenue breakdowns
        make_revenue_by_state,
        make_revenue_by_category,
        make_revenue_by_seller,
        make_revenue_by_payment_type,
        make_revenue_by_trend,
        # Category D — product performance
        make_count_products,
        make_top_categories,
        make_products_by_rating,
        # Category E — seller metrics
        make_top_sellers,
        make_seller_metrics,
        make_seller_concentration,
        make_sellers_by_state,
        # Category F — customer analytics
        make_customer_lifetime_value,
        make_repeat_customer_rate,
        make_customers_by_city,
        make_customer_order_history,
        make_customer_cohort_analysis,
        # Category G — quality metrics
        make_average_rating_by_product,
        make_average_rating_by_seller,
        make_average_rating_by_category,
        make_review_score_distribution,
        make_review_sentiment_trend,
        # Category H — delivery metrics
        make_on_time_delivery_rate,
        make_average_delivery_days,
        make_late_deliveries,
        make_fulfillment_status_breakdown,
        # Category I — comparative
        make_seller_comparison,
        make_category_comparison,
        make_state_comparison,
        make_payment_type_breakdown,
        # Phase 4 — SQL escape hatch
        make_run_readonly_sql,
    )
