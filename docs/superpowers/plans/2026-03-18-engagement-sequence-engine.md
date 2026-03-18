# Engagement Sequence Engine Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-tenant engagement sequence engine that replaces n8n + GHL workflows with native Wavelength support for configurable touchpoint sequences across WhatsApp, voice calls, and SMS channels.

**Architecture:** 5 new DB tables (messaging_providers, sequence_templates, sequence_steps, sequence_instances, sequence_touchpoints), 4 new backend services (AnthropicClient, MessagingClient, SequenceEngine, SequenceScheduler), REST API for template management + monitoring + prompt testing + JSON import/export, and 6 new frontend pages. Each sequence step can use a different bot (voice_bot_id per step), enabling multi-bot flows mixed with messaging touchpoints.

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, Anthropic Python SDK, aiohttp (WATI/AISensy), Next.js 14, Shadcn UI, Tailwind CSS, Fernet encryption (cryptography lib)

**Spec:** `docs/superpowers/specs/2026-03-18-engagement-sequence-engine-design.md`

---

## File Structure

### New Files (Backend)
| File | Responsibility |
|------|---------------|
| `alembic/versions/025_add_engagement_sequences.py` | Migration: 5 new tables + indexes + constraints |
| `app/models/messaging_provider.py` | MessagingProvider SQLAlchemy model |
| `app/models/sequence.py` | SequenceTemplate, SequenceStep, SequenceInstance, SequenceTouchpoint models |
| `app/services/credential_encryption.py` | Fernet encrypt/decrypt for messaging provider credentials |
| `app/services/anthropic_client.py` | Claude API wrapper for copywriting + prompt testing |
| `app/services/messaging_client.py` | Multi-provider WhatsApp/SMS delivery (WATI, AISensy, Twilio) |
| `app/services/sequence_engine.py` | Core sequence logic: trigger evaluation, instance creation, touchpoint processing, reply handling |
| `app/services/sequence_scheduler.py` | Background poller that fires due touchpoints |
| `app/api/sequences.py` | REST API: templates, steps, instances, touchpoints, import/export, prompt testing |
| `app/api/messaging_providers.py` | REST API: messaging provider CRUD + test connection |
| `app/api/webhooks.py` | WhatsApp reply webhook endpoint |
| `tests/test_sequence_engine.py` | Unit tests for sequence engine logic |
| `tests/test_credential_encryption.py` | Unit tests for Fernet encryption |
| `tests/test_anthropic_client.py` | Unit tests for prompt interpolation |
| `tests/test_sequence_scheduler.py` | Unit tests for scheduler logic |

### New Files (Frontend)
| File | Responsibility |
|------|---------------|
| `frontend/src/lib/sequences-api.ts` | API functions for sequence endpoints |
| `frontend/src/lib/messaging-api.ts` | API functions for messaging provider endpoints |
| `frontend/src/app/(app)/sequences/page.tsx` | Sequence templates list page |
| `frontend/src/app/(app)/sequences/[id]/page.tsx` | Template builder page |
| `frontend/src/app/(app)/sequences/monitor/page.tsx` | Engagement monitor dashboard |
| `frontend/src/app/(app)/sequences/components/StepCard.tsx` | Expandable step card component |
| `frontend/src/app/(app)/sequences/components/PromptTestPanel.tsx` | Slide-over prompt testing panel |
| `frontend/src/app/(app)/sequences/components/TouchpointTimeline.tsx` | Visual touchpoint timeline |
| `frontend/src/app/(app)/sequences/components/ImportExportDialog.tsx` | JSON import/export modal |
| `frontend/src/app/(app)/settings/messaging/page.tsx` | Messaging providers settings page |
| `frontend/src/app/(app)/leads/components/SequencesTab.tsx` | Lead detail sequences tab |
| `tests/test_sequence_scheduler.py` | Unit tests for scheduler retry logic |

### Modified Files
| File | Change |
|------|--------|
| `app/config.py` | Add ANTHROPIC_API_KEY, MESSAGING_CREDENTIALS_KEY env vars |
| `app/main.py` | Start/stop SequenceScheduler in lifespan |
| `app/plivo/routes.py` | Add post-call hook for sequence trigger (~line 702) |
| `app/twilio/routes.py` | Same post-call hook for Twilio calls |
| `app/services/billing.py` | Add `bill_ai_usage()` function |
| `frontend/src/app/(app)/layout.tsx` | Add "Sequences" nav item to sidebar |
| `frontend/src/app/(app)/leads/[leadId]/page.tsx` | Add "Sequences" tab |

---

## Task 1: Config + Credential Encryption

**Files:**
- Modify: `app/config.py`
- Create: `app/services/credential_encryption.py`
- Create: `tests/test_credential_encryption.py`

- [ ] **Step 1: Add env vars to config**

In `app/config.py`, add to the Settings class:
```python
# Anthropic (for sequence copywriting)
ANTHROPIC_API_KEY: str = ""

# Messaging provider credential encryption
MESSAGING_CREDENTIALS_KEY: str = ""  # Fernet key, generate with: from cryptography.fernet import Fernet; Fernet.generate_key()
```

- [ ] **Step 2: Write credential encryption tests**

Create `tests/test_credential_encryption.py`:
```python
import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))

from cryptography.fernet import Fernet

# Generate a test key
TEST_KEY = Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip():
    from app.services.credential_encryption import encrypt_credentials, decrypt_credentials

    creds = {"api_url": "https://live-server-123.wati.io", "api_token": "Bearer abc123"}
    encrypted = encrypt_credentials(creds, TEST_KEY)
    assert isinstance(encrypted, str)
    assert "abc123" not in encrypted  # Must not be plaintext

    decrypted = decrypt_credentials(encrypted, TEST_KEY)
    assert decrypted == creds


def test_encrypt_empty_dict():
    from app.services.credential_encryption import encrypt_credentials, decrypt_credentials

    encrypted = encrypt_credentials({}, TEST_KEY)
    assert decrypt_credentials(encrypted, TEST_KEY) == {}


def test_decrypt_with_wrong_key_raises():
    from app.services.credential_encryption import encrypt_credentials, decrypt_credentials

    encrypted = encrypt_credentials({"key": "val"}, TEST_KEY)
    wrong_key = Fernet.generate_key().decode()
    try:
        decrypt_credentials(encrypted, wrong_key)
        assert False, "Should have raised"
    except Exception:
        pass
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_credential_encryption.py -v`
Expected: FAIL (module not found)

- [ ] **Step 4: Implement credential encryption**

Create `app/services/credential_encryption.py`:
```python
"""Fernet-based encryption for messaging provider credentials."""

import json
from cryptography.fernet import Fernet


def encrypt_credentials(creds: dict, key: str) -> str:
    """Encrypt a credentials dict to a Fernet token string."""
    f = Fernet(key.encode() if isinstance(key, str) else key)
    plaintext = json.dumps(creds).encode()
    return f.encrypt(plaintext).decode()


def decrypt_credentials(encrypted: str, key: str) -> dict:
    """Decrypt a Fernet token string back to a credentials dict."""
    f = Fernet(key.encode() if isinstance(key, str) else key)
    plaintext = f.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted)
    return json.loads(plaintext)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_credential_encryption.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add app/config.py app/services/credential_encryption.py tests/test_credential_encryption.py
git commit -m "feat(sequences): add config vars and credential encryption service"
```

---

## Task 2: Database Models

**Files:**
- Create: `app/models/messaging_provider.py`
- Create: `app/models/sequence.py`

- [ ] **Step 1: Create MessagingProvider model**

Create `app/models/messaging_provider.py`:
```python
"""Messaging provider model — per-org WhatsApp/SMS credentials."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class MessagingProvider(Base):
    __tablename__ = "messaging_providers"
    __table_args__ = (
        Index("ix_msgprov_org", "org_id"),
        Index("ix_msgprov_org_type", "org_id", "provider_type"),
        Index(
            "ix_msgprov_org_default",
            "org_id",
            unique=False,
            postgresql_where=text("is_default = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)  # wati, aisensy, twilio_whatsapp, twilio_sms
    name: Mapped[str] = mapped_column(Text, nullable=False)
    credentials: Mapped[str] = mapped_column(Text, nullable=False)  # Fernet-encrypted JSON string
    is_default: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)
```

- [ ] **Step 2: Create Sequence models**

Create `app/models/sequence.py`:
```python
"""Sequence engine models — templates, steps, instances, touchpoints."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class SequenceTemplate(Base):
    __tablename__ = "sequence_templates"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_seqtemplate_org_name"),
        Index("ix_seqtemplate_org", "org_id"),
        Index("ix_seqtemplate_bot_active", "bot_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)  # post_call, manual, campaign_complete
    trigger_conditions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    max_active_per_lead: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)


class SequenceStep(Base):
    __tablename__ = "sequence_steps"
    __table_args__ = (
        UniqueConstraint("template_id", "step_order", name="uq_seqstep_template_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_templates.id", ondelete="RESTRICT"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)  # whatsapp_template, whatsapp_session, voice_call, sms
    timing_type: Mapped[str] = mapped_column(Text, nullable=False)  # relative_to_signup, relative_to_event, relative_to_previous_step
    timing_value: Mapped[dict] = mapped_column(JSONB, nullable=False)  # { hours: 1 } or { days: -1, time: "18:30" }
    skip_conditions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)  # static_template, ai_generated, voice_call
    whatsapp_template_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_template_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ai_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(Text, nullable=True)  # claude-sonnet, claude-haiku
    voice_bot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bot_configs.id"), nullable=True
    )
    expects_reply: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    reply_handler: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)


class SequenceInstance(Base):
    __tablename__ = "sequence_instances"
    __table_args__ = (
        Index("ix_seqinst_lead", "lead_id"),
        Index("ix_seqinst_org_status", "org_id", "status"),
        Index("ix_seqinst_template_status", "template_id", "status"),
        # Note: partial unique index uq_seqinst_active_per_lead (WHERE status='active')
        # is created in migration raw SQL only — cannot be expressed as SQLAlchemy constraint
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_templates.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    trigger_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_logs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))  # active, completed, paused, cancelled
    context_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)


class SequenceTouchpoint(Base):
    __tablename__ = "sequence_touchpoints"
    __table_args__ = (
        Index("ix_seqtp_instance_order", "instance_id", "step_order"),
        Index("ix_seqtp_lead_status", "lead_id", "status"),
        Index("ix_seqtp_org_status_scheduled", "org_id", "status", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_instances.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_steps.id", ondelete="SET NULL"), nullable=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_snapshot: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    session_window_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    messaging_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messaging_providers.id"), nullable=True
    )
    queued_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_queue.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=datetime.utcnow)
```

