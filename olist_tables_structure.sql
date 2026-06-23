--
-- PostgreSQL database dump
--

\restrict I1v9BgiRMuH6GAXOB1jdxfmlWWveTDu3MlqqUDKGiX9uKdIZa8A6sAnrf89iXda

-- Dumped from database version 17.10 (Homebrew)
-- Dumped by pg_dump version 17.10 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: olist_customers_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_customers_dataset (
    customer_id text NOT NULL,
    customer_unique_id text,
    customer_zip_code_prefix text,
    customer_city text,
    customer_state text
);


--
-- Name: olist_geolocation_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_geolocation_dataset (
    geolocation_zip_code_prefix text,
    geolocation_lat double precision,
    geolocation_lng double precision,
    geolocation_city text,
    geolocation_state text
);


--
-- Name: olist_order_items_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_order_items_dataset (
    order_id text NOT NULL,
    order_item_id integer NOT NULL,
    product_id text,
    seller_id text,
    shipping_limit_date timestamp without time zone,
    price numeric(12,2),
    freight_value numeric(12,2)
);


--
-- Name: olist_order_payments_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_order_payments_dataset (
    order_id text NOT NULL,
    payment_sequential integer NOT NULL,
    payment_type text,
    payment_installments integer,
    payment_value numeric(12,2)
);


--
-- Name: olist_order_reviews_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_order_reviews_dataset (
    review_id text NOT NULL,
    order_id text NOT NULL,
    review_score integer,
    review_comment_title text,
    review_comment_message text,
    review_creation_date timestamp without time zone,
    review_answer_timestamp timestamp without time zone
);


--
-- Name: olist_orders_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_orders_dataset (
    order_id text NOT NULL,
    customer_id text,
    order_status text,
    order_purchase_timestamp timestamp without time zone,
    order_approved_at timestamp without time zone,
    order_delivered_carrier_date timestamp without time zone,
    order_delivered_customer_date timestamp without time zone,
    order_estimated_delivery_date timestamp without time zone
);


--
-- Name: olist_products_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_products_dataset (
    product_id text NOT NULL,
    product_category_name text,
    product_name_lenght integer,
    product_description_lenght integer,
    product_photos_qty integer,
    product_weight_g integer,
    product_length_cm integer,
    product_height_cm integer,
    product_width_cm integer
);


--
-- Name: olist_sellers_dataset; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.olist_sellers_dataset (
    seller_id text NOT NULL,
    seller_zip_code_prefix text,
    seller_city text,
    seller_state text
);


--
-- Name: product_category_name_translation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.product_category_name_translation (
    product_category_name text NOT NULL,
    product_category_name_english text
);


--
-- Name: olist_customers_dataset olist_customers_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_customers_dataset
    ADD CONSTRAINT olist_customers_dataset_pkey PRIMARY KEY (customer_id);


--
-- Name: olist_order_items_dataset olist_order_items_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_items_dataset
    ADD CONSTRAINT olist_order_items_dataset_pkey PRIMARY KEY (order_id, order_item_id);


--
-- Name: olist_order_payments_dataset olist_order_payments_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_payments_dataset
    ADD CONSTRAINT olist_order_payments_dataset_pkey PRIMARY KEY (order_id, payment_sequential);


--
-- Name: olist_order_reviews_dataset olist_order_reviews_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_reviews_dataset
    ADD CONSTRAINT olist_order_reviews_dataset_pkey PRIMARY KEY (review_id, order_id);


--
-- Name: olist_orders_dataset olist_orders_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_orders_dataset
    ADD CONSTRAINT olist_orders_dataset_pkey PRIMARY KEY (order_id);


--
-- Name: olist_products_dataset olist_products_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_products_dataset
    ADD CONSTRAINT olist_products_dataset_pkey PRIMARY KEY (product_id);


--
-- Name: olist_sellers_dataset olist_sellers_dataset_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_sellers_dataset
    ADD CONSTRAINT olist_sellers_dataset_pkey PRIMARY KEY (seller_id);


--
-- Name: product_category_name_translation product_category_name_translation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.product_category_name_translation
    ADD CONSTRAINT product_category_name_translation_pkey PRIMARY KEY (product_category_name);


--
-- Name: idx_olist_customers_unique_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_customers_unique_id ON public.olist_customers_dataset USING btree (customer_unique_id);


--
-- Name: idx_olist_geolocation_zip_code_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_geolocation_zip_code_prefix ON public.olist_geolocation_dataset USING btree (geolocation_zip_code_prefix);


--
-- Name: idx_olist_order_items_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_order_items_order_id ON public.olist_order_items_dataset USING btree (order_id);


--
-- Name: idx_olist_order_items_product_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_order_items_product_id ON public.olist_order_items_dataset USING btree (product_id);


--
-- Name: idx_olist_order_items_seller_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_order_items_seller_id ON public.olist_order_items_dataset USING btree (seller_id);


--
-- Name: idx_olist_order_payments_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_order_payments_order_id ON public.olist_order_payments_dataset USING btree (order_id);


--
-- Name: idx_olist_order_reviews_creation_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_order_reviews_creation_date ON public.olist_order_reviews_dataset USING btree (review_creation_date);


--
-- Name: idx_olist_order_reviews_order_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_order_reviews_order_id ON public.olist_order_reviews_dataset USING btree (order_id);


--
-- Name: idx_olist_orders_customer_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_orders_customer_id ON public.olist_orders_dataset USING btree (customer_id);


--
-- Name: idx_olist_orders_purchase_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_orders_purchase_timestamp ON public.olist_orders_dataset USING btree (order_purchase_timestamp);


--
-- Name: idx_olist_products_category_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_products_category_name ON public.olist_products_dataset USING btree (product_category_name);


--
-- Name: idx_olist_sellers_zip_code_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_olist_sellers_zip_code_prefix ON public.olist_sellers_dataset USING btree (seller_zip_code_prefix);


--
-- Name: olist_order_items_dataset olist_order_items_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_items_dataset
    ADD CONSTRAINT olist_order_items_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.olist_orders_dataset(order_id);


--
-- Name: olist_order_items_dataset olist_order_items_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_items_dataset
    ADD CONSTRAINT olist_order_items_product_id_fkey FOREIGN KEY (product_id) REFERENCES public.olist_products_dataset(product_id);


--
-- Name: olist_order_items_dataset olist_order_items_seller_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_items_dataset
    ADD CONSTRAINT olist_order_items_seller_id_fkey FOREIGN KEY (seller_id) REFERENCES public.olist_sellers_dataset(seller_id);


--
-- Name: olist_order_payments_dataset olist_order_payments_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_payments_dataset
    ADD CONSTRAINT olist_order_payments_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.olist_orders_dataset(order_id);


--
-- Name: olist_order_reviews_dataset olist_order_reviews_order_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_order_reviews_dataset
    ADD CONSTRAINT olist_order_reviews_order_id_fkey FOREIGN KEY (order_id) REFERENCES public.olist_orders_dataset(order_id);


--
-- Name: olist_orders_dataset olist_orders_customer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.olist_orders_dataset
    ADD CONSTRAINT olist_orders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.olist_customers_dataset(customer_id);


--
-- PostgreSQL database dump complete
--

\unrestrict I1v9BgiRMuH6GAXOB1jdxfmlWWveTDu3MlqqUDKGiX9uKdIZa8A6sAnrf89iXda

