# Conversion Workbench Module

## Purpose
The Conversion Workbench Module is responsible for tracking source-to-target conversion artifacts across the migration lifecycle.

It covers:
- conversion items per project
- generated artifact tracking
- review workflow states
- source and target mapping metadata

## Planned API Scope
- `GET /api/v1/conversion/items`
- `POST /api/v1/conversion/items`
- `GET /api/v1/conversion/items/{item_id}`
- `GET /api/v1/conversion/items/{item_id}/summary`

## Initial Strategy
The first implementation pass uses an in-memory store and seeded items so the module can be demonstrated before live code-generation logic is attached.