- [ ] **Step 3: Commit models**

```bash
git add app/models/messaging_provider.py app/models/sequence.py
git commit -m "feat(sequences): add SQLAlchemy models for sequence engine"
```

---

## Task 3: Alembic Migration

**Files:**
- Create: `alembic/versions/025_add_engagement_sequences.py`

- [ ] **Step 1: Write migration**

Create `alembic/versions/025_add_engagement_sequences.py`:
```python
"""Add engagement sequence engine tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    # --- messaging_providers ---
    op.create_table(
        "messaging_providers",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("credentials", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_msgprov_org", "messaging_providers", ["org_id"])
    op.create_index("ix_msgprov_org_type", "messaging_providers", ["org_id", "provider_type"])

    # --- sequence_templates ---
    op.create_table(
        "sequence_templates",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("bot_id", UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("trigger_conditions", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("max_active_per_lead", sa.Integer(), server_default=sa.text("1")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_seqtemplate_org_name", "sequence_templates", ["org_id", "name"])
    op.create_index("ix_seqtemplate_org", "sequence_templates", ["org_id"])
    op.create_index("ix_seqtemplate_bot_active", "sequence_templates", ["bot_id", "is_active"])

    # --- sequence_steps ---
    op.create_table(
        "sequence_steps",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("sequence_templates.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("timing_type", sa.Text(), nullable=False),
        sa.Column("timing_value", JSONB(), nullable=False),
        sa.Column("skip_conditions", JSONB(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("whatsapp_template_name", sa.Text(), nullable=True),
        sa.Column("whatsapp_template_params", JSONB(), nullable=True),
        sa.Column("ai_prompt", sa.Text(), nullable=True),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("voice_bot_id", UUID(as_uuid=True), sa.ForeignKey("bot_configs.id"), nullable=True),
        sa.Column("expects_reply", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("reply_handler", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_seqstep_template_order", "sequence_steps", ["template_id", "step_order"])

    # --- sequence_instances ---
    op.create_table(
        "sequence_instances",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("template_id", UUID(as_uuid=True), sa.ForeignKey("sequence_templates.id"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("trigger_call_id", UUID(as_uuid=True), sa.ForeignKey("call_logs.id"), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'")),
        sa.Column("context_data", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_seqinst_lead", "sequence_instances", ["lead_id"])
    op.create_index("ix_seqinst_org_status", "sequence_instances", ["org_id", "status"])
    op.create_index("ix_seqinst_template_status", "sequence_instances", ["template_id", "status"])
    # Partial unique index: only one active instance per template+lead
    op.execute(
        "CREATE UNIQUE INDEX uq_seqinst_active_per_lead "
        "ON sequence_instances (template_id, lead_id) "
        "WHERE status = 'active'"
    )

    # --- sequence_touchpoints ---
    op.create_table(
        "sequence_touchpoints",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", UUID(as_uuid=True), sa.ForeignKey("sequence_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("sequence_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("org_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_snapshot", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("reply_response", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("2")),
        sa.Column("messaging_provider_id", UUID(as_uuid=True), sa.ForeignKey("messaging_providers.id"), nullable=True),
        sa.Column("queued_call_id", UUID(as_uuid=True), sa.ForeignKey("call_queue.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_seqtp_instance_order", "sequence_touchpoints", ["instance_id", "step_order"])
    op.create_index("ix_seqtp_lead_status", "sequence_touchpoints", ["lead_id", "status"])
    op.create_index("ix_seqtp_org_status_scheduled", "sequence_touchpoints", ["org_id", "status", "scheduled_at"])


def downgrade():
    op.drop_table("sequence_touchpoints")
    op.execute("DROP INDEX IF EXISTS uq_seqinst_active_per_lead")
    op.drop_table("sequence_instances")
    op.drop_table("sequence_steps")
    op.drop_table("sequence_templates")
    op.drop_table("messaging_providers")
```

- [ ] **Step 2: Run migration**

Run: `cd "/Users/animeshmahato/Wavelength v3" && alembic upgrade head`
Expected: 5 tables created successfully

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/025_add_engagement_sequences.py
git commit -m "feat(sequences): add database migration for 5 sequence engine tables"
```

---

## Task 4: Anthropic Client Service

**Files:**
- Create: `app/services/anthropic_client.py`
- Create: `tests/test_anthropic_client.py`

- [ ] **Step 1: Write tests for prompt interpolation and content generation**

Create `tests/test_anthropic_client.py`:
```python
import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))


def test_interpolate_variables():
    from app.services.anthropic_client import _interpolate_variables

    prompt = "Hello {{name}}, you are a {{profession}} who {{challenge}}."
    variables = {"name": "Amuthan", "profession": "software engineer", "challenge": "wants to learn AI"}
    result = _interpolate_variables(prompt, variables)
    assert result == "Hello Amuthan, you are a software engineer who wants to learn AI."


def test_interpolate_missing_variable_left_as_is():
    from app.services.anthropic_client import _interpolate_variables

    prompt = "Hello {{name}}, your score is {{score}}."
    variables = {"name": "Amuthan"}
    result = _interpolate_variables(prompt, variables)
    assert result == "Hello Amuthan, your score is {{score}}."


def test_interpolate_empty_variables():
    from app.services.anthropic_client import _interpolate_variables

    result = _interpolate_variables("No vars here", {})
    assert result == "No vars here"


def test_extract_variable_names():
    from app.services.anthropic_client import extract_variable_names

    prompt = "{{name}} is a {{profession}} from {{city}}. {{name}} again."
    names = extract_variable_names(prompt)
    assert names == {"name", "profession", "city"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_anthropic_client.py -v`

- [ ] **Step 3: Implement Anthropic client**

Create `app/services/anthropic_client.py`:
```python
"""Claude API wrapper for sequence copywriting and prompt testing."""

import re
import time

import anthropic
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

MODEL_MAP = {
    "claude-sonnet": "claude-sonnet-4-20250514",
    "claude-haiku": "claude-haiku-4-5-20251001",
}

# Cost per 1M tokens (USD) — update as pricing changes
COST_PER_1M_INPUT = {"claude-sonnet": 3.00, "claude-haiku": 0.80}
COST_PER_1M_OUTPUT = {"claude-sonnet": 15.00, "claude-haiku": 4.00}


def _interpolate_variables(prompt: str, variables: dict) -> str:
    """Replace {{variable}} placeholders with values. Missing vars left as-is."""
    def replacer(match):
        key = match.group(1).strip()
        return str(variables[key]) if key in variables else match.group(0)
    return re.sub(r"\{\{(\s*\w+\s*)\}\}", replacer, prompt)


def extract_variable_names(prompt: str) -> set[str]:
    """Extract unique variable names from a prompt template."""
    return {m.strip() for m in re.findall(r"\{\{(\s*\w+\s*)\}\}", prompt)}


async def generate_content(
    prompt: str,
    variables: dict,
    model: str = "claude-sonnet",
    max_tokens: int = 300,
    org_id: str | None = None,
    reference: str | None = None,
) -> str:
    """Interpolate variables and call Claude. Returns generated text.
    If org_id provided, bills the AI usage to the org's credit balance."""
    filled_prompt = _interpolate_variables(prompt, variables)
    model_id = MODEL_MAP.get(model, MODEL_MAP["claude-sonnet"])

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": filled_prompt}],
        )
        # Bill AI usage if org_id provided
        if org_id:
            try:
                from app.database import get_db_session
                from app.services.billing import bill_ai_usage
                import uuid as _uuid
                async with get_db_session() as db:
                    await bill_ai_usage(
                        db,
                        org_id=_uuid.UUID(org_id) if isinstance(org_id, str) else org_id,
                        tokens_used=response.usage.input_tokens + response.usage.output_tokens,
                        model=model,
                        reference=reference or "sequence_content",
                    )
            except Exception:
                logger.warning("ai_billing_failed", org_id=org_id)

        return response.content[0].text.strip()
    except Exception:
        logger.exception("anthropic_generation_failed", model=model_id)
        raise
    finally:
        await client.close()


async def test_prompt(
    prompt: str,
    sample_variables: dict,
    model: str = "claude-sonnet",
    max_tokens: int = 300,
) -> dict:
    """Generate content and return metadata for the prompt test UI."""
    filled_prompt = _interpolate_variables(prompt, sample_variables)
    model_id = MODEL_MAP.get(model, MODEL_MAP["claude-sonnet"])

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        start = time.monotonic()
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": filled_prompt}],
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        input_cost = (input_tokens / 1_000_000) * COST_PER_1M_INPUT.get(model, 3.0)
        output_cost = (output_tokens / 1_000_000) * COST_PER_1M_OUTPUT.get(model, 15.0)

        return {
            "generated_content": response.content[0].text.strip(),
            "tokens_used": input_tokens + output_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
            "cost_estimate": round(input_cost + output_cost, 6),
            "model": model_id,
            "filled_prompt": filled_prompt,
        }
    except Exception:
        logger.exception("anthropic_test_prompt_failed", model=model_id)
        raise
    finally:
        await client.close()
