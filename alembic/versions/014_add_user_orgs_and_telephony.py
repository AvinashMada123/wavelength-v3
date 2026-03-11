"""Add user_orgs junction table, phone_numbers table, org-level telephony credentials.

Revision ID: 014
Revises: 013
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. user_orgs junction table ---
    op.create_table(
        "user_orgs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="client_user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "org_id", name="uq_user_orgs_user_org"),
    )
    op.create_index("idx_user_orgs_user_id", "user_orgs", ["user_id"])
    op.create_index("idx_user_orgs_org_id", "user_orgs", ["org_id"])

    # Backfill from existing users
    op.execute(
        "INSERT INTO user_orgs (user_id, org_id, role) "
        "SELECT id, org_id, role FROM users"
    )

    # --- 2. Add telephony credentials to organizations ---
    op.add_column("organizations", sa.Column("plivo_auth_id", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("plivo_auth_token", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("twilio_account_sid", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("twilio_auth_token", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("ghl_api_key", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("ghl_location_id", sa.Text(), nullable=True))

    # Backfill org telephony from first active bot per org
    op.execute("""
        UPDATE organizations o
        SET plivo_auth_id = sub.plivo_auth_id,
            plivo_auth_token = sub.plivo_auth_token,
            twilio_account_sid = sub.twilio_account_sid,
            twilio_auth_token = sub.twilio_auth_token,
            ghl_api_key = sub.ghl_api_key,
            ghl_location_id = sub.ghl_location_id
        FROM (
            SELECT DISTINCT ON (org_id)
                org_id, plivo_auth_id, plivo_auth_token,
                twilio_account_sid, twilio_auth_token,
                ghl_api_key, ghl_location_id
            FROM bot_configs
            WHERE is_active = true
            ORDER BY org_id, created_at ASC
        ) sub
        WHERE o.id = sub.org_id
    """)

    # --- 3. phone_numbers table ---
    op.create_table(
        "phone_numbers",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default="plivo"),
        sa.Column("phone_number", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_phone_numbers_org_id", "phone_numbers", ["org_id"])

    # Backfill phone numbers from bot_configs (unique per org+provider+number)
    # Plivo numbers
    op.execute("""
        INSERT INTO phone_numbers (org_id, provider, phone_number, label, is_default)
        SELECT DISTINCT ON (org_id, plivo_caller_id)
            org_id, 'plivo', plivo_caller_id, 'Main', true
        FROM bot_configs
        WHERE plivo_caller_id IS NOT NULL AND plivo_caller_id != '' AND is_active = true
        ORDER BY org_id, plivo_caller_id, created_at ASC
    """)
    # Twilio numbers
    op.execute("""
        INSERT INTO phone_numbers (org_id, provider, phone_number, label, is_default)
        SELECT DISTINCT ON (org_id, twilio_phone_number)
            org_id, 'twilio', twilio_phone_number, 'Main', false
        FROM bot_configs
        WHERE twilio_phone_number IS NOT NULL AND twilio_phone_number != '' AND is_active = true
        ORDER BY org_id, twilio_phone_number, created_at ASC
    """)

    # --- 4. Add phone_number_id to bot_configs ---
    op.add_column("bot_configs", sa.Column("phone_number_id", UUID(as_uuid=True), sa.ForeignKey("phone_numbers.id"), nullable=True))

    # Link bots to their migrated phone numbers
    op.execute("""
        UPDATE bot_configs b
        SET phone_number_id = p.id
        FROM phone_numbers p
        WHERE b.org_id = p.org_id
          AND p.provider = 'plivo'
          AND b.plivo_caller_id = p.phone_number
          AND b.plivo_caller_id IS NOT NULL
          AND b.plivo_caller_id != ''
    """)
    # For twilio bots
    op.execute("""
        UPDATE bot_configs b
        SET phone_number_id = COALESCE(b.phone_number_id, p.id)
        FROM phone_numbers p
        WHERE b.org_id = p.org_id
          AND p.provider = 'twilio'
          AND b.twilio_phone_number = p.phone_number
          AND b.twilio_phone_number IS NOT NULL
          AND b.twilio_phone_number != ''
          AND b.telephony_provider = 'twilio'
    """)

    # --- 5. Make bot_config telephony columns nullable ---
    op.alter_column("bot_configs", "plivo_auth_id", existing_type=sa.Text(), nullable=True)
    op.alter_column("bot_configs", "plivo_auth_token", existing_type=sa.Text(), nullable=True)
    op.alter_column("bot_configs", "plivo_caller_id", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("bot_configs", "plivo_caller_id", existing_type=sa.Text(), nullable=False)
    op.alter_column("bot_configs", "plivo_auth_token", existing_type=sa.Text(), nullable=False)
    op.alter_column("bot_configs", "plivo_auth_id", existing_type=sa.Text(), nullable=False)
    op.drop_column("bot_configs", "phone_number_id")
    op.drop_table("phone_numbers")
    op.drop_column("organizations", "ghl_location_id")
    op.drop_column("organizations", "ghl_api_key")
    op.drop_column("organizations", "twilio_auth_token")
    op.drop_column("organizations", "twilio_account_sid")
    op.drop_column("organizations", "plivo_auth_token")
    op.drop_column("organizations", "plivo_auth_id")
    op.drop_table("user_orgs")
