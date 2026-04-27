# Reference Integration Plan

UMA will use the uploaded reference repos as product patterns, not as blind code drops.

## ingestr-main

What we borrow:
- simple source → destination ingestion primitive
- connector-centric mental model
- repeatable CLI-like execution pattern

UMA adaptation:
- portal creates connections/jobs
- worker executes table movement
- Postgres → Snowflake proves the primitive first

## Snowflake Labs mcp-main

What we borrow:
- tool-oriented Snowflake operations
- explicit safety boundary around metadata and SQL actions

UMA adaptation:
- future AI/Cortex features should call approved tools for catalog, DDL export, validation, and semantic model generation
- AI should suggest changes, not apply production mutations without approval

## Product build order

1. Stabilize Docker/frontend/backend.
2. Prove Postgres → Snowflake.
3. Wire Migration Jobs UI to real execution.
4. Add validation.
5. Add incremental/watermark MERGE.
6. Add schema drift DDL generation.
7. Then integrate broader Snowflake Labs patterns.
