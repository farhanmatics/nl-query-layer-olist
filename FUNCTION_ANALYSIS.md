# Function Analysis — Olist Database

Comprehensive analysis of queryable dimensions, aggregate measures, and practical functions we can build.

---

## Schema Overview

**8 Core Tables with Star Schema around `olist_orders_dataset`:**

```
                    ┌─ olist_customers_dataset (city, state)
                    │
olist_orders_dataset ─┼─ olist_order_items_dataset (product_id, seller_id)
                    │  │   ├─ olist_products_dataset (category)
                    │  │   │  └─ product_category_name_translation (PT→EN)
                    │  │   └─ olist_sellers_dataset (seller city, state)
                    │
                    ├─ olist_order_payments_dataset (payment_type, payment_value)
                    │
                    └─ olist_order_reviews_dataset (review_score, review_date)
```

---

## Key Dimensions (GROUP BY candidates)

| Dimension | Table | Values |
|-----------|-------|--------|
| **Order Status** | orders | delivered, shipped, canceled, processing, invoiced, unavailable, approved, created |
| **Customer City** | customers | ~5,000 unique cities in Brazil |
| **Customer State** | customers | 27 Brazilian states (UFs) |
| **Seller State** | sellers | 27 states |
| **Product Category** | products | ~70 Portuguese categories → translated to English |
| **Payment Type** | payments | credit_card, boleto, voucher, debit_card, not_defined |
| **Review Score** | reviews | 1, 2, 3, 4, 5 |
| **Time (Month)** | orders | order_purchase_timestamp → monthly buckets (Sept 2016 – Oct 2018) |

---

## Key Measures (Aggregates)

| Measure | Query Pattern | Notes |
|---------|---------------|-------|
| **Order Count** | `COUNT(DISTINCT order_id)` | Core metric — from orders table |
| **Revenue** | `SUM(payment_value)` | From payments table |
| **Average Rating** | `AVG(review_score)` | From reviews table |
| **Unique Customers** | `COUNT(DISTINCT customer_id)` | Customer count in filtered set |
| **Unique Sellers** | `COUNT(DISTINCT seller_id)` | Seller count in filtered set |
| **Unique Products** | `COUNT(DISTINCT product_id)` | Product count in filtered set |
| **Avg Items/Order** | `AVG(items_per_order)` | Subquery: items from order_items |
| **Avg Delivery Days** | `AVG(delivered_date - purchase_date)` | Only for delivered orders |

---

## Function Categories & Queryable Shapes

### Category A: Single Entity Lookups (ID-based)

**Return a single row with details about one entity.**

1. **`get_order_status(order_id: str)`**
   - Returns: order status, dates (purchase, delivered, estimated)
   - Joins: orders → customers (for city/state context)
   - Q: "What is the status of order abc123?"

2. **`get_customer_info(customer_id: str)`**
   - Returns: city, state, order count, total spent, avg rating received
   - Joins: customers → orders → payments/reviews
   - Q: "Tell me about customer XYZ"

3. **`get_product_info(product_id: str)`**
   - Returns: category (English), seller, avg rating, order count, total revenue
   - Joins: products → translation, order_items → reviews
   - Q: "What is product ABC? How is it selling?"

4. **`get_seller_info(seller_id: str)`**
   - Returns: city, state, products, order count, revenue, avg rating
   - Joins: sellers → order_items → orders/reviews
   - Q: "Show me metrics for seller XYZ"

---

### Category B: Filtered Counts (Multiple dimension filters)

**Count orders/reviews with optional filters on city, state, status, category, date range.**

5. **`count_orders(city?, state?, status?, date_range?)`** ✅ Phase 0
   - Filters: customer_city, customer_state, order_status, order_purchase_timestamp
   - Joins: orders → customers
   - Q: "How many delivered orders in São Paulo last month?"

6. **`count_by_status(status, date_range?)`**
   - Filters: order_status, date range
   - Q: "How many orders are currently processing?"

7. **`count_by_payment_type(payment_type, state?, date_range?)`**
   - Filters: payment_type, state, date range
   - Q: "How many credit card payments did we get in June?"

8. **`count_low_reviews(score_max=2, city?, seller_id?, date_range?)`** ✅ Phase 0
   - Filters: review_score ≤ threshold, city, seller, date range
   - Joins: reviews → orders → customers/items
   - Q: "How many low-scored reviews did we get last month?"

