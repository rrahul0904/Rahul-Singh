"""agentic orchestrator tables

Revision ID: 0008_agentic_orchestrator
Revises: 0007_run_events_schema_drift
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_agentic_orchestrator"
down_revision = "0007_run_events_schema_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("run_type", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("request_text", sa.Text(), nullable=True),
        sa.Column("source_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("target_connection_id", sa.String(), sa.ForeignKey("connections.id"), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("migration_type", sa.String(length=80), nullable=True),
        sa.Column("schemas", sa.JSON(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=True),
        sa.Column("current_step", sa.String(length=120), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    for col in ("project_id", "user_id", "run_type", "status", "source_connection_id", "target_connection_id"):
        op.create_index(f"ix_agent_runs_{col}", "agent_runs", [col])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("step_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "step_name", "status"):
        op.create_index(f"ix_agent_steps_{col}", "agent_steps", [col])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("step_id", sa.String(), sa.ForeignKey("agent_steps.id"), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("permission", sa.String(length=40), nullable=True),
        sa.Column("input_json", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "step_id", "tool_name", "permission", "status"):
        op.create_index(f"ix_agent_tool_calls_{col}", "agent_tool_calls", [col])

    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("step_id", sa.String(), sa.ForeignKey("agent_steps.id"), nullable=True),
        sa.Column("approval_type", sa.String(length=80), nullable=True),
        sa.Column("requested_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("approval_payload", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "step_id", "approval_type", "status"):
        op.create_index(f"ix_agent_approvals_{col}", "agent_approvals", [col])

    op.create_table(
        "ddl_conversion_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("source_object_name", sa.String(length=512), nullable=False),
        sa.Column("source_object_type", sa.String(length=80), nullable=True),
        sa.Column("source_dialect", sa.String(length=80), nullable=True),
        sa.Column("target_dialect", sa.String(length=80), nullable=True),
        sa.Column("original_ddl", sa.Text(), nullable=True),
        sa.Column("converted_ddl", sa.Text(), nullable=True),
        sa.Column("conversion_confidence", sa.Float(), nullable=True),
        sa.Column("unsupported_features", sa.JSON(), nullable=True),
        sa.Column("manual_review_required", sa.Boolean(), nullable=True),
        sa.Column("review_status", sa.String(length=40), nullable=True),
        sa.Column("execution_status", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    for col in ("run_id", "source_object_name", "review_status", "execution_status"):
        op.create_index(f"ix_ddl_conversion_results_{col}", "ddl_conversion_results", [col])


def downgrade() -> None:
    op.drop_table("ddl_conversion_results")
    op.drop_table("agent_approvals")
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
