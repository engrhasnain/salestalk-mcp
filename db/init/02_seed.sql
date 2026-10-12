-- =============================================================================
-- Seed data for Dune & Dhow Trading Co. (fictional).
--
-- * RELATIVE TO TODAY: orders cover the 12 full months before the current month
--   plus the current month to date, so "last month", "this quarter" and
--   "last 30 days" always have data on the day you seed.
-- * DETERMINISTIC: every "random" value comes from md5(<label>-<n>) instead of
--   random(), so seeding on the same date always produces identical data and
--   the result does not depend on row evaluation order.
-- * RE-RUNNABLE: it truncates and refills the tables. To refresh the dates:
--     docker compose exec db psql -U salestalk_admin -d salestalk -f /docker-entrypoint-initdb.d/02_seed.sql
-- =============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- Deterministic pseudo-random number in [0, 1) from any text key (session-local helper).
CREATE OR REPLACE FUNCTION pg_temp.rnd(key text) RETURNS double precision
LANGUAGE sql IMMUTABLE AS $$
    SELECT ('x' || substr(md5(key), 1, 8))::bit(32)::bigint / 4294967296.0
$$;

TRUNCATE order_items, orders, customers, products, cities, dataset_info RESTART IDENTITY CASCADE;

CREATE TEMP TABLE seed_params ON COMMIT DROP AS
SELECT (date_trunc('month', CURRENT_DATE) - interval '12 months')::date AS start_date,
       CURRENT_DATE                                                  AS end_date,
       5000                                                          AS n_orders;

-- ----------------------------------------------------------------------------- cities
INSERT INTO cities (city_id, name, country, country_code) VALUES
    (1, 'Dubai',     'United Arab Emirates', 'AE'),
    (2, 'Abu Dhabi', 'United Arab Emirates', 'AE'),
    (3, 'Riyadh',    'Saudi Arabia',         'SA'),
    (4, 'Jeddah',    'Saudi Arabia',         'SA');

-- ----------------------------------------------------------------------------- products
-- max_qty / w_ae / w_sa only drive the generator (order size and popularity in UAE vs KSA).
CREATE TEMP TABLE seed_products (
    product_id int, sku text, name text, category text, unit text,
    unit_price numeric, unit_cost numeric, max_qty int, w_ae numeric, w_sa numeric
) ON COMMIT DROP;