9. **`count_by_category(category, state?, seller_id?, date_range?)`**
   - Filters: product_category_name, state, seller, date range
   - Q: "How many electronics were ordered in São Paulo last quarter?"

---

### Category C: Revenue/Financial Aggregates

**Sum payment values with optional grouping or filtering.**

10. **`get_revenue(date_range?, state?, category?, seller_id?)`** ✅ Phase 0
    - Measure: SUM(payment_value)
    - Filters: date, state, category, seller
    - Q: "What was our total revenue last month?"

11. **`revenue_by_state(date_range?)`**
    - Measure: SUM(payment_value) GROUP BY customer_state
    - Returns: Top 10–15 states by revenue
    - Q: "Which states gave us the most revenue last month?"

12. **`revenue_by_category(date_range?, limit=10)`**
    - Measure: SUM(payment_value) GROUP BY product_category
    - Returns: Top categories + English names
    - Q: "What categories are our top revenue drivers?"

13. **`revenue_by_seller(date_range?, state?, limit=10)`**
    - Measure: SUM(payment_value) GROUP BY seller_id
    - Returns: Top sellers with names/locations
    - Q: "Who are our top 10 sellers by revenue?"

14. **`revenue_by_payment_type(date_range?)`**
    - Measure: SUM(payment_value) GROUP BY payment_type
    - Returns: Revenue by credit_card, boleto, etc.
    - Q: "How much revenue came from credit cards vs. boleto?"

15. **`revenue_trend(granularity='month', date_range?)`**
    - Measure: SUM(payment_value) GROUP BY DATE_TRUNC('month', order_purchase_timestamp)
    - Returns: Time series of monthly revenue
    - Q: "Show me our revenue trend over the past year"

---

### Category D: Product/Category Performance

**Rank products or categories by count, revenue, or rating.**

16. **`top_products(date_range?, limit=10, by='count'|'revenue')`** ✅ Phase 0
    - Measure: COUNT(orders) or SUM(revenue) GROUP BY product_id
    - Returns: Top N products with English names, categories
    - Q: "What are our best-selling products?"

17. **`top_categories(date_range?, limit=10, by='count'|'revenue')`**
    - Measure: COUNT(orders) or SUM(revenue) GROUP BY category
    - Returns: Top categories
    - Q: "Which product categories sell the most units?"

18. **`products_by_rating(category?, limit=20, min_reviews=10)`**
    - Measure: AVG(review_score) GROUP BY product_id
    - Filters: category, min reviews (to avoid noise)
    - Returns: Highest/lowest rated products
    - Q: "What products have the best customer ratings?"

---

### Category E: Seller & Marketplace Metrics

**Analyze seller performance, concentration, distribution.**

19. **`top_sellers(date_range?, state?, limit=10, by='revenue'|'orders')`**
    - Measure: SUM(revenue) or COUNT(orders) GROUP BY seller_id
    - Returns: Top sellers with location info
    - Q: "Who are our top sellers?"

20. **`seller_metrics(seller_id, date_range?)`**
    - Returns: # orders, revenue, # products, avg rating, cities served
    - Joins: complex (sellers → items → orders/reviews/products)
    - Q: "How is seller ABC performing?"

21. **`seller_concentration(date_range?)`**
    - Measure: revenue per seller
    - Returns: Gini coefficient or top-10 % of revenue (concentration metric)
    - Q: "Is our seller base concentrated or distributed?"

22. **`sellers_by_state(date_range?)`**
    - Measure: COUNT(orders) or SUM(revenue) GROUP BY seller_state
    - Returns: State distribution
    - Q: "Which states have the most sellers?"

---

### Category F: Customer Analytics

**Understand customer behavior, value, and engagement.**

23. **`customer_lifetime_value(state?, city?, min_orders=1)`**
    - Measure: SUM(payment_value) GROUP BY customer_id
    - Returns: Top customers by LTV
    - Q: "Who are our most valuable customers?"

24. **`repeat_customer_rate(date_range?)`**
    - Measure: COUNT(customers with >1 order) / COUNT(unique customers)
    - Returns: % repeat customers, avg orders per customer
    - Q: "What % of customers buy more than once?"

