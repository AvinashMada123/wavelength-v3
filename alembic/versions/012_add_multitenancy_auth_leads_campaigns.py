"""Add multi-tenancy: organizations, users, invites, leads, campaigns.

Creates new tables and adds org_id to existing tables.
All existing data is assigned to a default 'Freedom With AI' organization.

Revision ID: 012
Revises: 011
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None

# Fixed UUID for the default org so it's deterministic and referenceable
DEFAULT_ORG_ID = "00000000-0000-4000-a000-000000000001"
DEFAULT_ADMIN_ID = "00000000-0000-4000-a000-000000000002"


def upgrade() -> None:
    # === 1. Create organizations table ===
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), unique=True, nullable=False),
        sa.Column("plan", sa.Text(), nullable=False, server_default="free"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("usage", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # === 2. Create users table ===
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("email", sa.Text(), unique=True, nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="client_admin"),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)
    op.create_index("idx_users_org_id", "users", ["org_id"])

    # === 3. Create invites table ===
    op.create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("org_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="client_user"),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now() + interval '7 days'")),
    )
    op.create_index("idx_invites_email_org", "invites", ["email", "org_id"])

    # === 4. Create leads table ===
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("phone_number", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("custom_fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="new"),
        sa.Column("qualification_level", sa.Text(), nullable=True),
        sa.Column("qualification_confidence", sa.Float(), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_call_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("ghl_contact_id", sa.Text(), nullable=True),
        sa.Column("bot_notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_leads_org_id", "leads", ["org_id"])
    op.create_index("idx_leads_org_phone", "leads", ["org_id", "phone_number"])
    op.create_index("idx_leads_org_status", "leads", ["org_id", "status"])

    # === 5. Create campaigns table ===
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bot_config_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("total_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_campaigns_org_id", "campaigns", ["org_id"])
    op.create_index("idx_campaigns_status", "campaigns", ["status"])

    # === 6. Create campaign_leads table ===
    op.create_table(
        "campaign_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("call_log_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_campaign_leads_campaign", "campaign_leads", ["campaign_id"])
    op.create_index("idx_campaign_leads_status", "campaign_leads", ["campaign_id", "status"])

    # === 7. Insert default "Freedom With AI" organization ===
    op.execute(
        f"""
        INSERT INTO organizations (id, name, slug, plan, status)
        VALUES ('{DEFAULT_ORG_ID}', 'Freedom With AI', 'freedom-with-ai', 'enterprise', 'active')
        """
    )

    # Insert a placeholder admin user (password must be changed on first login)
    # bcrypt hash of 'changeme123' — user MUST change this
    op.execute(
        f"""
        INSERT INTO users (id, email, display_name, password_hash, role, org_id, status)
        VALUES (
            '{DEFAULT_ADMIN_ID}',
            'admin@freedomwithai.com',
            'Admin',
            '$2b$12$LJ3m4ys3Lk0TnYsWz8Qyf.sPBOmYqKJwGz0J4bVxQx4c4jUGXyHe',
            'super_admin',
            '{DEFAULT_ORG_ID}',
            'active'
        )
        """
    )

    # === 8. Add org_id to existing tables and backfill ===

    # bot_configs: add org_id (nullable first, backfill, then set NOT NULL)
    op.add_column("bot_configs", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(f"UPDATE bot_configs SET org_id = '{DEFAULT_ORG_ID}' WHERE org_id IS NULL")
    op.alter_column("bot_configs", "org_id", nullable=False)
    op.create_foreign_key("fk_bot_configs_org_id", "bot_configs", "organizations", ["org_id"], ["id"])
    op.create_index("idx_bot_configs_org_id", "bot_configs", ["org_id"])

    # call_logs: add org_id + lead_id
    op.add_column("call_logs", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("call_logs", sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(f"UPDATE call_logs SET org_id = '{DEFAULT_ORG_ID}' WHERE org_id IS NULL")
    op.alter_column("call_logs", "org_id", nullable=False)
    op.create_foreign_key("fk_call_logs_org_id", "call_logs", "organizations", ["org_id"], ["id"])
    op.create_index("idx_call_logs_org_id", "call_logs", ["org_id"])

    # call_queue: add org_id
    op.add_column("call_queue", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(f"UPDATE call_queue SET org_id = '{DEFAULT_ORG_ID}' WHERE org_id IS NULL")
    op.alter_column("call_queue", "org_id", nullable=False)
    op.create_foreign_key("fk_call_queue_org_id", "call_queue", "organizations", ["org_id"], ["id"])

    # call_analytics: add org_id
    op.add_column("call_analytics", sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute(f"UPDATE call_analytics SET org_id = '{DEFAULT_ORG_ID}' WHERE org_id IS NULL")
    op.alter_column("call_analytics", "org_id", nullable=False)


def downgrade() -> None:
    # Remove org_id from existing tables
    op.drop_column("call_analytics", "org_id")
    op.drop_column("call_queue", "org_id")
    op.drop_column("call_logs", "lead_id")
    op.drop_column("call_logs", "org_id")
    op.drop_column("bot_configs", "org_id")

    # Drop new tables (reverse order of creation)
    op.drop_table("campaign_leads")
    op.drop_table("campaigns")
    op.drop_table("leads")
    op.drop_table("invites")
    op.drop_table("users")
    op.drop_table("organizations")