INSERT INTO seed_products VALUES
    ( 1, 'DT-MED-1K',   'Medjool Dates Premium',          'Dates',        '1 kg box',     68,   41, 60, 6, 9),
    ( 2, 'DT-SUK-3K',   'Sukkari Dates Gift Box',         'Dates',        '3 kg box',     95,   55, 40, 4, 10),
    ( 3, 'DT-AJW-500',  'Ajwa Dates Al Madinah',          'Dates',        '500 g box',    85,   52, 40, 3, 8),
    ( 4, 'DT-KHL-5K',   'Khalas Dates Bulk Carton',       'Dates',        '5 kg carton', 120,   74, 30, 5, 7),
    ( 5, 'DT-STF-400',  'Almond-Stuffed Dates',           'Dates',        '400 g tin',    48,   27, 50, 5, 4),
    ( 6, 'DT-SYR-1L',   'Date Syrup (Dibs)',              'Dates',        '1 L bottle',   32,   17, 40, 3, 3),
    ( 7, 'CF-ARB-500',  'Arabic Coffee with Cardamom',    'Coffee & Tea', '500 g pack',   45,   24, 60, 7, 9),
    ( 8, 'CF-KHW-1K',   'Khawlani Green Coffee Beans',    'Coffee & Tea', '1 kg bag',    110,   66, 30, 3, 7),
    ( 9, 'CF-ESP-1K',   'Espresso Blend Roasted Beans',   'Coffee & Tea', '1 kg bag',     89,   51, 30, 6, 4),
    (10, 'CF-TRK-250',  'Turkish Coffee Fine Ground',     'Coffee & Tea', '250 g pack',   22,   12, 80, 4, 3),
    (11, 'TE-KRK-1K',   'Karak Tea Masala Mix',           'Coffee & Tea', '1 kg pack',    38,   19, 60, 6, 3),
    (12, 'TE-SAF-100',  'Saffron Tea Bags',               'Coffee & Tea', '100 bags',     55,   31, 40, 3, 3),
    (13, 'SP-SAF-10',   'Saffron Super Negin',            'Spices',       '10 g tin',    135,   88, 30, 4, 4),
    (14, 'SP-CRD-1K',   'Green Cardamom Pods',            'Spices',       '1 kg bag',    160,  102, 25, 4, 6),
    (15, 'SP-BHR-500',  'Baharat Seven-Spice Blend',      'Spices',       '500 g jar',    29,   13, 50, 4, 4),
    (16, 'SP-ZTR-500',  'Za''atar Premium Mix',           'Spices',       '500 g jar',    26,   12, 50, 4, 3),
    (17, 'SP-SMQ-500',  'Sumac Ground',                   'Spices',       '500 g jar',    24,   11, 40, 3, 2),
    (18, 'SP-TUR-1K',   'Turmeric Powder',                'Spices',       '1 kg bag',     21,    9, 50, 3, 3),
    (19, 'SP-KAB-1K',   'Kabsa Spice Mix',                'Spices',       '1 kg bag',     34,   16, 50, 2, 7),
    (20, 'TX-THB-25M',  'Thobe Fabric Roll',              'Textiles',     '25 m roll',   420,  265, 10, 2, 6),
    (21, 'TX-ABY-20M',  'Abaya Crepe Fabric Roll',        'Textiles',     '20 m roll',   380,  230, 10, 3, 4),
    (22, 'TX-PRG-01',   'Velvet Prayer Rug',              'Textiles',     'piece',        45,   22, 40, 3, 4),
    (23, 'TX-TWL-12',   'Egyptian Cotton Towels',         'Textiles',     'pack of 12',  160,   92, 20, 4, 3),
    (24, 'TX-BED-K',    'Linen Bedsheet Set King',        'Textiles',     'set',         210,  118, 15, 3, 2),
    (25, 'TX-SHM-01',   'Red Shemagh Cotton',             'Textiles',     'piece',        55,   28, 40, 1, 6),
    (26, 'EL-PHN-128',  'Smartphone 128 GB',              'Electronics',  'piece',      1450, 1210,  8, 5, 4),
    (27, 'EL-EBD-01',   'Wireless Earbuds Pro',           'Electronics',  'piece',       320,  225, 15, 6, 4),
    (28, 'EL-PWB-20K',  'Power Bank 20000 mAh',           'Electronics',  'piece',       110,   68, 25, 5, 4),
    (29, 'EL-TV-55',    '55-inch 4K Smart TV',            'Electronics',  'piece',      2100, 1720,  4, 3, 2),
    (30, 'EL-AFR-55',   'Digital Air Fryer 5.5 L',        'Electronics',  'piece',       289,  190, 12, 4, 4),
    (31, 'EL-SWT-01',   'Smart Watch Active',             'Electronics',  'piece',       499,  360, 10, 4, 3),
    (32, 'EL-LAP-14',   'Laptop 14-inch Core i5',         'Electronics',  'piece',      2899, 2450,  4, 3, 2),
    (33, 'FR-OUD-12',   'Cambodian Oud Oil',              'Fragrance',    '12 ml bottle', 380, 210, 12, 3, 4),
    (34, 'FR-BKH-50',   'Bakhoor Royal Blend',            'Fragrance',    '50 g box',     65,   30, 40, 5, 5),
    (35, 'FR-MBK-01',   'Electric Mabkhara Burner',       'Fragrance',    'piece',       120,   70, 15, 3, 3),
    (36, 'FR-RSW-1L',   'Taif Rose Water',                'Fragrance',    '1 L bottle',   28,   13, 40, 3, 4);

INSERT INTO products (product_id, sku, name, category, unit, unit_price, unit_cost)
SELECT product_id, sku, name, category, unit, unit_price, unit_cost FROM seed_products ORDER BY product_id;