25. **`customers_by_city(date_range?, limit=10)`**
    - Measure: COUNT(orders) GROUP BY customer_city
    - Returns: Cities with most customers
    - Q: "Which cities have the most customers?"

26. **`customer_order_history(customer_id)`**
    - Returns: All orders for a customer (with status, revenue, date)
    - Joins: customers → orders → items/payments/reviews
    - Q: "Show me all orders for customer XYZ"

27. **`customer_cohort_analysis(cohort_date_range, metric='revenue'|'retention')`**
    - Measure: Track customer cohorts over time
    - Complex — group by first order month, track LTV over subsequent months
    - Q: "How do customers acquired in January perform vs. February?"

---

### Category G: Quality & Satisfaction Metrics

**Review scores, ratings, disputes, satisfaction trends.**

28. **`average_rating_by_product(category?, limit=20)`**
    - Measure: AVG(review_score) GROUP BY product_id
    - Returns: Product ratings
    - Q: "Which products have the best ratings?"

29. **`average_rating_by_seller(state?, limit=10)`**
    - Measure: AVG(review_score) GROUP BY seller_id
    - Returns: Seller ratings
    - Q: "Which sellers have the best ratings?"

30. **`average_rating_by_category()`**
    - Measure: AVG(review_score) GROUP BY category
    - Returns: Category ratings
    - Q: "Which product categories are most satisfying?"

31. **`review_score_distribution(date_range?, state?, seller_id?)`**
    - Measure: COUNT(*) GROUP BY review_score (1–5)
    - Returns: Histogram of ratings
    - Q: "How many 5-star vs. 1-star reviews did we get?"

32. **`review_sentiment_trend(date_range?, granularity='month')`**
    - Measure: AVG(review_score) GROUP BY DATE_TRUNC('month', review_creation_date)
    - Returns: Satisfaction trend over time
    - Q: "Is customer satisfaction improving or declining?"

---

### Category H: Delivery & Performance Metrics

**On-time delivery, delivery time analysis, fulfillment metrics.**

33. **`on_time_delivery_rate(state?, date_range?)`**
    - Measure: COUNT(delivered_date ≤ estimated_date) / COUNT(all delivered)
    - Filters: only orders with order_status='delivered'
    - Q: "What % of orders are delivered on time?"

34. **`average_delivery_days(state?, category?, seller_id?, date_range?)`**
    - Measure: AVG(delivered_date - purchase_date)
    - Filters: only delivered orders
    - Q: "How long does delivery take on average?"

35. **`late_deliveries(days_late=5, state?, date_range?)`**
    - Measure: COUNT(*) WHERE delivered_date > estimated_date + days_late
    - Returns: # orders with late deliveries (>N days)
    - Q: "How many orders were more than 5 days late?"

36. **`fulfillment_status_breakdown(date_range?)`**
    - Measure: COUNT(*) GROUP BY order_status
    - Returns: Count in each status (delivered, shipped, canceled, etc.)
    - Q: "How many orders are in each status right now?"

---

### Category I: Comparative & Dimensional Analysis

**Compare two entities or drill across dimensions.**

37. **`seller_comparison(seller_ids: list, date_range?)`**
    - Measure: # orders, revenue, avg rating for each seller
    - Returns: Side-by-side metrics
    - Q: "Compare sellers A, B, and C"

38. **`category_comparison(categories: list, date_range?)`**
    - Measure: # orders, revenue, avg rating for each category
    - Q: "How do Electronics and Books compare?"

39. **`state_comparison(states: list, date_range?)`**
    - Measure: # orders, revenue, avg rating by state
    - Q: "Which state has better customer satisfaction: SP or RJ?"

40. **`payment_type_breakdown(date_range?)`**
    - Measure: COUNT(*) GROUP BY payment_type + SUM(revenue)
    - Returns: # orders and revenue by payment method
    - Q: "What is the breakdown of payment methods?"

---

## Summary: Function Count by Type

