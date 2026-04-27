# UMA Golden Path: Postgres → Snowflake

This build standardizes UMA around the first product-proving path: local Postgres source → Snowflake target.

## Fixed in this package

- Frontend Docker no longer bind-mounts broken `node_modules`.
- Frontend no longer runs a runtime `npm install` loop.
- API/worker use the saved connection credentials from UMA instead of defaulting to local Postgres sockets.
- Real migration engine decrypts stored credentials before connecting.
- Postgres → Snowflake is the base path to test first.

## Start clean

```bash
docker compose down -v
docker compose build --no-cache
docker compose up -d
docker compose ps
```

Expected: `uma-api`, `uma-frontend`, `uma-worker`, `uma-postgres`, and `uma-redis` should be Up.

## Seed local Postgres demo source

```bash
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
SELECT COUNT(*) FROM demo_src.customers;
SQL
```

## Create connections in portal

### Postgres source

Type: `postgres`

Credentials:

```json
{
  "host": "postgres",
  "port": 5432,
  "database": "uma",
  "user": "uma",
  "password": "uma"
}
```

Config:

```json
{
  "sslmode": "disable"
}
```

### Snowflake target

Type: `snowflake`

Credentials:

```json
{
  "account": "<account_identifier>",
  "user": "<username>",
  "password": "<password>",
  "warehouse": "<warehouse>",
  "database": "<database>",
  "schema": "<schema>",
  "role": "<role>"
}
```

## Migration job mapping

- source dataset/schema: `demo_src`
- source table: `customers`
- target table: `DEMO_CUSTOMERS`
- load strategy: `full_load`
- task config:

```json
{
  "primary_key_columns": ["customer_id"],
  "watermark_column": "updated_at",
  "batch_size": 1000
}
```

## Snowflake verification

```sql
SELECT COUNT(*) FROM <schema>.DEMO_CUSTOMERS;
SELECT * FROM <schema>.DEMO_CUSTOMERS ORDER BY CUSTOMER_ID;
```

Expected seed count: `4`.

## Security note

Rotate any Snowflake password that was pasted into chat/logs before continuing.