```

- [ ] **Step 4: Run tests**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_anthropic_client.py -v`
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/services/anthropic_client.py tests/test_anthropic_client.py
git commit -m "feat(sequences): add Anthropic client for copywriting and prompt testing"
```

---

## Task 5: Messaging Client Service

**Files:**
- Create: `app/services/messaging_client.py`

- [ ] **Step 1: Implement multi-provider messaging client**

Create `app/services/messaging_client.py`:
```python
"""Multi-provider messaging client for WhatsApp and SMS delivery."""

import aiohttp
import structlog

from app.services.credential_encryption import decrypt_credentials
from app.config import settings

logger = structlog.get_logger(__name__)


class DeliveryResult:
    """Standardized delivery result across all providers."""

    def __init__(self, success: bool, message_id: str | None = None, error: str | None = None):
        self.success = success
        self.message_id = message_id
        self.error = error

    def to_dict(self):
        return {"success": self.success, "message_id": self.message_id, "error": self.error}


async def _get_provider_creds(encrypted_creds: str) -> dict:
    """Decrypt provider credentials."""
    return decrypt_credentials(encrypted_creds, settings.MESSAGING_CREDENTIALS_KEY)


# ---------------------------------------------------------------------------
# WATI
# ---------------------------------------------------------------------------

async def _wati_send_template(
    creds: dict, phone: str, template_name: str, params: list
) -> DeliveryResult:
    """Send a WhatsApp template message via WATI."""
    url = f"{creds['api_url']}/api/v1/sendTemplateMessage"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    body = {
        "template_name": template_name,
        "broadcast_name": f"seq_{template_name}_{phone}",
        "parameters": params,
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400:
                    return DeliveryResult(True, message_id=data.get("messageId") or data.get("id"))
                return DeliveryResult(False, error=f"WATI {resp.status}: {data}")
        except Exception as e:
            logger.exception("wati_send_template_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


async def _wati_send_session(creds: dict, phone: str, text: str) -> DeliveryResult:
    """Send a WhatsApp session (free-form) message via WATI."""
    url = f"{creds['api_url']}/api/v1/sendSessionMessage/{phone}"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    body = {"messageText": text}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400:
                    return DeliveryResult(True, message_id=data.get("messageId") or data.get("id"))
                return DeliveryResult(False, error=f"WATI session {resp.status}: {data}")
        except Exception as e:
            logger.exception("wati_send_session_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


# ---------------------------------------------------------------------------
# AISensy
# ---------------------------------------------------------------------------

async def _aisensy_send_template(
    creds: dict, phone: str, template_name: str, params: list
) -> DeliveryResult:
    """Send a WhatsApp template message via AISensy."""
    url = f"{creds['api_url']}/campaign/smart-campaign/api/v1"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    # AISensy param format: list of strings (positional)
    param_values = [p.get("value", "") for p in params] if params else []
    body = {
        "apiKey": creds.get("api_key", ""),
        "campaignName": f"seq_{template_name}_{phone}",
        "destination": phone,
        "userName": "Wavelength",
        "templateParams": param_values,
        "source": "wavelength-sequence",
        "media": {},
        "buttons": [],
        "carouselCards": [],
        "location": {},
    }
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400 and data.get("result"):
                    return DeliveryResult(True, message_id=data.get("data", {}).get("messageId"))
                return DeliveryResult(False, error=f"AISensy {resp.status}: {data}")
        except Exception as e:
            logger.exception("aisensy_send_template_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


async def _aisensy_send_session(creds: dict, phone: str, text: str) -> DeliveryResult:
    """Send a session message via AISensy."""
    url = f"{creds['api_url']}/project/api/v1/sendSessionMessage/{phone}"
    headers = {"Authorization": creds["api_token"], "Content-Type": "application/json"}
    body = {"messageText": text}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json()
                if resp.status < 400:
                    return DeliveryResult(True, message_id=data.get("messageId"))
                return DeliveryResult(False, error=f"AISensy session {resp.status}: {data}")
        except Exception as e:
            logger.exception("aisensy_send_session_failed", phone=phone)
            return DeliveryResult(False, error=str(e))


# ---------------------------------------------------------------------------
# Public interface (factory pattern)
# ---------------------------------------------------------------------------

TEMPLATE_HANDLERS = {
    "wati": _wati_send_template,
    "aisensy": _aisensy_send_template,
}

SESSION_HANDLERS = {
    "wati": _wati_send_session,
    "aisensy": _aisensy_send_session,
}


async def send_template(
    encrypted_creds: str, provider_type: str, phone: str, template_name: str, params: list
) -> DeliveryResult:
    """Send a WhatsApp template message via the appropriate provider."""
    creds = await _get_provider_creds(encrypted_creds)
    handler = TEMPLATE_HANDLERS.get(provider_type)
    if not handler:
        return DeliveryResult(False, error=f"Unsupported provider: {provider_type}")
    return await handler(creds, phone, template_name, params)


async def send_session_message(
    encrypted_creds: str, provider_type: str, phone: str, text: str
) -> DeliveryResult:
    """Send a WhatsApp session message via the appropriate provider."""
    creds = await _get_provider_creds(encrypted_creds)
    handler = SESSION_HANDLERS.get(provider_type)
    if not handler:
        return DeliveryResult(False, error=f"Unsupported provider for session: {provider_type}")
    return await handler(creds, phone, text)


async def send_sms(
    encrypted_creds: str, provider_type: str, phone: str, text: str
) -> DeliveryResult:
    """Send an SMS via the appropriate provider. Placeholder for v1."""
    logger.warning("sms_not_implemented", provider_type=provider_type, phone=phone)
    return DeliveryResult(False, error="SMS sending not yet implemented")
```

- [ ] **Step 2: Commit**

```bash
git add app/services/messaging_client.py
git commit -m "feat(sequences): add multi-provider messaging client (WATI, AISensy)"
```

---

## Task 6: Sequence Engine (Core Logic)

**Files:**
- Create: `app/services/sequence_engine.py`
- Create: `tests/test_sequence_engine.py`

- [ ] **Step 1: Write tests for timing calculation and skip evaluation**

Create `tests/test_sequence_engine.py`:
```python
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))


def test_calculate_scheduled_time_relative_to_signup():
    from app.services.sequence_engine import _calculate_scheduled_time

    signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    result = _calculate_scheduled_time(
        timing_type="relative_to_signup",
        timing_value={"hours": 1},
        signup_time=signup,
        event_date=None,
        prev_scheduled=None,
    )
    assert result == signup + timedelta(hours=1)


def test_calculate_scheduled_time_relative_to_event():
    from app.services.sequence_engine import _calculate_scheduled_time

    signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    event = datetime(2026, 3, 22, 0, 0, tzinfo=timezone.utc)
    result = _calculate_scheduled_time(
        timing_type="relative_to_event",
        timing_value={"days": -1, "time": "18:30"},
        signup_time=signup,
        event_date=event,
        prev_scheduled=None,
    )
    assert result.day == 21
    assert result.hour == 18
    assert result.minute == 30


def test_calculate_scheduled_time_relative_to_previous():
    from app.services.sequence_engine import _calculate_scheduled_time

    signup = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    prev = datetime(2026, 3, 19, 14, 0, tzinfo=timezone.utc)
    result = _calculate_scheduled_time(
        timing_type="relative_to_previous_step",
        timing_value={"hours": 24},
        signup_time=signup,
        event_date=None,
        prev_scheduled=prev,
    )
    assert result == prev + timedelta(hours=24)


def test_evaluate_skip_conditions_match():
    from app.services.sequence_engine import _should_skip

    conditions = {"field": "attended_saturday", "equals": "yes"}
    context = {"attended_saturday": "yes"}
    assert _should_skip(conditions, context) is True


def test_evaluate_skip_conditions_no_match():
    from app.services.sequence_engine import _should_skip

    conditions = {"field": "attended_saturday", "equals": "yes"}
    context = {"attended_saturday": "no"}
    assert _should_skip(conditions, context) is False


def test_evaluate_skip_conditions_none():
    from app.services.sequence_engine import _should_skip

    assert _should_skip(None, {"any": "data"}) is False


def test_trigger_conditions_match():
    from app.services.sequence_engine import _matches_trigger_conditions

    conditions = {"goal_outcome": ["qualified", "interested"], "min_interest": "medium"}
    analysis = SimpleNamespace(
        goal_outcome="qualified",
        interest_level="high",
        captured_data={},
    )
    assert _matches_trigger_conditions(conditions, analysis) is True


def test_trigger_conditions_no_match():
    from app.services.sequence_engine import _matches_trigger_conditions

    conditions = {"goal_outcome": ["qualified"]}
    analysis = SimpleNamespace(goal_outcome="not_interested", interest_level="low", captured_data={})
    assert _matches_trigger_conditions(conditions, analysis) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_sequence_engine.py -v`

- [ ] **Step 3: Implement sequence engine**

Create `app/services/sequence_engine.py`:
```python
"""Core sequence engine — trigger evaluation, instance creation, touchpoint processing, reply handling."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sequence import (
    SequenceInstance,
    SequenceStep,
    SequenceTemplate,
    SequenceTouchpoint,
)
from app.models.messaging_provider import MessagingProvider
from app.models.call_queue import QueuedCall
from app.services import anthropic_client, messaging_client

logger = structlog.get_logger(__name__)

INTEREST_LEVELS = {"low": 1, "medium": 2, "high": 3}


# ---------------------------------------------------------------------------
# Pure functions (testable without DB)
# ---------------------------------------------------------------------------

def _calculate_scheduled_time(
    timing_type: str,
    timing_value: dict,
    signup_time: datetime,
    event_date: datetime | None,
    prev_scheduled: datetime | None,
) -> datetime:
    """Calculate absolute scheduled time from timing config."""
    if timing_type == "relative_to_signup":
        delta = timedelta(
            hours=timing_value.get("hours", 0),
            days=timing_value.get("days", 0),
            minutes=timing_value.get("minutes", 0),
        )
        base = signup_time + delta
        # If a specific time is set, override hour/minute
        if "time" in timing_value:
            h, m = map(int, timing_value["time"].split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        return base

    elif timing_type == "relative_to_event":
        if not event_date:
            raise ValueError("relative_to_event requires event_date in context_data")
        days_offset = timing_value.get("days", 0)
        base = event_date + timedelta(days=days_offset)
        if "time" in timing_value:
            h, m = map(int, timing_value["time"].split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            hours = timing_value.get("hours", 0)
            base = base + timedelta(hours=hours)
        return base

    elif timing_type == "relative_to_previous_step":
        if not prev_scheduled:
            # Fallback to signup if no previous step
            prev_scheduled = signup_time
        delta = timedelta(
            hours=timing_value.get("hours", 0),
            days=timing_value.get("days", 0),
            minutes=timing_value.get("minutes", 0),
        )
        base = prev_scheduled + delta
        if "time" in timing_value:
            h, m = map(int, timing_value["time"].split(":"))
            base = base.replace(hour=h, minute=m, second=0, microsecond=0)
        return base

    raise ValueError(f"Unknown timing_type: {timing_type}")


def _should_skip(skip_conditions: dict | None, context_data: dict) -> bool:
    """Evaluate if a step should be skipped based on context data."""
    if not skip_conditions:
        return False
    field = skip_conditions.get("field", "")
    expected = skip_conditions.get("equals")
    actual = context_data.get(field)
    if expected is not None:
        return str(actual) == str(expected)
    not_equals = skip_conditions.get("not_equals")
    if not_equals is not None:
        return str(actual) != str(not_equals)
    return False


def _matches_trigger_conditions(conditions: dict, analysis) -> bool:
    """Check if a call analysis matches template trigger conditions."""
    if not conditions:
        return True

    # Check goal_outcome
    if "goal_outcome" in conditions:
        allowed = conditions["goal_outcome"]
        if isinstance(allowed, list) and analysis.goal_outcome not in allowed:
            return False

    # Check min_interest
    if "min_interest" in conditions:
        min_level = INTEREST_LEVELS.get(conditions["min_interest"], 0)
        actual_level = INTEREST_LEVELS.get(getattr(analysis, "interest_level", "low"), 0)
        if actual_level < min_level:
            return False

    return True


def _snapshot_step(step: SequenceStep) -> dict:
    """Create a JSON snapshot of step config for touchpoint."""
    return {
        "name": step.name,
        "channel": step.channel,
        "content_type": step.content_type,
        "whatsapp_template_name": step.whatsapp_template_name,
        "whatsapp_template_params": step.whatsapp_template_params,
        "ai_prompt": step.ai_prompt,
        "ai_model": step.ai_model,
        "voice_bot_id": str(step.voice_bot_id) if step.voice_bot_id else None,
        "expects_reply": step.expects_reply,
        "reply_handler": step.reply_handler,
        "skip_conditions": step.skip_conditions,
    }


# ---------------------------------------------------------------------------
# DB-dependent functions
# ---------------------------------------------------------------------------

async def evaluate_trigger(
    db: AsyncSession,
    org_id: uuid.UUID,
    bot_id: uuid.UUID,
    analysis,
    lead,
    call_log,
) -> SequenceInstance | None:
    """After a call completes, check if any sequence template should fire."""
    # Find active templates for this bot (or org-wide)
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,
            SequenceTemplate.trigger_type == "post_call",
            (SequenceTemplate.bot_id == bot_id) | (SequenceTemplate.bot_id.is_(None)),
        )
    )
    templates = result.scalars().all()

    for template in templates:
        if not _matches_trigger_conditions(template.trigger_conditions, analysis):
            continue

        # Check max_active_per_lead
        active_count_result = await db.execute(
            select(func.count()).where(
                SequenceInstance.template_id == template.id,
                SequenceInstance.lead_id == lead.id,
                SequenceInstance.status == "active",
            )
        )
        active_count = active_count_result.scalar() or 0
        if active_count >= template.max_active_per_lead:
            logger.info(
                "sequence_trigger_skipped_max_active",
                template_id=str(template.id),
                lead_id=str(lead.id),
                active_count=active_count,
            )
            continue

        # Build context_data from analysis + lead + call_log
        context_data = {
            "contact_name": lead.contact_name or "",
            "contact_phone": lead.phone_number or "",
            "profession": getattr(analysis, "captured_data", {}).get("profession", ""),
            "challenge": getattr(analysis, "captured_data", {}).get("challenge", ""),
            "anchor_task": getattr(analysis, "captured_data", {}).get("anchor_task", ""),
            "tried_ai": getattr(analysis, "captured_data", {}).get("tried_ai", ""),
            "interest_level": getattr(analysis, "interest_level", ""),
            "goal_outcome": getattr(analysis, "goal_outcome", ""),
            "sentiment": getattr(analysis, "sentiment", ""),
            "call_summary": getattr(analysis, "summary", ""),
        }
        # Merge any captured_data fields
        if hasattr(analysis, "captured_data") and analysis.captured_data:
            for k, v in analysis.captured_data.items():
                if k not in context_data:
                    context_data[k] = v

        instance = await create_instance(
            db,
            template_id=template.id,
            org_id=org_id,
            lead_id=lead.id,
            trigger_call_id=call_log.id if call_log else None,
            context_data=context_data,
        )
        if instance:
            logger.info(
                "sequence_triggered",
                template=template.name,
                lead_id=str(lead.id),
                instance_id=str(instance.id),
            )
            return instance

    return None


async def create_instance(
    db: AsyncSession,
    template_id: uuid.UUID,
    org_id: uuid.UUID,
    lead_id: uuid.UUID,
    trigger_call_id: uuid.UUID | None,
    context_data: dict,
) -> SequenceInstance | None:
    """Create a sequence instance + all touchpoints with calculated times."""
    # Load steps
    result = await db.execute(
        select(SequenceStep)
        .where(SequenceStep.template_id == template_id, SequenceStep.is_active == True)
        .order_by(SequenceStep.step_order)
    )
    steps = result.scalars().all()
    if not steps:
        logger.warning("sequence_create_no_steps", template_id=str(template_id))
        return None

    # Validate event_date if any step needs it
    event_date = None
    if context_data.get("event_date"):
        try:
            ed = context_data["event_date"]
            if isinstance(ed, str):
                event_date = datetime.fromisoformat(ed.replace("Z", "+00:00"))
                if event_date.tzinfo is None:
                    event_date = event_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    for step in steps:
        if step.timing_type == "relative_to_event" and not event_date:
            logger.error("sequence_create_missing_event_date", template_id=str(template_id))
            return None

    # Create instance
    now = datetime.now(timezone.utc)
    instance = SequenceInstance(
        org_id=org_id,
        template_id=template_id,
        lead_id=lead_id,
        trigger_call_id=trigger_call_id,
        status="active",
        context_data=context_data,
        started_at=now,
    )
    db.add(instance)
    await db.flush()  # Get instance.id

    # Resolve default messaging provider for this org
    provider_result = await db.execute(
        select(MessagingProvider).where(
            MessagingProvider.org_id == org_id,
            MessagingProvider.is_default == True,
        )
    )
    default_provider = provider_result.scalar_one_or_none()

    # Create touchpoints
    prev_scheduled = None
    for step in steps:
        scheduled_at = _calculate_scheduled_time(
            timing_type=step.timing_type,
            timing_value=step.timing_value,
            signup_time=now,
            event_date=event_date,
            prev_scheduled=prev_scheduled,
        )

        # Determine initial status
        status = "pending"
        if _should_skip(step.skip_conditions, context_data):
            status = "skipped"

        touchpoint = SequenceTouchpoint(
            instance_id=instance.id,
            step_id=step.id,
            org_id=org_id,
            lead_id=lead_id,
            step_order=step.step_order,
            step_snapshot=_snapshot_step(step),
            status=status,
            scheduled_at=scheduled_at,
            messaging_provider_id=default_provider.id if default_provider else None,
        )
        db.add(touchpoint)
        prev_scheduled = scheduled_at

    await db.flush()
    return instance


async def process_touchpoint(db: AsyncSession, touchpoint: SequenceTouchpoint) -> None:
    """Process a single due touchpoint: generate content, send, update status."""
    snapshot = touchpoint.step_snapshot or {}
    channel = snapshot.get("channel", "")
    content_type = snapshot.get("content_type", "")

    # Load instance for context_data
    inst_result = await db.execute(
        select(SequenceInstance).where(SequenceInstance.id == touchpoint.instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance or instance.status != "active":
        touchpoint.status = "skipped"
        await db.commit()
        return

    context = instance.context_data or {}
    phone = context.get("contact_phone", "")

    # Re-check skip conditions
    if _should_skip(snapshot.get("skip_conditions"), context):
        touchpoint.status = "skipped"
        await db.commit()
        return

    # --- Generate content if AI ---
    if content_type == "ai_generated" and snapshot.get("ai_prompt"):
        touchpoint.status = "generating"
        await db.commit()
        try:
            generated = await anthropic_client.generate_content(
                prompt=snapshot["ai_prompt"],
                variables=context,
                model=snapshot.get("ai_model", "claude-sonnet"),
                org_id=str(touchpoint.org_id),
                reference=f"sequence_tp_{touchpoint.id}",
            )
            touchpoint.generated_content = generated
        except Exception as e:
            touchpoint.status = "failed"
            touchpoint.error_message = f"AI generation failed: {e}"
            touchpoint.retry_count += 1
            await db.commit()
            return

    # --- Send via channel ---
    if channel == "voice_call":
        # Create a QueuedCall for the specified bot
        bot_id = snapshot.get("voice_bot_id")
        if not bot_id:
            touchpoint.status = "failed"
            touchpoint.error_message = "No voice_bot_id configured for voice_call step"
            await db.commit()
            return

        queued_call = QueuedCall(
            org_id=touchpoint.org_id,
            bot_id=uuid.UUID(bot_id) if isinstance(bot_id, str) else bot_id,
            contact_name=context.get("contact_name", ""),
            contact_phone=phone,
            ghl_contact_id=context.get("ghl_contact_id"),
            source="sequence",
            status="queued",
            priority=1,
            extra_vars={
                "sequence_instance_id": str(touchpoint.instance_id),
                "sequence_touchpoint_id": str(touchpoint.id),
                "step_name": snapshot.get("name", ""),
            },
        )
        db.add(queued_call)
        await db.flush()
        touchpoint.queued_call_id = queued_call.id
        touchpoint.status = "scheduled"
        await db.commit()
        logger.info("sequence_voice_call_queued", touchpoint_id=str(touchpoint.id), bot_id=bot_id)
        return

    # WhatsApp / SMS delivery
    if not touchpoint.messaging_provider_id:
        touchpoint.status = "failed"
        touchpoint.error_message = "No messaging provider configured"
        await db.commit()
        return

    prov_result = await db.execute(
        select(MessagingProvider).where(MessagingProvider.id == touchpoint.messaging_provider_id)
    )
    provider = prov_result.scalar_one_or_none()
    if not provider:
        touchpoint.status = "failed"
        touchpoint.error_message = "Messaging provider not found"
        await db.commit()
        return

    result = None
    now = datetime.now(timezone.utc)

    if channel == "whatsapp_template":
        # Interpolate template params
        params = snapshot.get("whatsapp_template_params") or []
        resolved_params = []
        for p in params:
            val = p.get("value", "")
            # Replace {{var}} with context values
            from app.services.anthropic_client import _interpolate_variables
            val = _interpolate_variables(val, context)
            resolved_params.append({"name": p.get("name", ""), "value": val})

        # If AI-generated content should be injected into a template param
        if touchpoint.generated_content and resolved_params:
            # Find param that references {{ai_content}} or is empty, fill with generated
            for rp in resolved_params:
                if "{{ai_content}}" in rp.get("value", "") or rp.get("value", "") == "":
                    rp["value"] = touchpoint.generated_content
                    break

        result = await messaging_client.send_template(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            template_name=snapshot.get("whatsapp_template_name", ""),
            params=resolved_params,
        )
        if result.success:
            touchpoint.session_window_expires_at = now + timedelta(hours=24)

    elif channel == "whatsapp_session":
        content = touchpoint.generated_content or ""
        if not content:
            touchpoint.status = "failed"
            touchpoint.error_message = "No content for session message"
            await db.commit()
            return
        result = await messaging_client.send_session_message(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            text=content,
        )

    elif channel == "sms":
        content = touchpoint.generated_content or ""
        result = await messaging_client.send_sms(
            encrypted_creds=provider.credentials,
            provider_type=provider.provider_type,
            phone=phone,
            text=content,
        )

    # Update touchpoint status
    if result and result.success:
        if snapshot.get("expects_reply"):
            touchpoint.status = "awaiting_reply"
        else:
            touchpoint.status = "sent"
        touchpoint.sent_at = now
    elif result:
        touchpoint.status = "failed"
        touchpoint.error_message = result.error
        touchpoint.retry_count += 1
    else:
        touchpoint.status = "failed"
        touchpoint.error_message = "No delivery result returned"
        touchpoint.retry_count += 1

    await db.commit()

    # Check if sequence is complete
    await _check_instance_completion(db, touchpoint.instance_id)


async def handle_reply(db: AsyncSession, phone: str, message_text: str) -> bool:
    """Handle an incoming WhatsApp reply. Returns True if processed."""
    # Normalize phone
    clean_phone = phone.lstrip("+")

    # Find most recent awaiting_reply touchpoint for this phone, within 48hrs
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    result = await db.execute(
        select(SequenceTouchpoint)
        .join(SequenceInstance, SequenceTouchpoint.instance_id == SequenceInstance.id)
        .where(
            SequenceTouchpoint.status == "awaiting_reply",
            SequenceInstance.status == "active",
            SequenceTouchpoint.sent_at >= cutoff,
            SequenceInstance.context_data["contact_phone"].astext.contains(clean_phone[-10:]),
        )
        .order_by(SequenceTouchpoint.sent_at.desc())
        .limit(1)
    )
    touchpoint = result.scalar_one_or_none()
    if not touchpoint:
        logger.debug("reply_no_matching_touchpoint", phone=phone)
        return False

    snapshot = touchpoint.step_snapshot or {}
    reply_handler = snapshot.get("reply_handler")
    touchpoint.reply_text = message_text
    # Reset session window on reply (WhatsApp 24hr window resets from user's last message)
    touchpoint.session_window_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

    # Load instance for context
    inst_result = await db.execute(
        select(SequenceInstance).where(SequenceInstance.id == touchpoint.instance_id)
    )
    instance = inst_result.scalar_one_or_none()

    if reply_handler and reply_handler.get("action") == "ai_respond":
        # Check session window
        now = datetime.now(timezone.utc)
        if touchpoint.session_window_expires_at and now > touchpoint.session_window_expires_at:
            logger.warning("reply_session_window_expired", touchpoint_id=str(touchpoint.id))
            touchpoint.status = "replied"
            touchpoint.error_message = "Session window expired, AI response not sent"
            await db.commit()
            return True

        # Generate AI response
        try:
            context = dict(instance.context_data) if instance else {}
            context["reply_text"] = message_text
            response = await anthropic_client.generate_content(
                prompt=reply_handler["ai_prompt"],
                variables=context,
                model=reply_handler.get("ai_model", "claude-sonnet"),
            )
            touchpoint.reply_response = response

            # Send response via WhatsApp session
            if touchpoint.messaging_provider_id:
                prov_result = await db.execute(
                    select(MessagingProvider).where(
                        MessagingProvider.id == touchpoint.messaging_provider_id
                    )
                )
                provider = prov_result.scalar_one_or_none()
                if provider:
                    contact_phone = (instance.context_data or {}).get("contact_phone", phone)
                    await messaging_client.send_session_message(
                        encrypted_creds=provider.credentials,
                        provider_type=provider.provider_type,
                        phone=contact_phone,
                        text=response,
                    )

            # Save to context_data if configured
            if reply_handler.get("save_field") and instance:
                updated_context = dict(instance.context_data)
                updated_context[reply_handler["save_field"]] = message_text
                instance.context_data = updated_context

        except Exception as e:
            logger.exception("reply_ai_generation_failed", touchpoint_id=str(touchpoint.id))
            touchpoint.error_message = f"AI response generation failed: {e}"

    touchpoint.status = "replied"
    await db.commit()

    logger.info("reply_processed", touchpoint_id=str(touchpoint.id), phone=phone)
    return True


async def _check_instance_completion(db: AsyncSession, instance_id: uuid.UUID) -> None:
    """Check if all touchpoints are terminal and mark instance completed."""
    result = await db.execute(
        select(func.count()).where(
            SequenceTouchpoint.instance_id == instance_id,
            SequenceTouchpoint.status.in_(["pending", "generating", "scheduled", "awaiting_reply"]),
        )
    )
    remaining = result.scalar() or 0
    if remaining == 0:
        inst_result = await db.execute(
            select(SequenceInstance).where(SequenceInstance.id == instance_id)
        )
        instance = inst_result.scalar_one_or_none()
        if instance and instance.status == "active":
            instance.status = "completed"
            instance.completed_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("sequence_completed", instance_id=str(instance_id))
```

- [ ] **Step 4: Run tests**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/test_sequence_engine.py -v`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/services/sequence_engine.py tests/test_sequence_engine.py
git commit -m "feat(sequences): add sequence engine with trigger evaluation, instance creation, and touchpoint processing"
```

---

## Task 7: Sequence Scheduler (Background Poller)

**Files:**
- Create: `app/services/sequence_scheduler.py`

- [ ] **Step 1: Implement scheduler**

Create `app/services/sequence_scheduler.py`:
```python
"""Background scheduler that polls for due touchpoints and fires them."""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models.sequence import SequenceTouchpoint, SequenceInstance
from app.services import sequence_engine

logger = structlog.get_logger(__name__)

POLL_INTERVAL = 10  # seconds
MAX_CONCURRENT = 10  # max touchpoints processed in parallel per batch

_shutdown = False
_task: asyncio.Task | None = None


def start():
    """Start the sequence scheduler background task."""
    global _task, _shutdown
    _shutdown = False
    _task = asyncio.create_task(_scheduler_loop())
    logger.info("sequence_scheduler_started", poll_interval=POLL_INTERVAL)


async def stop():
    """Stop the scheduler gracefully."""
    global _shutdown, _task
    _shutdown = True
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    logger.info("sequence_scheduler_stopped")


async def _scheduler_loop():
    """Main loop — polls DB for due touchpoints."""
    cycle_count = 0
    while not _shutdown:
        try:
            await _process_batch()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("sequence_scheduler_error")

        # Every 5th cycle, retry failed touchpoints that haven't hit max retries
        cycle_count += 1
        if cycle_count % 5 == 0:
            try:
                await _retry_failed()
            except Exception:
                logger.exception("sequence_retry_failed_error")

        await asyncio.sleep(POLL_INTERVAL)


async def _process_batch():
    """Find and process all due touchpoints."""
    now = datetime.now(timezone.utc)

    async with get_db_session() as db:
        # Find due touchpoints: pending/scheduled and scheduled_at in the past
        # Skip touchpoints belonging to paused/cancelled instances
        result = await db.execute(
            select(SequenceTouchpoint)
            .join(SequenceInstance, SequenceTouchpoint.instance_id == SequenceInstance.id)
            .where(
                SequenceTouchpoint.status.in_(["pending", "scheduled"]),
                SequenceTouchpoint.scheduled_at <= now,
                SequenceInstance.status == "active",
            )
            .order_by(SequenceTouchpoint.scheduled_at.asc())
            .limit(MAX_CONCURRENT * 2)  # Fetch more than we process to account for skips
            .with_for_update(skip_locked=True)
        )
        touchpoints = result.scalars().all()

        # Phone spacing: skip touchpoints whose lead had a message sent <60s ago
        # This prevents WhatsApp rate limiting when multiple sequences target same lead
        _recent_phones: dict[str, datetime] = {}
        filtered = []
        for tp in touchpoints:
            # Get phone from instance context (cheap: already in memory after join)
            phone = None
            if tp.step_snapshot and tp.step_snapshot.get("channel", "").startswith("whatsapp"):
                inst_result = await db.execute(
                    select(SequenceInstance.context_data).where(SequenceInstance.id == tp.instance_id)
                )
                ctx = inst_result.scalar_one_or_none() or {}
                phone = ctx.get("contact_phone", "")[-10:] if isinstance(ctx, dict) else ""

            if phone and phone in _recent_phones:
                last_sent = _recent_phones[phone]
                if (now - last_sent).total_seconds() < 60:
                    continue  # Skip — too soon for this phone

            filtered.append(tp)
            if phone:
                _recent_phones[phone] = now

        touchpoints = filtered

        if not touchpoints:
            return

        logger.info("sequence_scheduler_batch", count=len(touchpoints))

        # Process in bounded parallel batches
        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def _process_one(tp_id):
            async with semaphore:
                # Each touchpoint gets its own DB session for isolation
                async with get_db_session() as tp_db:
                    tp_result = await tp_db.execute(
                        select(SequenceTouchpoint)
                        .where(SequenceTouchpoint.id == tp_id)
                        .with_for_update(skip_locked=True)
                    )
                    tp = tp_result.scalar_one_or_none()
                    if not tp or tp.status != "pending":
                        return

                    try:
                        await sequence_engine.process_touchpoint(tp_db, tp)
                    except Exception:
                        logger.exception("sequence_touchpoint_processing_failed", touchpoint_id=str(tp_id))
                        tp.status = "failed"
                        tp.error_message = "Unexpected processing error"
                        tp.retry_count += 1
                        await tp_db.commit()

        # Launch all in parallel (bounded by semaphore)
        tasks = [asyncio.create_task(_process_one(tp.id)) for tp in touchpoints]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Release the original FOR UPDATE lock
        await db.commit()


async def _retry_failed():
    """Re-queue failed touchpoints that haven't hit max retries."""
    async with get_db_session() as db:
        result = await db.execute(
            select(SequenceTouchpoint).where(
                SequenceTouchpoint.status == "failed",
                SequenceTouchpoint.retry_count < SequenceTouchpoint.max_retries,
            )
        )
        retryable = result.scalars().all()
        for tp in retryable:
            tp.status = "pending"
            logger.info("sequence_touchpoint_retry", touchpoint_id=str(tp.id), retry=tp.retry_count)
        if retryable:
            await db.commit()
```

- [ ] **Step 2: Commit**

```bash
git add app/services/sequence_scheduler.py
git commit -m "feat(sequences): add background sequence scheduler with bounded parallel processing"
```

---

## Task 8: App Lifespan + Post-Call Hook Integration

**Files:**
- Modify: `app/main.py`
- Modify: `app/plivo/routes.py`
- Modify: `app/services/billing.py`

- [ ] **Step 1: Add scheduler to app lifespan**

In `app/main.py`, add import and start/stop calls:

After existing imports, add:
```python
from app.services import sequence_scheduler
```

In the lifespan startup section, after `queue_processor.start(bot_config_loader)`, add:
```python
    # Start sequence scheduler
    sequence_scheduler.start()
```

In the lifespan shutdown section, before `await queue_processor.stop()`, add:
```python
    await sequence_scheduler.stop()
```

- [ ] **Step 2: Add post-call hook in plivo/routes.py**

In `app/plivo/routes.py`, add import at top:
```python
from app.services import sequence_engine
```

After the billing call (~line 702), before the backup GHL posting, add:
```python
    # Trigger engagement sequence if matching template exists
    if call_log and call_log.metadata_:
        try:
            from app.models.lead import Lead
            from app.database import get_db_session as _get_db
            async with _get_db() as seq_db:
                # Find lead
                lead_result = await seq_db.execute(
                    select(Lead).where(
                        Lead.org_id == call_log.org_id,
                        Lead.phone_number.contains(call_log.contact_phone[-10:]),
                    ).limit(1)
                )
                lead = lead_result.scalar_one_or_none()
                if lead and call_log.metadata_.get("goal_outcome"):
                    from types import SimpleNamespace
                    analysis = SimpleNamespace(
                        goal_outcome=call_log.metadata_.get("goal_outcome", ""),
                        interest_level=call_log.metadata_.get("interest_level", ""),
                        captured_data=call_log.metadata_.get("captured_data", {}),
                        sentiment=call_log.metadata_.get("sentiment", ""),
                        summary=call_log.metadata_.get("summary", ""),
                    )
                    await sequence_engine.evaluate_trigger(
                        seq_db, call_log.org_id, call_log.bot_id, analysis, lead, call_log
                    )
        except Exception:
            logger.exception("sequence_trigger_failed", call_sid=call_sid)
```

- [ ] **Step 3: Add same hook in twilio/routes.py**

Same pattern in `app/twilio/routes.py` at the equivalent post-call location.

- [ ] **Step 4: Add bill_ai_usage to billing.py**

In `app/services/billing.py`, add after the existing `bill_completed_call` function:
```python
async def bill_ai_usage(
    db: AsyncSession,
    org_id: uuid.UUID,
    tokens_used: int,
    model: str,
    reference: str,
) -> bool:
    """Bill for AI content generation (Claude API usage)."""
    # Estimate cost in credits (1 credit = ~$0.01)
    cost_per_1m = {"claude-sonnet": 18.0, "claude-haiku": 4.8}  # input+output avg
    cost_usd = (tokens_used / 1_000_000) * cost_per_1m.get(model, 18.0)
    credits = Decimal(str(round(cost_usd * 100, 2)))  # Convert to credits

    if credits <= ZERO_CREDITS:
        return False

    org = await db.execute(
        select(Organization).where(Organization.id == org_id).with_for_update()
    )
    org_obj = org.scalar_one_or_none()
    if not org_obj:
        return False

    org_obj.credit_balance = org_obj.credit_balance - credits

    tx = CreditTransaction(
        org_id=org_id,
        type="usage",
        amount=-credits,
        description=f"AI generation ({model})",
        reference_id=reference,
    )
    db.add(tx)
    await db.commit()
    return True
```

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/plivo/routes.py app/twilio/routes.py app/services/billing.py
git commit -m "feat(sequences): integrate scheduler in lifespan + post-call trigger hook + AI billing"
```

---

## Task 9: API Routes — Sequences

**Files:**
- Create: `app/api/sequences.py`
- Create: `app/api/messaging_providers.py`
- Create: `app/api/webhooks.py`
- Modify: `app/main.py` (register routers)

- [ ] **Step 1: Create sequences API**

Create `app/api/sequences.py` with these endpoints:
- `GET /api/sequences/templates` — list templates (paginated)
- `POST /api/sequences/templates` — create template
- `GET /api/sequences/templates/{id}` — get template with steps
- `PUT /api/sequences/templates/{id}` — update template
- `DELETE /api/sequences/templates/{id}` — deactivate
- `POST /api/sequences/templates/{id}/steps` — add step
- `PUT /api/sequences/steps/{id}` — update step
- `DELETE /api/sequences/steps/{id}` — remove step
- `POST /api/sequences/templates/{id}/reorder` — reorder steps
- `POST /api/sequences/test-prompt` — test AI prompt
- `GET /api/sequences/templates/{id}/export` — export as JSON
- `POST /api/sequences/templates/import` — import from JSON
- `POST /api/sequences/templates/import/preview` — validate JSON
- `GET /api/sequences/instances` — list instances (paginated, filterable)
- `GET /api/sequences/instances/{id}` — instance with touchpoints
- `POST /api/sequences/instances/{id}/pause` — pause
- `POST /api/sequences/instances/{id}/resume` — resume
- `POST /api/sequences/instances/{id}/cancel` — cancel
- `GET /api/sequences/touchpoints/{id}` — touchpoint detail
- `POST /api/sequences/touchpoints/{id}/retry` — retry failed

Follow exact pattern from `app/api/leads.py`: APIRouter, Depends(get_current_org), Depends(get_db), Pydantic schemas for request/response, pagination with page/page_size query params.

**Key schemas:**
```python
class TemplateCreate(BaseModel):
    name: str
    trigger_type: str = "post_call"
    trigger_conditions: dict = {}
    bot_id: str | None = None
    max_active_per_lead: int = 1

class StepCreate(BaseModel):
    name: str
    step_order: int
    channel: str  # whatsapp_template, whatsapp_session, voice_call, sms
    timing_type: str
    timing_value: dict
    content_type: str  # static_template, ai_generated, voice_call
    skip_conditions: dict | None = None
    whatsapp_template_name: str | None = None
    whatsapp_template_params: list | None = None
    ai_prompt: str | None = None
    ai_model: str | None = "claude-sonnet"
    voice_bot_id: str | None = None
    expects_reply: bool = False
    reply_handler: dict | None = None

class PromptTestRequest(BaseModel):
    prompt: str
    variables: dict
    model: str = "claude-sonnet"
    max_tokens: int = 300

class ImportRequest(BaseModel):
    template_json: dict  # Full template + steps JSON
```

The test-prompt endpoint calls `anthropic_client.test_prompt()` and returns the result. **Rate limiting:** Track per-org usage with an in-memory dict `{org_id: [timestamp, ...]}`. Before calling Claude, check if org has >= 20 calls in the last hour. If so, return 429 with message "Rate limit: 20 prompt tests per hour." Also debit credits via `bill_ai_usage()` after successful generation.

Import/export: export serializes template + steps to JSON matching the format in the spec. Import validates and creates template + steps in a transaction.

- [ ] **Step 2: Create messaging providers API**

Create `app/api/messaging_providers.py`:
- `GET /api/messaging/providers` — list org's providers
- `POST /api/messaging/providers` — create (encrypt credentials)
- `PUT /api/messaging/providers/{id}` — update
- `DELETE /api/messaging/providers/{id}` — remove
- `POST /api/messaging/providers/{id}/test` — send test message

Credentials are encrypted on POST/PUT using `credential_encryption.encrypt_credentials()`.

- [ ] **Step 3: Create webhooks API**

Create `app/api/webhooks.py`:
- `POST /api/webhooks/whatsapp-reply/{provider_id}` — receives WATI/AISensy webhooks

Parses provider-specific format, normalizes phone, deduplicates by message_id, calls `sequence_engine.handle_reply()`.

- [ ] **Step 4: Register routers in main.py**

In `app/main.py`, add:
```python
from app.api import sequences, messaging_providers, webhooks

# In the app creation section:
app.include_router(sequences.router)
app.include_router(messaging_providers.router)
app.include_router(webhooks.router)
```

- [ ] **Step 5: Commit**

```bash
git add app/api/sequences.py app/api/messaging_providers.py app/api/webhooks.py app/main.py
git commit -m "feat(sequences): add REST API for templates, instances, messaging providers, and webhooks"
```

---

## Task 10: Frontend — API Functions

**Files:**
- Create: `frontend/src/lib/sequences-api.ts`
- Create: `frontend/src/lib/messaging-api.ts`

- [ ] **Step 0: Export apiFetch from api.ts (PREREQUISITE)**

In `frontend/src/lib/api.ts`, change `async function apiFetch<T>` to `export async function apiFetch<T>`. All Tasks 10-16 depend on this.

- [ ] **Step 1: Create sequences API functions**

Create `frontend/src/lib/sequences-api.ts` following the pattern in `frontend/src/lib/api.ts`:

```typescript
import { apiFetch } from "./api";

// --- Types ---
export interface SequenceTemplate {
  id: string;
  name: string;
  trigger_type: string;
  trigger_conditions: Record<string, any>;
  bot_id: string | null;
  max_active_per_lead: number;
  is_active: boolean;
  step_count?: number;
  created_at: string;
}

export interface SequenceStep {
  id: string;
  template_id: string;
  step_order: number;
  name: string;
  is_active: boolean;
  channel: string;
  timing_type: string;
  timing_value: Record<string, any>;
  skip_conditions: Record<string, any> | null;
  content_type: string;
  whatsapp_template_name: string | null;
  whatsapp_template_params: any[] | null;
  ai_prompt: string | null;
  ai_model: string | null;
  voice_bot_id: string | null;
  expects_reply: boolean;
  reply_handler: Record<string, any> | null;
}

export interface SequenceInstance {
  id: string;
  template_id: string;
  template_name?: string;
  lead_id: string;
  lead_name?: string;
  lead_phone?: string;
  status: string;
  context_data: Record<string, any>;
  current_step?: number;
  next_touchpoint_at?: string;
  started_at: string;
  completed_at: string | null;
}

export interface SequenceTouchpoint {
  id: string;
  instance_id: string;
  step_order: number;
  step_snapshot: Record<string, any>;
  status: string;
  scheduled_at: string;
  generated_content: string | null;
  sent_at: string | null;
  reply_text: string | null;
  reply_response: string | null;
  error_message: string | null;
  retry_count: number;
}

export interface PromptTestResult {
  generated_content: string;
  tokens_used: number;
  latency_ms: number;
  cost_estimate: number;
  model: string;
  filled_prompt: string;
}

// --- Templates ---
export const fetchTemplates = (page = 1, pageSize = 50) =>
  apiFetch<{ items: SequenceTemplate[]; total: number }>(
    `/api/sequences/templates?page=${page}&page_size=${pageSize}`
  );

export const fetchTemplate = (id: string) =>
  apiFetch<SequenceTemplate & { steps: SequenceStep[] }>(`/api/sequences/templates/${id}`);

export const createTemplate = (data: Partial<SequenceTemplate>) =>
  apiFetch<SequenceTemplate>("/api/sequences/templates", { method: "POST", body: JSON.stringify(data) });

export const updateTemplate = (id: string, data: Partial<SequenceTemplate>) =>
  apiFetch<SequenceTemplate>(`/api/sequences/templates/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteTemplate = (id: string) =>
  apiFetch<void>(`/api/sequences/templates/${id}`, { method: "DELETE" });

// --- Steps ---
export const addStep = (templateId: string, data: Partial<SequenceStep>) =>
  apiFetch<SequenceStep>(`/api/sequences/templates/${templateId}/steps`, { method: "POST", body: JSON.stringify(data) });

export const updateStep = (stepId: string, data: Partial<SequenceStep>) =>
  apiFetch<SequenceStep>(`/api/sequences/steps/${stepId}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteStep = (stepId: string) =>
  apiFetch<void>(`/api/sequences/steps/${stepId}`, { method: "DELETE" });

export const reorderSteps = (templateId: string, stepIds: string[]) =>
  apiFetch<void>(`/api/sequences/templates/${templateId}/reorder`, { method: "POST", body: JSON.stringify({ step_ids: stepIds }) });

// --- Prompt Testing ---
export const testPrompt = (data: { prompt: string; variables: Record<string, string>; model?: string; max_tokens?: number }) =>
  apiFetch<PromptTestResult>("/api/sequences/test-prompt", { method: "POST", body: JSON.stringify(data) });

// --- Import/Export ---
export const exportTemplate = (id: string) =>
  apiFetch<Record<string, any>>(`/api/sequences/templates/${id}/export`);

export const importTemplate = (templateJson: Record<string, any>) =>
  apiFetch<SequenceTemplate>("/api/sequences/templates/import", { method: "POST", body: JSON.stringify({ template_json: templateJson }) });

export const previewImport = (templateJson: Record<string, any>) =>
  apiFetch<{ valid: boolean; errors: string[]; template: SequenceTemplate | null }>(
    "/api/sequences/templates/import/preview",
    { method: "POST", body: JSON.stringify({ template_json: templateJson }) }
  );

// --- Instances ---
export const fetchInstances = (params?: { lead_id?: string; template_id?: string; status?: string; page?: number }) => {
  const qs = new URLSearchParams();
  if (params?.lead_id) qs.set("lead_id", params.lead_id);
  if (params?.template_id) qs.set("template_id", params.template_id);
  if (params?.status) qs.set("status", params.status);
  if (params?.page) qs.set("page", String(params.page));
  return apiFetch<{ items: SequenceInstance[]; total: number }>(`/api/sequences/instances?${qs}`);
};

export const fetchInstance = (id: string) =>
  apiFetch<SequenceInstance & { touchpoints: SequenceTouchpoint[] }>(`/api/sequences/instances/${id}`);

export const pauseInstance = (id: string) =>
  apiFetch<void>(`/api/sequences/instances/${id}/pause`, { method: "POST" });

export const resumeInstance = (id: string) =>
  apiFetch<void>(`/api/sequences/instances/${id}/resume`, { method: "POST" });

export const cancelInstance = (id: string) =>
  apiFetch<void>(`/api/sequences/instances/${id}/cancel`, { method: "POST" });

// --- Touchpoints ---
export const fetchTouchpoint = (id: string) =>
  apiFetch<SequenceTouchpoint>(`/api/sequences/touchpoints/${id}`);

export const retryTouchpoint = (id: string) =>
  apiFetch<void>(`/api/sequences/touchpoints/${id}/retry`, { method: "POST" });
```

- [ ] **Step 2: Create messaging API functions**

Create `frontend/src/lib/messaging-api.ts`:
```typescript
import { apiFetch } from "./api";

export interface MessagingProvider {
  id: string;
  provider_type: string;
  name: string;
  is_default: boolean;
  created_at: string;
}

export const fetchProviders = () =>
  apiFetch<MessagingProvider[]>("/api/messaging/providers");

export const createProvider = (data: { provider_type: string; name: string; credentials: Record<string, string>; is_default?: boolean }) =>
  apiFetch<MessagingProvider>("/api/messaging/providers", { method: "POST", body: JSON.stringify(data) });

export const updateProvider = (id: string, data: Partial<{ name: string; credentials: Record<string, string>; is_default: boolean }>) =>
  apiFetch<MessagingProvider>(`/api/messaging/providers/${id}`, { method: "PUT", body: JSON.stringify(data) });

export const deleteProvider = (id: string) =>
  apiFetch<void>(`/api/messaging/providers/${id}`, { method: "DELETE" });

export const testProvider = (id: string) =>
  apiFetch<{ success: boolean; message: string }>(`/api/messaging/providers/${id}/test`, { method: "POST" });
```

- [ ] **Step 3: Export apiFetch from api.ts if not already exported**

Check `frontend/src/lib/api.ts` — if `apiFetch` is not exported, add `export` to its declaration.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/sequences-api.ts frontend/src/lib/messaging-api.ts
git commit -m "feat(sequences): add frontend API functions for sequences and messaging providers"
```

---

## Task 11: Frontend — Sequence Templates List Page

**Files:**
- Create: `frontend/src/app/(app)/sequences/page.tsx`
- Modify: `frontend/src/app/(app)/layout.tsx` (add nav item)

- [ ] **Step 1: Add "Sequences" to sidebar navigation**

In the layout file, add a nav item with icon `Workflow` (from lucide-react) pointing to `/sequences`, placed after "Campaigns" or "Analytics" in the nav order.

- [ ] **Step 2: Create templates list page**

Create `frontend/src/app/(app)/sequences/page.tsx`:

Page should display:
- Header: "Sequence Templates" with "Create New" and "Import JSON" buttons
- Table with columns: Name, Trigger Type, Steps, Active (toggle), Created
- Click row → navigate to `/sequences/{id}`
- Import JSON button → opens dialog with textarea for pasting JSON + file upload
- Preview step before confirming import
- Use existing UI patterns from leads page: Card, Table, Badge, Button, Dialog components
- Pagination at bottom

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/page.tsx frontend/src/app/\(app\)/layout.tsx
git commit -m "feat(sequences): add sequence templates list page with import"
```

---

## Task 12: Frontend — Template Builder Page

**Files:**
- Create: `frontend/src/app/(app)/sequences/[id]/page.tsx`
- Create: `frontend/src/app/(app)/sequences/components/StepCard.tsx`

- [ ] **Step 1: Create StepCard component**

Each step is an expandable card showing:
- Header row: step name, channel badge, timing summary, drag handle, expand/collapse
- Expanded content:
  - Name input
  - Channel selector (dropdown: WhatsApp Template / WhatsApp Session / Voice Call / SMS)
  - Timing: type dropdown + value inputs (hours/days + optional time picker)
  - Skip conditions (optional toggle → field input + equals input)
  - Content section (conditional on channel/content_type):
    - If whatsapp_template: template name input + params table (name → value with {{var}} syntax)
    - If ai_generated: prompt textarea with {{variable}} highlighting + "Test Prompt" button + model selector
    - If voice_call: bot selector dropdown (fetched from /api/bots)
  - Reply handler toggle → AI prompt textarea + save_field input
  - Active toggle, delete button

- [ ] **Step 2: Create template builder page**

Page layout:
- Header: template name (editable), trigger type dropdown, trigger conditions editor (JSON), active toggle, Export JSON button
- Steps list: vertical stack of StepCard components, drag-to-reorder (use @dnd-kit or simple move up/down buttons)
- "Add Step" button at bottom
- Auto-save on field change (debounced) or explicit Save button
- "Test Prompt" button on AI steps opens PromptTestPanel (Task 13)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/\[id\]/page.tsx frontend/src/app/\(app\)/sequences/components/StepCard.tsx
git commit -m "feat(sequences): add template builder page with step cards"
```

---

## Task 13: Frontend — Prompt Test Panel

**Files:**
- Create: `frontend/src/app/(app)/sequences/components/PromptTestPanel.tsx`

- [ ] **Step 1: Create prompt test slide-over**

Component receives: `prompt: string`, `onClose: () => void`, `isOpen: boolean`

Layout (slide-over panel from right):
- Left section: prompt text displayed with {{variables}} highlighted (use regex to color them)
- Right section: form with input fields for each detected {{variable}} (auto-parsed from prompt)
- Model selector: Claude Sonnet / Haiku dropdown
- "Generate" button → calls testPrompt API → displays:
  - Generated output in a bordered text area
  - Stats bar: tokens used, latency, cost estimate
- "Try Again" button to regenerate
- History section: last 5 results shown as collapsible items for comparison
- Loading state with spinner during generation

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/components/PromptTestPanel.tsx
git commit -m "feat(sequences): add prompt test panel with variable detection and history"
```

---

## Task 14: Frontend — Engagement Monitor Page

**Files:**
- Create: `frontend/src/app/(app)/sequences/monitor/page.tsx`
- Create: `frontend/src/app/(app)/sequences/components/TouchpointTimeline.tsx`

- [ ] **Step 1: Create TouchpointTimeline component**

Visual timeline showing all touchpoints for a sequence instance:
- Vertical list of touchpoint cards
- Each card shows: step name, channel icon (MessageSquare for WhatsApp, Phone for voice, MessageCircle for SMS), scheduled time, status badge
- Status badges: pending (gray), generating (yellow), sent (green), failed (red), awaiting_reply (blue), replied (green with reply icon), skipped (gray strikethrough)
- Sent touchpoints: show generated_content preview (truncated), delivery time
- Reply touchpoints: show reply_text + reply_response
- Failed touchpoints: show error_message + "Retry" button
- Pending touchpoints: show countdown to scheduled_at

- [ ] **Step 2: Create engagement monitor page**

Page layout:
- Filters bar: template dropdown, status dropdown (active/completed/paused/cancelled), date range picker
- Table: lead name, phone, template name, current step / total steps, next touchpoint time, status badge
- Click row → expands inline to show TouchpointTimeline
- Pause / Resume / Cancel buttons on each row
- Refresh button + auto-refresh toggle (poll every 30s)
- Badge showing count of failed touchpoints needing attention

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/monitor/page.tsx frontend/src/app/\(app\)/sequences/components/TouchpointTimeline.tsx
git commit -m "feat(sequences): add engagement monitor page with touchpoint timeline"
```

---

## Task 15: Frontend — Import/Export Dialog + Lead Sequences Tab

**Files:**
- Create: `frontend/src/app/(app)/sequences/components/ImportExportDialog.tsx`
- Create: `frontend/src/app/(app)/leads/components/SequencesTab.tsx`

- [ ] **Step 1: Create import/export dialog**

Dialog component with two modes:
- **Export mode**: shows JSON in a read-only textarea with "Copy to Clipboard" and "Download as .json" buttons
- **Import mode**: file upload (accepts .json) OR paste textarea. "Preview" button validates and shows parsed template summary. "Import" button creates the template. Validation errors shown inline in red.

- [ ] **Step 2: Create lead sequences tab**

Component receives `leadId: string`. Shows:
- List of all sequence instances for this lead (fetch via `fetchInstances({ lead_id: leadId })`)
- Each instance shows: template name, status, started_at
- Click to expand → shows TouchpointTimeline (reuse from Task 14)
- If no sequences: "No engagement sequences for this lead" empty state

- [ ] **Step 3: Integrate tab into lead detail page**

In existing `frontend/src/app/(app)/leads/[leadId]/page.tsx`, add a "Sequences" tab alongside existing tabs. Render SequencesTab component when active.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/\(app\)/sequences/components/ImportExportDialog.tsx frontend/src/app/\(app\)/leads/components/SequencesTab.tsx frontend/src/app/\(app\)/leads/\[id\]/page.tsx
git commit -m "feat(sequences): add import/export dialog and lead sequences tab"
```

---

## Task 16: Frontend — Messaging Providers Settings Page

**Files:**
- Create: `frontend/src/app/(app)/settings/messaging/page.tsx`

- [ ] **Step 1: Create messaging providers page**

Page layout (following existing settings page pattern):
- Header: "Messaging Providers" with "Add Provider" button
- Table: provider name, type badge (WATI/AISensy/Twilio), default badge, created date
- Click row → edit dialog
- Add/Edit dialog:
  - Provider type dropdown: WATI, AISensy, Twilio WhatsApp, Twilio SMS
  - Name input
  - Credentials form (changes based on type):
    - WATI: API URL, API Token
    - AISensy: API URL, API Token, API Key
    - Twilio: Account SID, Auth Token, From Number
  - "Set as default" toggle
  - "Test Connection" button → calls test endpoint, shows success/error toast
- Delete confirmation dialog
- Link to this page from existing settings navigation

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/\(app\)/settings/messaging/page.tsx
git commit -m "feat(sequences): add messaging providers settings page"
```

---

## Task 17: End-to-End Verification

- [ ] **Step 1: Run all backend tests**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Run migration on dev database**

Run: `cd "/Users/animeshmahato/Wavelength v3" && alembic upgrade head`
Expected: Migration 025 applied successfully

- [ ] **Step 3: Start backend and verify endpoints**

Run: `cd "/Users/animeshmahato/Wavelength v3" && python -m uvicorn app.main:app --reload --port 8080`

Verify:
- `GET /api/sequences/templates` returns `{"items": [], "total": 0}`
- `POST /api/messaging/providers` with test data returns created provider
- `POST /api/sequences/test-prompt` with sample prompt returns Claude response
- Sequence scheduler logs show "sequence_scheduler_started"

- [ ] **Step 4: Start frontend and verify pages**

Run: `cd "/Users/animeshmahato/Wavelength v3/frontend" && npm run dev`

Verify:
- `/sequences` page loads with empty template list
- "Create New" opens create form
- `/settings/messaging` page loads
- Add provider form works with credential fields

- [ ] **Step 5: Integration test — create and trigger a sequence**

1. Create a messaging provider via UI
2. Create a sequence template with 2 steps (WhatsApp gift + voice call)
3. Trigger a test call that matches trigger conditions
4. Verify sequence instance created with touchpoints
5. Verify scheduler picks up due touchpoint and processes it
6. Check engagement monitor shows the sequence

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(sequences): engagement sequence engine complete — all components integrated"
```
