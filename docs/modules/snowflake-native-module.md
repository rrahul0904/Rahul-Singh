# Snowflake Native Module

## Purpose
This module makes Snowflake a first-class runtime target inside the Unified Data Migration Accelerator.

## Capability areas
- connection and credential configuration
- warehouse / database / schema targeting
- internal Snowflake table destinations
- external cloud storage destinations for S3, Azure, and GCS
- Cortex-aligned text-to-SQL and AI workflow hooks
- destination deployment planning

## Product direction
This module is intended to support both:
- standard Snowflake-managed/internal destinations
- external-stage and external-storage style destinations

## Initial implementation strategy
The first implementation pass introduces configuration models, capability APIs, destination descriptors, and AI request scaffolding so the product shell has a real Snowflake integration surface.
