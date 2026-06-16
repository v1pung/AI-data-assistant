-- =============================================================================
-- Analytics schema (PostgreSQL)
-- =============================================================================
-- A compact but realistic e-commerce analytics model. Rich enough for
-- non-trivial questions: revenue by country/region, top products, category
-- performance, customer lifetime value, channel mix, review sentiment, etc.
--
-- Loaded automatically by the postgres container via
-- /docker-entrypoint-initdb.d (runs as the superuser POSTGRES_USER).
--
-- Layout:
--   regions < countries < customers
--                        < suppliers
--   categories (self-referencing) < products > suppliers
--   customers < orders < order_items > products
--                      < payments
--   products  < reviews > customers
-- =============================================================================

BEGIN;

-- Reference geography
CREATE TABLE regions (
    region_id   SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE countries (
    country_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    iso_code    CHAR(2) NOT NULL UNIQUE,
    region_id   INTEGER NOT NULL REFERENCES regions(region_id)
);

-- People and partners
CREATE TABLE customers (
    customer_id SERIAL PRIMARY KEY,
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    country_id  INTEGER NOT NULL REFERENCES countries(country_id),
    segment     TEXT NOT NULL CHECK (segment IN ('consumer', 'business', 'enterprise')),
    signup_date DATE NOT NULL
);

CREATE TABLE suppliers (
    supplier_id SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    country_id  INTEGER NOT NULL REFERENCES countries(country_id)
);

-- Catalog
CREATE TABLE categories (
    category_id        SERIAL PRIMARY KEY,
    name               TEXT NOT NULL,
    parent_category_id INTEGER REFERENCES categories(category_id)
);

CREATE TABLE products (
    product_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    unit_price  NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    cost        NUMERIC(10, 2) NOT NULL CHECK (cost >= 0),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE
);

-- Sales
CREATE TABLE orders (
    order_id    SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  DATE NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('completed', 'pending', 'cancelled', 'refunded')),
    channel     TEXT NOT NULL CHECK (channel IN ('web', 'mobile', 'store', 'partner'))
);

CREATE TABLE order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),  -- price at sale time
    discount      NUMERIC(4, 3) NOT NULL DEFAULT 0 CHECK (discount >= 0 AND discount < 1)
);

CREATE TABLE payments (
    payment_id   SERIAL PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(order_id),
    amount       NUMERIC(12, 2) NOT NULL CHECK (amount >= 0),
    payment_date DATE NOT NULL,
    method       TEXT NOT NULL CHECK (method IN ('card', 'paypal', 'bank_transfer', 'crypto')),
    status       TEXT NOT NULL CHECK (status IN ('captured', 'failed', 'refunded'))
);

CREATE TABLE reviews (
    review_id   SERIAL PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_date DATE NOT NULL
);

-- Column comments with allowed value sets
COMMENT ON COLUMN customers.segment  IS 'values: consumer, business, enterprise';
COMMENT ON COLUMN orders.status      IS 'values: completed, pending, cancelled, refunded';
COMMENT ON COLUMN orders.channel     IS 'values: web, mobile, store, partner';
COMMENT ON COLUMN payments.method    IS 'values: card, paypal, bank_transfer, crypto';
COMMENT ON COLUMN payments.status    IS 'values: captured, failed, refunded';
COMMENT ON COLUMN reviews.rating     IS 'integer 1..5 (1=worst, 5=best)';

-- Indexes for realistic query plans
CREATE INDEX idx_customers_country     ON customers(country_id);
CREATE INDEX idx_orders_customer       ON orders(customer_id);
CREATE INDEX idx_orders_date           ON orders(order_date);
CREATE INDEX idx_order_items_order     ON order_items(order_id);
CREATE INDEX idx_order_items_product   ON order_items(product_id);
CREATE INDEX idx_payments_order        ON payments(order_id);
CREATE INDEX idx_products_category     ON products(category_id);
CREATE INDEX idx_reviews_product       ON reviews(product_id);

COMMIT;

-- =============================================================================
-- Read-only application role (safety layer #3).
-- The service connects as this role, so it CANNOT write or change schema even
-- if the SQL guard and the read-only transaction were both bypassed.
-- Credentials here must match DATABASE_URL in docker-compose.yml / .env.
-- =============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'assistant_ro') THEN
        CREATE ROLE assistant_ro LOGIN PASSWORD 'assistant_ro';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE analytics TO assistant_ro;
GRANT USAGE ON SCHEMA public TO assistant_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO assistant_ro;
-- Tables created later (e.g. by seed) also become readable.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO assistant_ro;