-- Popularity CDF per country, used to pick a product for each order line.
CREATE TEMP TABLE seed_product_cdf ON COMMIT DROP AS
SELECT product_id, country_code, max_qty,
       coalesce(sum(w) OVER (PARTITION BY country_code ORDER BY product_id
                             ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
         / sum(w) OVER (PARTITION BY country_code) AS cum_lo,
       sum(w) OVER (PARTITION BY country_code ORDER BY product_id)
         / sum(w) OVER (PARTITION BY country_code) AS cum_hi
  FROM (SELECT product_id, 'AE' AS country_code, max_qty, w_ae::float8 AS w FROM seed_products
        UNION ALL
        SELECT product_id, 'SA', max_qty, w_sa::float8 FROM seed_products) s;

-- ----------------------------------------------------------------------------- customers
-- 30 name stems x 20 business types; (stem, type) pairs are unique for 320 customers.
INSERT INTO customers (customer_id, company_name, segment, city_id, contact_name, email, phone, created_at)
SELECT i + 1,
       stem || ' ' || btype,
       segment,
       city_id,
       first_name || ' ' || last_name,
       lower(first_name) || '.' || lower(regexp_replace(last_name, '[^A-Za-z]', '', 'g')) || '@'
         || trim(both '-' from regexp_replace(lower(stem || ' ' || btype), '[^a-z0-9]+', '-', 'g')) || '.example',
       CASE WHEN city_id IN (1, 2) THEN '+971 5' ELSE '+966 5' END
         || floor(pg_temp.rnd('c-ph1-' || i) * 9)::int || ' '
         || lpad(floor(pg_temp.rnd('c-ph2-' || i) * 1000)::int::text, 3, '0') || ' '
         || lpad(floor(pg_temp.rnd('c-ph3-' || i) * 10000)::int::text, 4, '0'),
       CASE WHEN i >= 290  -- the last 30 accounts were opened during the last year
            THEN p.start_date + floor(pg_temp.rnd('c-new-' || i) * (p.end_date - p.start_date) * 0.85)::int
            ELSE p.start_date - (20 + floor(pg_temp.rnd('c-age-' || i) * 1500)::int)
       END
  FROM generate_series(0, 319) AS i
 CROSS JOIN seed_params p
 CROSS JOIN LATERAL (
       SELECT (ARRAY['Al Noor', 'Al Barakah', 'Al Waha', 'Al Safa', 'Al Rawabi', 'Al Fajr', 'Al Khaleej',
                     'Al Ameen', 'Al Mubarak', 'Al Hilal', 'Al Yasmeen', 'Al Marjan', 'Al Sahraa', 'Al Bustan',
                     'Al Wafa', 'Al Reem', 'Al Nakheel', 'Al Thuraya', 'Al Majd', 'Al Diyafa', 'Golden Dune',
                     'Blue Lagoon', 'Desert Rose', 'Pearl Coast', 'Falcon Crest', 'Oasis Gate', 'Red Sea Breeze',
                     'Arabian Star', 'Silver Sands', 'Palm Grove'])[(i % 30) + 1] AS stem,
              ((i % 30) + 11 * (i / 30)) % 20 + 1 AS t
   ) n
 CROSS JOIN LATERAL (
       SELECT (ARRAY['Hypermarket', 'Supermarket', 'Mini Mart', 'Foodstuff Trading LLC', 'General Trading LLC',
                     'Import & Export', 'Restaurants', 'Hospitality Group', 'Catering Co.', 'Hotel Supplies',
                     'Department Store', 'Home & Living', 'Retail Group', 'Gifts & Hampers', 'Online Store',
                     'E-Shop', 'Holding Co.', 'Facilities Management', 'Trading Est.', 'Wholesale Market'])[n.t] AS btype,
              (ARRAY['Hypermarket', 'Supermarket', 'Supermarket', 'Wholesale', 'Wholesale',
                     'Wholesale', 'HoReCa', 'HoReCa', 'HoReCa', 'HoReCa',
                     'Retail', 'Retail', 'Retail', 'Retail', 'E-commerce',
                     'E-commerce', 'Corporate', 'Corporate', 'Wholesale', 'Wholesale'])[n.t] AS segment,
              CASE WHEN pg_temp.rnd('c-city-' || i) < 0.36 THEN 1   -- Dubai
                   WHEN pg_temp.rnd('c-city-' || i) < 0.53 THEN 2   -- Abu Dhabi
                   WHEN pg_temp.rnd('c-city-' || i) < 0.80 THEN 3   -- Riyadh
                   ELSE 4 END AS city_id,                          -- Jeddah
              (ARRAY['Omar', 'Fatima', 'Ahmed', 'Aisha', 'Khalid', 'Mariam', 'Yousef', 'Noura', 'Hassan', 'Layla',
                     'Saeed', 'Huda', 'Rashid', 'Sara', 'Faisal', 'Reem', 'Tariq', 'Hessa', 'Majid', 'Dana',
                     'Ali', 'Amna', 'Ibrahim', 'Salma'])[1 + floor(pg_temp.rnd('c-fn-' || i) * 24)::int] AS first_name,
              (ARRAY['Al Mansoori', 'Al Harbi', 'Al Qahtani', 'Al Shamsi', 'Al Otaibi', 'Al Ketbi', 'Al Ghamdi',
                     'Al Nuaimi', 'Al Zahrani', 'Al Suwaidi', 'Al Dosari', 'Al Mazrouei', 'Haddad', 'Khoury',
                     'Rahman', 'Siddiqui', 'Nair', 'Fernandes', 'Pillai', 'Qureshi'])[1 + floor(pg_temp.rnd('c-ln-' || i) * 20)::int] AS last_name
   ) a
 ORDER BY i;

-- ----------------------------------------------------------------------------- orders
-- 8,000 candidate dates; keep each with a probability shaped by season (Ramadan / winter
-- peaks, summer dip), weekday (Friday dip) and ~25% growth over the year; take the first 5,000.
CREATE TEMP TABLE seed_orders ON COMMIT DROP AS
WITH cand AS (
    SELECT n, p.start_date, p.end_date,
           p.start_date + floor(pg_temp.rnd('o-date-' || n) * (p.end_date - p.start_date + 1))::int AS d
      FROM generate_series(1, 8000) AS n
     CROSS JOIN seed_params p
)
SELECT n, d
  FROM cand
 WHERE pg_temp.rnd('o-keep-' || n) <
         (ARRAY[0.85, 0.95, 1.00, 0.80, 0.80, 0.75, 0.65, 0.70, 0.85, 0.90, 0.95, 1.00])[extract(month FROM d)::int]
       * CASE extract(isodow FROM d)::int WHEN 5 THEN 0.55 WHEN 6 THEN 0.85 ELSE 1.0 END
       * (0.80 + 0.20 * (d - start_date)::float8 / greatest(end_date - start_date, 1))
 ORDER BY n
 LIMIT (SELECT n_orders FROM seed_params);

INSERT INTO orders (order_id, order_number, customer_id, order_date, status, channel)
SELECT row_number() OVER (ORDER BY o.d, o.n)                                    AS order_id,
       'DD-' || to_char(o.d, 'YYYY') || '-' || lpad((row_number() OVER (ORDER BY o.d, o.n))::text, 6, '0'),
       -- big accounts order more (power law); a customer never orders before their account opened
       CASE WHEN c1.created_at <= o.d THEN c1.customer_id ELSE c2.customer_id END,
       o.d,
       CASE
           WHEN CURRENT_DATE - o.d <= 2 THEN
                CASE WHEN pg_temp.rnd('o-st-' || o.n) < 0.70 THEN 'processing' ELSE 'shipped' END
           WHEN CURRENT_DATE - o.d <= 7 THEN
                CASE WHEN pg_temp.rnd('o-st-' || o.n) < 0.05 THEN 'cancelled'
                     WHEN pg_temp.rnd('o-st-' || o.n) < 0.60 THEN 'shipped'
                     ELSE 'delivered' END
           ELSE CASE WHEN pg_temp.rnd('o-st-' || o.n) < 0.045 THEN 'cancelled'
                     WHEN pg_temp.rnd('o-st-' || o.n) < 0.080 THEN 'returned'
                     ELSE 'delivered' END
       END,
       CASE WHEN pg_temp.rnd('o-ch-' || o.n) < 0.45 THEN 'Sales rep'
            WHEN pg_temp.rnd('o-ch-' || o.n) < 0.75 THEN 'B2B portal'
            WHEN pg_temp.rnd('o-ch-' || o.n) < 0.85 THEN 'Phone'
            ELSE 'WhatsApp' END
  FROM seed_orders o
  JOIN customers c1 ON c1.customer_id = 1 + floor(320 * power(pg_temp.rnd('o-c1-' || o.n), 1.6))::int
  JOIN customers c2 ON c2.customer_id = 1 + floor(290 * power(pg_temp.rnd('o-c2-' || o.n), 1.6))::int
 ORDER BY 1;

-- ----------------------------------------------------------------------------- order_items
-- 1-5 lines per order; product drawn from the country's popularity CDF; quantity scaled by segment.
INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount_pct, line_total)
SELECT order_id, product_id, quantity, unit_price, discount_pct,
       round(quantity * unit_price * (1 - discount_pct / 100.0), 2)
  FROM (
        SELECT DISTINCT ON (o.order_id, cdf.product_id)
               o.order_id, line_no, cdf.product_id, p.unit_price,
               greatest(1, round((1 + power(pg_temp.rnd('l-q-' || o.order_id || '-' || line_no), 1.6) * cdf.max_qty)
                   * CASE c.segment WHEN 'Hypermarket' THEN 1.6 WHEN 'Wholesale' THEN 1.8 WHEN 'Supermarket' THEN 1.0
                                    WHEN 'HoReCa' THEN 0.8 WHEN 'Retail' THEN 0.7 WHEN 'E-commerce' THEN 0.9
                                    ELSE 0.6 END))::int AS quantity,
               CASE WHEN pg_temp.rnd('l-d-' || o.order_id || '-' || line_no) < 0.70 THEN 0
                    WHEN pg_temp.rnd('l-d-' || o.order_id || '-' || line_no) < 0.90 THEN 5
                    ELSE 10 END AS discount_pct
          FROM orders o
          JOIN customers c  ON c.customer_id = o.customer_id
          JOIN cities    ci ON ci.city_id    = c.city_id
         CROSS JOIN LATERAL generate_series(1, 1 + floor(power(pg_temp.rnd('o-lines-' || o.order_id), 1.4) * 5)::int) AS line_no
          JOIN seed_product_cdf cdf
            ON cdf.country_code = ci.country_code
           AND pg_temp.rnd('l-p-' || o.order_id || '-' || line_no) >= cdf.cum_lo
           AND pg_temp.rnd('l-p-' || o.order_id || '-' || line_no) <  cdf.cum_hi
          JOIN products p ON p.product_id = cdf.product_id
         ORDER BY o.order_id, cdf.product_id, line_no
       ) lines
 ORDER BY order_id, line_no;

UPDATE orders o
   SET total_amount = t.total
  FROM (SELECT order_id, sum(line_total) AS total FROM order_items GROUP BY order_id) t
 WHERE t.order_id = o.order_id;

-- ----------------------------------------------------------------------------- dataset_info
INSERT INTO dataset_info (key, value)
SELECT k, v FROM seed_params p, LATERAL (VALUES
    ('company',            'Dune & Dhow Trading Co. (fictional)'),
    ('headquarters',       'Dubai, United Arab Emirates'),
    ('currency',           'AED (all amounts)'),
    ('revenue_definition', 'Sum of orders.total_amount excluding cancelled and returned orders'),
    ('seeded_on',          CURRENT_DATE::text),
    ('orders_from',        p.start_date::text),
    ('orders_to',          p.end_date::text),
    ('note',               'All companies, people and figures are fictional demo data.')
) AS kv(k, v);

COMMIT;

ANALYZE;
