-- 0001_schema.sql
-- Olist schema: 8 dataset tables + geolocation, with primary keys, indexes, and
-- foreign keys. Idempotent: safe to run against an empty DB or one that already
-- has the tables (e.g. loaded from a pg_dump).

-- ---------------------------------------------------------------------------
-- Tables (primary keys declared inline so existing tables are left untouched)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.olist_customers_dataset (
    customer_id text PRIMARY KEY,
    customer_unique_id text,
    customer_zip_code_prefix text,
    customer_city text,
    customer_state text
);

CREATE TABLE IF NOT EXISTS public.olist_geolocation_dataset (
    geolocation_zip_code_prefix text,
    geolocation_lat double precision,
    geolocation_lng double precision,
    geolocation_city text,
    geolocation_state text
);

CREATE TABLE IF NOT EXISTS public.olist_orders_dataset (
    order_id text PRIMARY KEY,
    customer_id text,
    order_status text,
    order_purchase_timestamp timestamp without time zone,
    order_approved_at timestamp without time zone,
    order_delivered_carrier_date timestamp without time zone,
    order_delivered_customer_date timestamp without time zone,
    order_estimated_delivery_date timestamp without time zone
);

CREATE TABLE IF NOT EXISTS public.olist_products_dataset (
    product_id text PRIMARY KEY,
    product_category_name text,
    product_name_lenght integer,
    product_description_lenght integer,
    product_photos_qty integer,
    product_weight_g integer,
    product_length_cm integer,
    product_height_cm integer,
    product_width_cm integer
);

CREATE TABLE IF NOT EXISTS public.olist_sellers_dataset (
    seller_id text PRIMARY KEY,
    seller_zip_code_prefix text,
    seller_city text,
    seller_state text
);

CREATE TABLE IF NOT EXISTS public.olist_order_items_dataset (
    order_id text NOT NULL,
    order_item_id integer NOT NULL,
    product_id text,
    seller_id text,
    shipping_limit_date timestamp without time zone,
    price numeric(12,2),
    freight_value numeric(12,2),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE IF NOT EXISTS public.olist_order_payments_dataset (
    order_id text NOT NULL,
    payment_sequential integer NOT NULL,
    payment_type text,
    payment_installments integer,
    payment_value numeric(12,2),
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE TABLE IF NOT EXISTS public.olist_order_reviews_dataset (
    review_id text NOT NULL,
    order_id text NOT NULL,
    review_score integer,
    review_comment_title text,
    review_comment_message text,
    review_creation_date timestamp without time zone,
    review_answer_timestamp timestamp without time zone,
    PRIMARY KEY (review_id, order_id)
);

CREATE TABLE IF NOT EXISTS public.product_category_name_translation (
    product_category_name text PRIMARY KEY,
    product_category_name_english text
);

-- ---------------------------------------------------------------------------
-- Secondary indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_olist_customers_unique_id
    ON public.olist_customers_dataset USING btree (customer_unique_id);
CREATE INDEX IF NOT EXISTS idx_olist_geolocation_zip_code_prefix
    ON public.olist_geolocation_dataset USING btree (geolocation_zip_code_prefix);
CREATE INDEX IF NOT EXISTS idx_olist_order_items_order_id
    ON public.olist_order_items_dataset USING btree (order_id);
CREATE INDEX IF NOT EXISTS idx_olist_order_items_product_id
    ON public.olist_order_items_dataset USING btree (product_id);
CREATE INDEX IF NOT EXISTS idx_olist_order_items_seller_id
    ON public.olist_order_items_dataset USING btree (seller_id);
CREATE INDEX IF NOT EXISTS idx_olist_order_payments_order_id
    ON public.olist_order_payments_dataset USING btree (order_id);
CREATE INDEX IF NOT EXISTS idx_olist_order_reviews_creation_date
    ON public.olist_order_reviews_dataset USING btree (review_creation_date);
CREATE INDEX IF NOT EXISTS idx_olist_order_reviews_order_id
    ON public.olist_order_reviews_dataset USING btree (order_id);
CREATE INDEX IF NOT EXISTS idx_olist_orders_customer_id
    ON public.olist_orders_dataset USING btree (customer_id);
CREATE INDEX IF NOT EXISTS idx_olist_orders_purchase_timestamp
    ON public.olist_orders_dataset USING btree (order_purchase_timestamp);
CREATE INDEX IF NOT EXISTS idx_olist_products_category_name
    ON public.olist_products_dataset USING btree (product_category_name);
CREATE INDEX IF NOT EXISTS idx_olist_sellers_zip_code_prefix
    ON public.olist_sellers_dataset USING btree (seller_zip_code_prefix);

-- ---------------------------------------------------------------------------
-- Foreign keys (guarded so re-running never errors on existing constraints)
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'olist_order_items_order_id_fkey') THEN
        ALTER TABLE public.olist_order_items_dataset
            ADD CONSTRAINT olist_order_items_order_id_fkey
            FOREIGN KEY (order_id) REFERENCES public.olist_orders_dataset(order_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'olist_order_items_product_id_fkey') THEN
        ALTER TABLE public.olist_order_items_dataset
            ADD CONSTRAINT olist_order_items_product_id_fkey
            FOREIGN KEY (product_id) REFERENCES public.olist_products_dataset(product_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'olist_order_items_seller_id_fkey') THEN
        ALTER TABLE public.olist_order_items_dataset
            ADD CONSTRAINT olist_order_items_seller_id_fkey
            FOREIGN KEY (seller_id) REFERENCES public.olist_sellers_dataset(seller_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'olist_order_payments_order_id_fkey') THEN
        ALTER TABLE public.olist_order_payments_dataset
            ADD CONSTRAINT olist_order_payments_order_id_fkey
            FOREIGN KEY (order_id) REFERENCES public.olist_orders_dataset(order_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'olist_order_reviews_order_id_fkey') THEN
        ALTER TABLE public.olist_order_reviews_dataset
            ADD CONSTRAINT olist_order_reviews_order_id_fkey
            FOREIGN KEY (order_id) REFERENCES public.olist_orders_dataset(order_id);
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'olist_orders_customer_id_fkey') THEN
        ALTER TABLE public.olist_orders_dataset
            ADD CONSTRAINT olist_orders_customer_id_fkey
            FOREIGN KEY (customer_id) REFERENCES public.olist_customers_dataset(customer_id);
    END IF;
END $$;