| Category | Count | Examples |
|----------|-------|----------|
| **A: Entity Lookups** | 4 | order_status, customer_info, product_info, seller_info |
| **B: Filtered Counts** | 5 | count_orders, count_by_status, count_low_reviews, etc. |
| **C: Revenue Aggregates** | 6 | get_revenue, revenue_by_state, revenue_by_category, etc. |
| **D: Product Performance** | 3 | top_products, top_categories, products_by_rating |
| **E: Seller Metrics** | 4 | top_sellers, seller_metrics, seller_concentration, sellers_by_state |
| **F: Customer Analytics** | 5 | customer_lifetime_value, repeat_customer_rate, customer_order_history, etc. |
| **G: Quality Metrics** | 5 | average_rating_by_product, review_sentiment_trend, etc. |
| **H: Delivery Metrics** | 4 | on_time_delivery_rate, average_delivery_days, late_deliveries, etc. |
| **I: Comparative** | 4 | seller_comparison, category_comparison, state_comparison, etc. |
| **TOTAL** | **40** | |

---

## Recommended MVP (Phase 0 + Phase 1)

**Phase 0 (Vertical Slice)**
- ✅ `get_order_status` (A1)
- ✅ `count_orders` (B1)

**Phase 1 (Full MVP — 12–16 functions)**
Core functions that cover 80% of use cases:
1. `get_order_status` (lookup)
2. `count_orders` (flagship: count with filters)
3. `get_revenue` (revenue)
4. `count_low_reviews` (disputes analog)
5. `top_products` (rankings)
6. `list_orders` (paginated list)
7. `revenue_by_state` (geographic breakdown)
8. `revenue_by_category` (category analysis)
9. `top_sellers` (seller rankings)
10. `average_rating_by_product` (quality)
11. `customer_lifetime_value` (customer segment)
12. `fulfillment_status_breakdown` (operational)

**Optional Phase 1 additions** (if time permits):
13. `top_categories`
14. `on_time_delivery_rate`
15. `review_sentiment_trend`
16. `seller_metrics`

**Phase 2+ (Beyond MVP)**
- Customer cohort analysis
- Seller concentration metrics
- Delivery time analysis by dimension
- Repeat customer rate
- All comparative functions

---

## Design Patterns

All 40 functions fall into 5 repeatable query patterns:

### Pattern 1: Single-Row Lookups
```sql
SELECT ... WHERE id = $1
```
Functions: get_order_status, get_customer_info, etc. (4 functions)

### Pattern 2: Filtered COUNT
```sql
SELECT COUNT(*) FROM orders
JOIN customers ON ...
WHERE (filter1) AND (filter2) AND (date range)
```
Functions: count_orders, count_low_reviews, count_by_status, etc. (5 functions)

### Pattern 3: Filtered SUM (Revenue)
```sql
SELECT SUM(payment_value) FROM payments
JOIN orders ON ...
WHERE (filters) AND (date range)
```
Functions: get_revenue, revenue_by_state, revenue_by_category, etc. (6 functions)

### Pattern 4: GROUP BY + ORDER BY DESC (Rankings)
```sql
SELECT entity_id, COUNT(*)|SUM(revenue)|AVG(rating)
FROM ... GROUP BY entity_id
ORDER BY aggregate DESC
LIMIT N
```
Functions: top_products, top_sellers, products_by_rating, etc. (12 functions)

### Pattern 5: GROUP BY + Histogram
```sql
SELECT dimension, COUNT(*), SUM(revenue)
FROM ... GROUP BY dimension
ORDER BY aggregate DESC
```
Functions: review_score_distribution, fulfillment_status_breakdown, payment_type_breakdown, etc. (10+ functions)

These patterns are so consistent that once we build 2–3 examples, the rest are rote SQL.

---

## Which Functions to Implement First?

**Tier 1 (Phase 0): Proof of Concept**
1. `get_order_status` — simplest, one-row lookup
2. `count_orders` — flagship, validates JOIN + filtering + date handling

**Tier 2 (Phase 1): MVP Depth**
3. `get_revenue` — revenue pattern
4. `count_low_reviews` — multi-table JOIN + aggregate
5. `top_products` — ranking + translation join
6. `list_orders` — pagination pattern
7. `revenue_by_state` — GROUP BY pattern
8. `top_sellers` — seller metrics

**Tier 3 (Phase 1+): Quality/Operational**
9. `average_rating_by_product`
10. `fulfillment_status_breakdown`
11. `customer_lifetime_value`
12. `on_time_delivery_rate`

This progression: (1) proves the loop, (2) covers core use cases, (3) adds observability.
