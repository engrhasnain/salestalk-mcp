-- =============================================================================
-- SalesTalk MCP demo database
-- "Dune & Dhow Trading Co." is a FICTIONAL Gulf trading company. All names,
-- people, emails and numbers are made up. Any resemblance is coincidental.
--
-- Currency: every amount is AED. Dune & Dhow is headquartered in Dubai and
-- invoices all customers (UAE and KSA) in AED.
-- =============================================================================

CREATE TABLE cities (
    city_id       smallint PRIMARY KEY,
    name          text     NOT NULL UNIQUE,
    country       text     NOT NULL,
    country_code  char(2)  NOT NULL
);

CREATE TABLE customers (
    customer_id   integer  PRIMARY KEY,
    company_name  text     NOT NULL UNIQUE,
    segment       text     NOT NULL CHECK (segment IN
                  ('Hypermarket', 'Supermarket', 'Wholesale', 'HoReCa', 'Retail', 'E-commerce', 'Corporate')),
    city_id       smallint NOT NULL REFERENCES cities (city_id),
    contact_name  text     NOT NULL,
    email         text     NOT NULL,
    phone         text     NOT NULL,
    created_at    date     NOT NULL
);

CREATE TABLE products (
    product_id    integer       PRIMARY KEY,
    sku           text          NOT NULL UNIQUE,
    name          text          NOT NULL,
    category      text          NOT NULL,
    unit          text          NOT NULL,
    unit_price    numeric(10,2) NOT NULL CHECK (unit_price > 0),
    unit_cost     numeric(10,2) NOT NULL CHECK (unit_cost > 0),
    is_active     boolean       NOT NULL DEFAULT true
);

CREATE TABLE orders (
    order_id      integer       PRIMARY KEY,
    order_number  text          NOT NULL UNIQUE,
    customer_id   integer       NOT NULL REFERENCES customers (customer_id),
    order_date    date          NOT NULL,
    status        text          NOT NULL CHECK (status IN ('processing', 'shipped', 'delivered', 'cancelled', 'returned')),
    channel       text          NOT NULL CHECK (channel IN ('Sales rep', 'B2B portal', 'Phone', 'WhatsApp')),
    total_amount  numeric(12,2) NOT NULL DEFAULT 0,
    currency      char(3)       NOT NULL DEFAULT 'AED' CHECK (currency = 'AED')
);

CREATE TABLE order_items (
    order_item_id integer       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id      integer       NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id    integer       NOT NULL REFERENCES products (product_id),
    quantity      integer       NOT NULL CHECK (quantity > 0),
    unit_price    numeric(10,2) NOT NULL,
    discount_pct  numeric(4,1)  NOT NULL DEFAULT 0 CHECK (discount_pct BETWEEN 0 AND 50),
    line_total    numeric(12,2) NOT NULL
);

CREATE TABLE dataset_info (
    key    text PRIMARY KEY,
    value  text NOT NULL
);

CREATE INDEX orders_order_date_idx     ON orders (order_date);
CREATE INDEX orders_customer_id_idx    ON orders (customer_id);
CREATE INDEX order_items_order_id_idx  ON order_items (order_id);
CREATE INDEX order_items_product_idx   ON order_items (product_id);
CREATE INDEX customers_city_id_idx     ON customers (city_id);

-- One row per order line of revenue-generating orders, already joined. Handy for ad-hoc SQL.
CREATE VIEW v_sales AS
SELECT o.order_id,
       o.order_number,
       o.order_date,
       date_trunc('month', o.order_date)::date AS order_month,
       o.status,
       o.channel,
       c.customer_id,
       c.company_name AS customer,
       c.segment,
       ci.name        AS city,
       ci.country,
       p.product_id,
       p.sku,
       p.name         AS product,
       p.category,
       oi.quantity,
       oi.unit_price,
       oi.discount_pct,
       oi.line_total  AS revenue,
       round(oi.quantity * p.unit_cost, 2) AS cost
  FROM order_items oi
  JOIN orders    o  ON o.order_id    = oi.order_id
  JOIN customers c  ON c.customer_id = o.customer_id
  JOIN cities    ci ON ci.city_id    = c.city_id
  JOIN products  p  ON p.product_id  = oi.product_id
 WHERE o.status NOT IN ('cancelled', 'returned');

-- Descriptions are surfaced to Claude by list_tables / describe_table.
COMMENT ON TABLE cities       IS 'Cities where Dune & Dhow has customers (UAE and Saudi Arabia).';
COMMENT ON TABLE customers    IS 'B2B customers (fictional companies), each based in one city.';
COMMENT ON TABLE products     IS 'Product catalogue with list price and unit cost in AED.';
COMMENT ON TABLE orders       IS 'Customer orders. total_amount (AED) = sum of order_items.line_total. Revenue excludes cancelled and returned orders.';
COMMENT ON TABLE order_items  IS 'Order lines: quantity x unit_price minus discount = line_total (AED).';
COMMENT ON TABLE dataset_info IS 'Facts about this demo dataset (company, currency, date coverage, revenue definition).';
COMMENT ON VIEW  v_sales      IS 'One row per order line for revenue-generating orders, joined with customer, city and product. revenue and cost are AED.';

COMMENT ON COLUMN customers.segment      IS 'Hypermarket, Supermarket, Wholesale, HoReCa (hotels/restaurants/cafes), Retail, E-commerce or Corporate.';
COMMENT ON COLUMN customers.created_at   IS 'Date the customer account was opened.';
COMMENT ON COLUMN products.category      IS 'Dates, Coffee & Tea, Spices, Textiles, Electronics or Fragrance.';
COMMENT ON COLUMN products.unit          IS 'Selling unit, e.g. "1 kg box" or "piece".';
COMMENT ON COLUMN products.unit_price    IS 'Current list price per unit in AED.';
COMMENT ON COLUMN products.unit_cost     IS 'Landed cost per unit in AED (for margin).';
COMMENT ON COLUMN orders.status          IS 'processing, shipped, delivered, cancelled or returned. Revenue excludes cancelled and returned.';
COMMENT ON COLUMN orders.channel         IS 'How the order was placed: Sales rep, B2B portal, Phone or WhatsApp.';
COMMENT ON COLUMN orders.total_amount    IS 'Order total in AED after line discounts.';
COMMENT ON COLUMN orders.currency        IS 'Always AED.';
COMMENT ON COLUMN order_items.unit_price IS 'Price per unit charged on this line (AED, before discount).';
COMMENT ON COLUMN order_items.discount_pct IS 'Line discount in percent (0, 5 or 10).';
COMMENT ON COLUMN order_items.line_total IS 'quantity * unit_price * (1 - discount_pct/100), AED.';
