"""Add callback_schedule JSONB to bot_configs.

Revision ID: 031
Revises: 030
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "031"
down_revision = "030"


def upgrade():
    # Phase 1: Add new column
    op.add_column("bot_configs", sa.Column("callback_schedule", JSONB, nullable=True))

    # Phase 2: Migrate existing callback configs to new format
    # Use a FROM subquery to avoid aggregate-in-UPDATE error
    op.execute("""
        UPDATE bot_configs bc
        SET callback_schedule = jsonb_build_object(
            'template', 'custom',
            'steps', s.steps_arr
        )
        FROM (
            SELECT id,
                   jsonb_agg(jsonb_build_object('delay_hours', callback_retry_delay_hours))
                       AS steps_arr
            FROM bot_configs,
                 generate_series(1, callback_max_retries)
            WHERE callback_enabled = true
              AND callback_max_retries > 0
              AND callback_schedule IS NULL
            GROUP BY id
        ) s
        WHERE bc.id = s.id
    """)


def downgrade():
    op.drop_column("bot_configs", "callback_schedule")
