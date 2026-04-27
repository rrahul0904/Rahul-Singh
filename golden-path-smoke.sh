#!/usr/bin/env bash
set -euo pipefail

curl -sf http://localhost:8000/api/health >/dev/null

echo "API health OK"

docker exec -i uma-postgres psql -U uma -d uma <<'SQL'
CREATE SCHEMA IF NOT EXISTS demo_src;
DROP TABLE IF EXISTS demo_src.customers;
CREATE TABLE demo_src.customers (
  customer_id INTEGER PRIMARY KEY,
  first_name TEXT,
  last_name TEXT,
  email TEXT,
  status TEXT,
  updated_at TIMESTAMP NOT NULL DEFAULT now()
);
INSERT INTO demo_src.customers VALUES
(1, 'Rahul', 'Singh', 'rahul@example.com', 'active', now() - interval '3 days'),
(2, 'Anjali', 'Patel', 'anjali@example.com', 'active', now() - interval '2 days'),
(3, 'John', 'Miller', 'john@example.com', 'inactive', now() - interval '1 day'),
(4, 'Priya', 'Shah', 'priya@example.com', 'active', now())
ON CONFLICT (customer_id) DO NOTHING;
SELECT COUNT(*) AS demo_src_customers_count FROM demo_src.customers;
SQL

echo "Demo source created. Now create Postgres/Snowflake connections in UMA and run a job."
