import { describe, expect, it } from "vitest";
import { aiPatchProposalAllowed, conversionDownloadAllowed, conversionQualityBlocks, modelIssueCards, readinessReason, validationCredentialsComplete } from "./MigrationControlPlanePage.jsx";

describe("conversion quality gate UI helpers", () => {
  it("hides the Snowflake package when the backend judge says the job is not ready", () => {
    expect(conversionDownloadAllowed({
      snowflake_ready: false,
      judge_status: "passed_with_warnings",
      rules_applied_count: 8,
      source_residue: [],
    })).toBe(false);

    expect(conversionDownloadAllowed({
      snowflake_ready: true,
      judge_status: "failed",
      rules_applied_count: 8,
      source_residue: [],
    })).toBe(false);

    expect(conversionDownloadAllowed({
      snowflake_ready: true,
      judge_status: "passed",
      rules_applied_count: 0,
      source_residue: [],
    })).toBe(false);

    expect(conversionDownloadAllowed({
      snowflake_ready: true,
      judge_status: "passed",
      rules_applied_count: 8,
      source_residue: ["DATE_SUB"],
    })).toBe(false);
  });

  it("allows the Snowflake package only when every quality gate passes", () => {
    expect(conversionDownloadAllowed({
      snowflake_ready: true,
      judge_status: "passed",
      rules_applied_count: 8,
      source_residue: [],
      validation_status: "validation_passed",
    })).toBe(true);
  });

  it("shows blocking quality reasons from backend job state", () => {
    const blocks = conversionQualityBlocks({
      snowflake_ready: false,
      judge_status: "failed",
      rules_applied_count: 0,
      source_residue: ["TIMESTAMP_TRUNC"],
    });

    expect(blocks).toContain("Snowflake-ready is false.");
    expect(blocks).toContain("Judge status is failed.");
    expect(blocks).toContain("No conversion rules were applied.");
    expect(blocks.join(" ")).toContain("TIMESTAMP_TRUNC");
  });

  it("explains Requires Review with structured dbt readiness reasons when residue is gone", () => {
    const state = {
      snowflake_ready: false,
      judge_status: "passed_with_warnings",
      manual_review_required: true,
      source_residue: [],
      readiness_reasons: [
        {
          category: "dbt_incremental",
          severity: "warning",
          message: "Incremental model requires review because unique_key was not confirmed.",
          recommended_action: "Add or confirm unique_key and incremental_strategy before Snowflake-ready approval.",
        },
      ],
    };

    expect(readinessReason(state, [])).toContain("SQL syntax conversion completed");
    expect(readinessReason(state, [])).toContain("unique_key was not confirmed");
  });

  it("renders dbt readiness reasons as issue cards", () => {
    const cards = modelIssueCards(
      {
        original_sql: "{{ config(materialized='incremental') }} select 1",
        rules_applied: ["TIMESTAMP_TRUNC->DATE_TRUNC"],
        source_residue: [],
        readiness_reasons: [
          {
            category: "dbt_incremental",
            severity: "warning",
            message: "Incremental model requires review because no is_incremental() filter or incremental_predicates were found.",
            recommended_action: "Add or confirm the incremental filter predicate.",
          },
        ],
      },
      { snowflake_ready: false, source_residue: [] },
    );

    expect(cards.map((card) => card.title)).toContain("Dbt Incremental");
    expect(cards.map((card) => card.detail).join(" ")).toContain("is_incremental");
  });

  it("disables AI patch proposal when no provider is configured", () => {
    expect(aiPatchProposalAllowed({ ai_provider_status: { ai_patch_available: false } })).toBe(false);
    expect(aiPatchProposalAllowed({ ai_provider_status: { ai_patch_available: true, provider_name: "openai" } })).toBe(true);
  });

  it("requires complete Snowflake validation credentials before enabling validation", () => {
    expect(validationCredentialsComplete({ account: "acct", user: "uma" })).toBe(false);
    expect(validationCredentialsComplete({
      account: "acct",
      user: "uma",
      password: "secret",
      role: "TRANSFORMER",
      warehouse: "COMPUTE_WH",
      database: "ANALYTICS",
      schema: "MARTS",
    })).toBe(true);
  });
});
