# Flow Builder Plan 2: Data Model & Flow Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the flow engine data layer (8 new tables), the graph-traversal engine, and adapt the scheduler to poll flow touchpoints alongside the existing linear sequence loop.

**Architecture:** New SQLAlchemy models mirror the existing `sequence.py` patterns (UUID PKs, `org_id` denormalization, JSONB configs, `server_default=text("gen_random_uuid()")`). The flow engine is a standalone module (`flow_engine.py`) that the scheduler calls. The existing linear engine remains untouched — two parallel polling loops coexist.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, SQLAlchemy 2.0 (async, mapped_column), Alembic, pytest

**Spec Reference:** `docs/superpowers/specs/2026-03-23-sequence-flow-builder-design.md` §3, §5

**Depends on:** Plan 1 (prerequisites) — rate limiter, business hours, AI router must exist.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `app/models/flow.py` | All 8 flow SQLAlchemy models |
| Create | `alembic/versions/032_add_flow_builder_tables.py` | Migration for all flow tables + indexes |
| Modify | `alembic/env.py` | Add `import app.models.flow` so Alembic sees new models |
| Create | `app/services/flow_engine.py` | Graph traversal engine: `node_completed()`, `activate_node()`, `evaluate_edges()` |
| Modify | `app/services/sequence_scheduler.py` | Add parallel flow touchpoint polling loop |
| Create | `tests/test_flow_models.py` | Model instantiation + constraint tests |
| Create | `tests/test_flow_engine.py` | Engine logic: edge evaluation, node activation, error paths |
| Create | `tests/test_flow_scheduler.py` | Scheduler integration: flow polling loop |

---

## Task 1: Flow Data Models (8 tables)

**Files:**
- Create: `app/models/flow.py`

- [ ] **Step 1: Write model tests**

Create `tests/test_flow_models.py`:

```python
"""Tests for flow builder SQLAlchemy models."""

import uuid
from datetime import datetime, timezone

import pytest

from app.models.flow import (
    FlowDefinition,
    FlowVersion,
    FlowNode,
    FlowEdge,
    FlowInstance,
    FlowTouchpoint,
    FlowTransition,
    FlowEvent,
)


class TestFlowDefinition:
    def test_create_minimal(self):
        org_id = uuid.uuid4()
        fd = FlowDefinition(
            org_id=org_id,
            name="Follow-up Flow",
            trigger_type="post_call",
        )
        assert fd.name == "Follow-up Flow"
        assert fd.org_id == org_id
        assert fd.trigger_type == "post_call"

    def test_trigger_conditions_default(self):
        fd = FlowDefinition(
            org_id=uuid.uuid4(),
            name="Test",
            trigger_type="manual",
        )
        # JSONB defaults are set by server_default, so in-memory they're None
        # until persisted. Just verify the column accepts dict.
        fd.trigger_conditions = {"goal_outcome": "interested"}
        assert fd.trigger_conditions["goal_outcome"] == "interested"

    def test_variables_accepts_list(self):
        fd = FlowDefinition(
            org_id=uuid.uuid4(),
            name="Test",
            trigger_type="manual",
            variables=[{"key": "event_date", "label": "Event Date"}],
        )
        assert len(fd.variables) == 1


class TestFlowVersion:
    def test_create(self):
        fv = FlowVersion(
            flow_id=uuid.uuid4(),
            version_number=1,
            status="draft",
        )
        assert fv.version_number == 1
        assert fv.status == "draft"
        assert fv.is_locked is False

    def test_published_version(self):
        fv = FlowVersion(
            flow_id=uuid.uuid4(),
            version_number=2,
            status="published",
            is_locked=True,
            published_at=datetime.now(timezone.utc),
            published_by=uuid.uuid4(),
        )
        assert fv.is_locked is True
        assert fv.published_at is not None


class TestFlowNode:
    def test_action_node(self):
        node = FlowNode(
            version_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            node_type="voice_call",
            name="Initial Call",
            position_x=100.0,
            position_y=200.0,
            config={
                "bot_id": str(uuid.uuid4()),
                "quick_retry": {"enabled": True, "max_attempts": 3, "interval_hours": 1},
                "send_window": {"enabled": True, "start": "09:00", "end": "19:00",
                                "days": ["mon", "tue", "wed", "thu", "fri"],
                                "timezone": "Asia/Kolkata"},
            },
        )
        assert node.node_type == "voice_call"
        assert node.config["quick_retry"]["max_attempts"] == 3

    def test_control_node(self):
        node = FlowNode(
            version_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            node_type="condition",
            name="Check Interest",
            position_x=300.0,
            position_y=200.0,
            config={
                "field": "call_analysis.interest_level",
                "operator": "in",
                "value": ["high", "medium"],
            },
        )
        assert node.node_type == "condition"

    def test_terminal_node(self):
        node = FlowNode(
            version_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            node_type="end",
            name="End",
            position_x=500.0,
            position_y=200.0,
            config={"end_reason": "completed"},
        )
        assert node.node_type == "end"


class TestFlowEdge:
    def test_create(self):
        version_id = uuid.uuid4()
        edge = FlowEdge(
            version_id=version_id,
            org_id=uuid.uuid4(),
            source_node_id=uuid.uuid4(),
            target_node_id=uuid.uuid4(),
            condition_label="picked_up",
            sort_order=1,
        )
        assert edge.condition_label == "picked_up"
        assert edge.sort_order == 1


class TestFlowInstance:
    def test_create_active(self):
        inst = FlowInstance(
            org_id=uuid.uuid4(),
            flow_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            lead_id=uuid.uuid4(),
            status="active",
        )
        assert inst.status == "active"
        assert inst.is_test is False

    def test_with_trigger_call(self):
        inst = FlowInstance(
            org_id=uuid.uuid4(),
            flow_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            lead_id=uuid.uuid4(),
            trigger_call_id=uuid.uuid4(),
            status="active",
            context_data={"lead_name": "John", "interest": "high"},
        )
        assert inst.trigger_call_id is not None
        assert inst.context_data["interest"] == "high"


class TestFlowTouchpoint:
    def test_create_pending(self):
        tp = FlowTouchpoint(
            instance_id=uuid.uuid4(),
            node_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            lead_id=uuid.uuid4(),
            node_snapshot={"node_type": "voice_call", "config": {}},
            status="pending",
            scheduled_at=datetime.now(timezone.utc),
        )
        assert tp.status == "pending"
        assert tp.retry_count == 0
        assert tp.max_retries == 2

    def test_completed_with_outcome(self):
        tp = FlowTouchpoint(
            instance_id=uuid.uuid4(),
            node_id=uuid.uuid4(),
            org_id=uuid.uuid4(),
            lead_id=uuid.uuid4(),
            node_snapshot={},
            status="completed",
            outcome="picked_up",
            scheduled_at=datetime.now(timezone.utc),
            executed_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        assert tp.outcome == "picked_up"


class TestFlowTransition:
    def test_create(self):
        tr = FlowTransition(
            instance_id=uuid.uuid4(),
            to_node_id=uuid.uuid4(),
            transitioned_at=datetime.now(timezone.utc),
        )
        assert tr.from_node_id is None  # null for entry transition
        assert tr.to_node_id is not None

    def test_with_edge(self):
        tr = FlowTransition(
            instance_id=uuid.uuid4(),
            from_node_id=uuid.uuid4(),
            to_node_id=uuid.uuid4(),
            edge_id=uuid.uuid4(),
            outcome_data={"outcome": "picked_up"},
            transitioned_at=datetime.now(timezone.utc),
        )
        assert tr.outcome_data["outcome"] == "picked_up"


class TestFlowEvent:
    def test_create_unconsumed(self):
        ev = FlowEvent(
            instance_id=uuid.uuid4(),
            event_type="call_completed",
            event_data={"call_id": str(uuid.uuid4()), "outcome": "picked_up"},
        )
        assert ev.consumed is False
        assert ev.event_type == "call_completed"

    def test_consume(self):
        ev = FlowEvent(
            instance_id=uuid.uuid4(),
            event_type="reply_received",
            event_data={"message": "Yes I'm interested"},
            consumed=False,
        )
        ev.consumed = True
        assert ev.consumed is True
```

Run: `pytest tests/test_flow_models.py -v`
Expected: ImportError (models don't exist yet)

- [ ] **Step 2: Implement all 8 models**

Create `app/models/flow.py`:

```python
"""Flow builder models — definitions, versions, nodes, edges, instances, touchpoints, transitions, events."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.bot_config import Base


class FlowDefinition(Base):
    """Top-level flow template. Replaces SequenceTemplate for flow-based sequences."""

    __tablename__ = "flow_definitions"
    __table_args__ = (
        Index("ix_flowdef_org", "org_id"),
        Index("ix_flowdef_org_active", "org_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)  # post_call, manual, campaign_complete
    trigger_conditions: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    max_active_per_lead: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    variables: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(timezone.utc)
    )


class FlowVersion(Base):
    """Immutable published snapshot. Leads are pinned to the version they enrolled on."""

    __tablename__ = "flow_versions"
    __table_args__ = (
        Index("ix_flowver_flow", "flow_id"),
        Index("ix_flowver_flow_status", "flow_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # draft, published, archived
    is_locked: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True  # FK to users table if needed
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FlowNode(Base):
    """A node in the flow graph. org_id denormalized for efficient RLS queries."""

    __tablename__ = "flow_nodes"
    __table_args__ = (
        Index("ix_flownode_version", "version_id"),
        Index("ix_flownode_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    # node_type values: voice_call, whatsapp_template, whatsapp_session, ai_generate_send,
    #   condition, delay_wait, wait_for_event, goal_met, end
    name: Mapped[str] = mapped_column(Text, nullable=False)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    position_y: Mapped[float] = mapped_column(Float, nullable=False, server_default=text("0"))
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FlowEdge(Base):
    """Directed edge between two nodes. condition_label determines which outcome follows this edge."""

    __tablename__ = "flow_edges"
    __table_args__ = (
        Index("ix_flowedge_version", "version_id"),
        Index("ix_flowedge_source", "source_node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False
    )
    condition_label: Mapped[str] = mapped_column(Text, nullable=False)  # picked_up, no_answer, default, etc.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class FlowInstance(Base):
    """A lead's journey through a flow. Pinned to a specific FlowVersion at enrollment."""

    __tablename__ = "flow_instances"
    __table_args__ = (
        Index("ix_flowinst_lead", "lead_id"),
        Index("ix_flowinst_org_status", "org_id", "status"),
        Index("ix_flowinst_flow_status", "flow_id", "status"),
        # Only one active instance per lead per flow
        Index(
            "uq_flowinst_flow_lead_active",
            "flow_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_definitions.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_versions.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False
    )
    trigger_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_logs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    # status values: active, paused, completed, cancelled, error
    current_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=True
    )
    context_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_test: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(timezone.utc)
    )


class FlowTouchpoint(Base):
    """Execution record for each node visit. Extends the concept of SequenceTouchpoint."""

    __tablename__ = "flow_touchpoints"
    __table_args__ = (
        Index("ix_flowtp_instance", "instance_id"),
        Index("ix_flowtp_org_status_scheduled", "org_id", "status", "scheduled_at"),
        Index("ix_flowtp_lead_org", "lead_id", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=False
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    node_snapshot: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    # status values: pending, executing, waiting, completed, failed, skipped
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    # outcome values: picked_up, no_answer, busy, replied, timed_out, failed, etc.
    generated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    messaging_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messaging_providers.id"), nullable=True
    )
    queued_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("call_queue.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(
        server_default=text("now()"), onupdate=lambda: datetime.now(timezone.utc)
    )


class FlowTransition(Base):
    """Audit trail for journey replay and debugging."""

    __tablename__ = "flow_transitions"
    __table_args__ = (
        Index("ix_flowtrans_instance", "instance_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False
    )
    from_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=True  # null for entry transition
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_nodes.id"), nullable=False
    )
    edge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_edges.id"), nullable=True
    )
    outcome_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    transitioned_at: Mapped[datetime] = mapped_column(nullable=False)


class FlowEvent(Base):
    """Event delivery mechanism for 'Wait for Event' nodes."""

    __tablename__ = "flow_events"
    __table_args__ = (
        Index("ix_flowevent_instance_consumed", "instance_id", "consumed"),
        Index("ix_flowevent_unconsumed", "consumed", "created_at",
              postgresql_where=text("consumed = false")),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    # event_type values: call_completed, reply_received, timeout, manual_advance
    event_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    consumed: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
```

Run: `pytest tests/test_flow_models.py -v`
Expected: All tests PASS (models instantiate correctly)

- [ ] **Step 3: Commit**

```bash
git add app/models/flow.py tests/test_flow_models.py
git commit -m "feat: add 8 flow builder SQLAlchemy models

FlowDefinition, FlowVersion, FlowNode, FlowEdge, FlowInstance,
FlowTouchpoint, FlowTransition, FlowEvent — following existing
sequence.py patterns with UUID PKs, org_id denormalization, and
JSONB config fields."
```

---

## Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/032_add_flow_builder_tables.py`
- Modify: `alembic/env.py`

- [ ] **Step 1: Register flow models with Alembic**

In `alembic/env.py`, add the import alongside existing model imports:

```python
# After the existing model imports (around line 13):
import app.models.flow  # noqa: F401
```

The exact insertion point is after the last existing `import app.models.*` line in `alembic/env.py`.

- [ ] **Step 2: Create the migration file**

Create `alembic/versions/032_add_flow_builder_tables.py`:

```python
"""Add flow builder tables: definitions, versions, nodes, edges, instances, touchpoints, transitions, events.

Revision ID: 032
Revises: 031
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- flow_definitions ---
    op.create_table(
        "flow_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("trigger_conditions", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("max_active_per_lead", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("variables", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowdef_org", "flow_definitions", ["org_id"])
    op.create_index("ix_flowdef_org_active", "flow_definitions", ["org_id", "is_active"])

    # --- flow_versions ---
    op.create_table(
        "flow_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowver_flow", "flow_versions", ["flow_id"])
    op.create_index("ix_flowver_flow_status", "flow_versions", ["flow_id", "status"])

    # --- flow_nodes ---
    op.create_table(
        "flow_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("position_x", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("position_y", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flownode_version", "flow_nodes", ["version_id"])
    op.create_index("ix_flownode_org", "flow_nodes", ["org_id"])

    # --- flow_edges ---
    op.create_table(
        "flow_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("condition_label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_flowedge_version", "flow_edges", ["version_id"])
    op.create_index("ix_flowedge_source", "flow_edges", ["source_node_id"])

    # --- flow_instances ---
    op.create_table(
        "flow_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_definitions.id"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_versions.id"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("trigger_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_logs.id"), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("current_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=True),
        sa.Column("context_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_test", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowinst_lead", "flow_instances", ["lead_id"])
    op.create_index("ix_flowinst_org_status", "flow_instances", ["org_id", "status"])
    op.create_index("ix_flowinst_flow_status", "flow_instances", ["flow_id", "status"])
    op.create_index(
        "uq_flowinst_flow_lead_active",
        "flow_instances",
        ["flow_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # --- flow_touchpoints ---
    op.create_table(
        "flow_touchpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("node_snapshot", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("2"), nullable=False),
        sa.Column("messaging_provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messaging_providers.id"), nullable=True),
        sa.Column("queued_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("call_queue.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowtp_instance", "flow_touchpoints", ["instance_id"])
    op.create_index("ix_flowtp_org_status_scheduled", "flow_touchpoints", ["org_id", "status", "scheduled_at"])
    op.create_index("ix_flowtp_lead_org", "flow_touchpoints", ["lead_id", "org_id"])

    # --- flow_transitions ---
    op.create_table(
        "flow_transitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=True),
        sa.Column("to_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_nodes.id"), nullable=False),
        sa.Column("edge_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_edges.id"), nullable=True),
        sa.Column("outcome_data", postgresql.JSONB(), nullable=True),
        sa.Column("transitioned_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_flowtrans_instance", "flow_transitions", ["instance_id"])

    # --- flow_events ---
    op.create_table(
        "flow_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("consumed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_flowevent_instance_consumed", "flow_events", ["instance_id", "consumed"])
    op.create_index(
        "ix_flowevent_unconsumed",
        "flow_events",
        ["consumed", "created_at"],
        postgresql_where=sa.text("consumed = false"),
    )


def downgrade() -> None:
    op.drop_table("flow_events")
    op.drop_table("flow_transitions")
    op.drop_table("flow_touchpoints")
    op.drop_table("flow_instances")
    op.drop_table("flow_edges")
    op.drop_table("flow_nodes")
    op.drop_table("flow_versions")
    op.drop_table("flow_definitions")
```

- [ ] **Step 3: Run migration (local verification)**

```bash
alembic upgrade head
```

Expected: All 8 tables created successfully. If no local DB, verify the migration file is syntactically valid:

```bash
python -c "import alembic.versions" 2>/dev/null || python -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('m', 'alembic/versions/032_add_flow_builder_tables.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('Migration file loads OK')
print(f'revision={mod.revision}, down_revision={mod.down_revision}')
"
```

- [ ] **Step 4: Commit**

```bash
git add app/models/flow.py alembic/versions/032_add_flow_builder_tables.py alembic/env.py
git commit -m "feat: add Alembic migration for 8 flow builder tables

Migration 032 creates flow_definitions, flow_versions, flow_nodes,
flow_edges, flow_instances, flow_touchpoints, flow_transitions, and
flow_events with all indexes. Registers flow models in alembic/env.py."
```

---

## Task 3: Flow Engine — Graph Traversal

**Files:**
- Create: `app/services/flow_engine.py`
- Create: `tests/test_flow_engine.py`

- [ ] **Step 1: Write engine tests**

Create `tests/test_flow_engine.py`:

```python
"""Tests for flow engine graph traversal logic."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.flow_engine import (
    evaluate_edges,
    get_node_category,
    NODE_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Pure function tests (no DB needed)
# ---------------------------------------------------------------------------


class TestGetNodeCategory:
    def test_action_nodes(self):
        for nt in ("voice_call", "whatsapp_template", "whatsapp_session", "ai_generate_send"):
            assert get_node_category(nt) == "action", f"{nt} should be action"

    def test_control_nodes(self):
        for nt in ("condition", "delay_wait", "wait_for_event"):
            assert get_node_category(nt) == "control", f"{nt} should be control"

    def test_terminal_nodes(self):
        for nt in ("goal_met", "end"):
            assert get_node_category(nt) == "terminal", f"{nt} should be terminal"

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown node_type"):
            get_node_category("unknown_type")


class TestEvaluateEdges:
    """Test edge matching logic with mock edge objects."""

    def _make_edge(self, condition_label: str, sort_order: int, target_node_id=None):
        edge = MagicMock()
        edge.condition_label = condition_label
        edge.sort_order = sort_order
        edge.target_node_id = target_node_id or uuid.uuid4()
        edge.id = uuid.uuid4()
        return edge

    def test_exact_match(self):
        edges = [
            self._make_edge("picked_up", 1),
            self._make_edge("no_answer", 2),
            self._make_edge("default", 99),
        ]
        matched = evaluate_edges(edges, "picked_up")
        assert matched is not None
        assert matched.condition_label == "picked_up"

    def test_fallback_to_default(self):
        edges = [
            self._make_edge("picked_up", 1),
            self._make_edge("no_answer", 2),
            self._make_edge("default", 99),
        ]
        matched = evaluate_edges(edges, "busy")
        assert matched is not None
        assert matched.condition_label == "default"

    def test_no_match_no_default(self):
        edges = [
            self._make_edge("picked_up", 1),
            self._make_edge("no_answer", 2),
        ]
        matched = evaluate_edges(edges, "busy")
        assert matched is None

    def test_sort_order_priority(self):
        """First matching edge by sort_order wins."""
        target_1 = uuid.uuid4()
        target_2 = uuid.uuid4()
        edges = [
            self._make_edge("picked_up", 2, target_2),
            self._make_edge("picked_up", 1, target_1),  # lower sort_order = higher priority
        ]
        matched = evaluate_edges(edges, "picked_up")
        assert matched.target_node_id == target_1

    def test_empty_edges(self):
        matched = evaluate_edges([], "picked_up")
        assert matched is None

    def test_condition_node_true_false(self):
        """Condition nodes emit 'true' or 'false' outcomes."""
        edges = [
            self._make_edge("true", 1),
            self._make_edge("false", 2),
        ]
        assert evaluate_edges(edges, "true").condition_label == "true"
        assert evaluate_edges(edges, "false").condition_label == "false"


class TestNodeCompleted:
    """Integration-style tests for node_completed using mocked DB session."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_instance(self):
        inst = MagicMock()
        inst.id = uuid.uuid4()
        inst.version_id = uuid.uuid4()
        inst.org_id = uuid.uuid4()
        inst.lead_id = uuid.uuid4()
        inst.status = "active"
        inst.current_node_id = uuid.uuid4()
        inst.context_data = {}
        return inst

    @pytest.fixture
    def mock_node(self):
        node = MagicMock()
        node.id = uuid.uuid4()
        node.node_type = "voice_call"
        node.version_id = uuid.uuid4()
        node.config = {}
        node.name = "Test Call"
        return node

    @pytest.mark.asyncio
    async def test_node_completed_no_matching_edge_sets_error(self, mock_db, mock_instance, mock_node):
        """When no edge matches the outcome, instance should be marked as error."""
        from app.services.flow_engine import node_completed

        # Mock: no edges returned
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        await node_completed(mock_db, mock_instance, mock_node, "some_unknown_outcome")

        assert mock_instance.status == "error"
        assert "no matching edge" in mock_instance.error_message.lower()

    @pytest.mark.asyncio
    async def test_node_completed_follows_matching_edge(self, mock_db, mock_instance, mock_node):
        """When an edge matches, transition to target node."""
        from app.services.flow_engine import node_completed

        target_node_id = uuid.uuid4()
        edge = MagicMock()
        edge.id = uuid.uuid4()
        edge.condition_label = "picked_up"
        edge.sort_order = 1
        edge.target_node_id = target_node_id

        # First execute: get edges
        edges_result = MagicMock()
        edges_result.scalars.return_value.all.return_value = [edge]

        # Second execute: get target node
        target_node = MagicMock()
        target_node.id = target_node_id
        target_node.node_type = "end"
        target_node.config = {"end_reason": "completed"}
        target_node.name = "End"
        target_node.version_id = mock_instance.version_id
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_node

        mock_db.execute.side_effect = [edges_result, target_result]

        await node_completed(mock_db, mock_instance, mock_node, "picked_up")

        # Should have transitioned — FlowTransition added
        assert mock_db.add.called
        assert mock_instance.current_node_id == target_node_id

    @pytest.mark.asyncio
    async def test_node_completed_end_node_completes_instance(self, mock_db, mock_instance, mock_node):
        """When target is an end node, instance should be completed."""
        from app.services.flow_engine import node_completed

        target_node_id = uuid.uuid4()
        edge = MagicMock()
        edge.id = uuid.uuid4()
        edge.condition_label = "picked_up"
        edge.sort_order = 1
        edge.target_node_id = target_node_id

        edges_result = MagicMock()
        edges_result.scalars.return_value.all.return_value = [edge]

        target_node = MagicMock()
        target_node.id = target_node_id
        target_node.node_type = "end"
        target_node.config = {"end_reason": "completed"}
        target_node.name = "End"
        target_node.version_id = mock_instance.version_id
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_node

        mock_db.execute.side_effect = [edges_result, target_result]

        await node_completed(mock_db, mock_instance, mock_node, "picked_up")

        assert mock_instance.status == "completed"
        assert mock_instance.completed_at is not None

    @pytest.mark.asyncio
    async def test_node_completed_goal_met_sets_completed(self, mock_db, mock_instance, mock_node):
        """goal_met node completes instance with goal data in context."""
        from app.services.flow_engine import node_completed

        target_node_id = uuid.uuid4()
        edge = MagicMock()
        edge.id = uuid.uuid4()
        edge.condition_label = "default"
        edge.sort_order = 1
        edge.target_node_id = target_node_id

        edges_result = MagicMock()
        edges_result.scalars.return_value.all.return_value = [edge]

        target_node = MagicMock()
        target_node.id = target_node_id
        target_node.node_type = "goal_met"
        target_node.config = {"goal_label": "booked_meeting"}
        target_node.name = "Goal: Meeting Booked"
        target_node.version_id = mock_instance.version_id
        target_result = MagicMock()
        target_result.scalar_one_or_none.return_value = target_node

        mock_db.execute.side_effect = [edges_result, target_result]

        await node_completed(mock_db, mock_instance, mock_node, "default")

        assert mock_instance.status == "completed"
        assert mock_instance.context_data.get("goal_label") == "booked_meeting"


class TestActivateNode:
    """Test activate_node logic for different node categories."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        return db

    @pytest.fixture
    def mock_instance(self):
        inst = MagicMock()
        inst.id = uuid.uuid4()
        inst.version_id = uuid.uuid4()
        inst.org_id = uuid.uuid4()
        inst.lead_id = uuid.uuid4()
        inst.status = "active"
        inst.context_data = {}
        return inst

    @pytest.mark.asyncio
    async def test_activate_action_node_creates_pending_touchpoint(self, mock_db, mock_instance):
        from app.services.flow_engine import activate_node

        node = MagicMock()
        node.id = uuid.uuid4()
        node.node_type = "voice_call"
        node.config = {"bot_id": str(uuid.uuid4()), "send_window": {"enabled": False}}
        node.name = "Call Lead"
        node.version_id = mock_instance.version_id

        await activate_node(mock_db, mock_instance, node)

        # Should add a FlowTouchpoint
        assert mock_db.add.called
        added_obj = mock_db.add.call_args[0][0]
        from app.models.flow import FlowTouchpoint
        assert isinstance(added_obj, FlowTouchpoint)
        assert added_obj.status == "pending"

    @pytest.mark.asyncio
    async def test_activate_delay_node_creates_future_touchpoint(self, mock_db, mock_instance):
        from app.services.flow_engine import activate_node

        node = MagicMock()
        node.id = uuid.uuid4()
        node.node_type = "delay_wait"
        node.config = {"delay_hours": 24}
        node.name = "Wait 24h"
        node.version_id = mock_instance.version_id

        await activate_node(mock_db, mock_instance, node)

        added_obj = mock_db.add.call_args[0][0]
        from app.models.flow import FlowTouchpoint
        assert isinstance(added_obj, FlowTouchpoint)
        # scheduled_at should be ~24h in the future
        now = datetime.now(timezone.utc)
        assert added_obj.scheduled_at > now + timedelta(hours=23)

    @pytest.mark.asyncio
    async def test_activate_wait_for_event_sets_waiting_status(self, mock_db, mock_instance):
        from app.services.flow_engine import activate_node

        node = MagicMock()
        node.id = uuid.uuid4()
        node.node_type = "wait_for_event"
        node.config = {"event_type": "reply_received", "timeout_hours": 48}
        node.name = "Wait for Reply"
        node.version_id = mock_instance.version_id

        await activate_node(mock_db, mock_instance, node)

        added_obj = mock_db.add.call_args[0][0]
        from app.models.flow import FlowTouchpoint
        assert isinstance(added_obj, FlowTouchpoint)
        assert added_obj.status == "waiting"
```

Run: `pytest tests/test_flow_engine.py -v`
Expected: ImportError (engine doesn't exist yet)

- [ ] **Step 2: Implement flow engine**

Create `app/services/flow_engine.py`:

```python
"""Flow engine — graph traversal, node activation, edge evaluation.

This module handles the core logic for executing flow-based sequences:
1. node_completed() — called when a touchpoint finishes, traverses to next node
2. activate_node() — creates touchpoints for the target node
3. evaluate_edges() — finds the matching outgoing edge for an outcome
4. evaluate_condition() — evaluates condition node expressions against context
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import (
    FlowEdge,
    FlowEvent,
    FlowInstance,
    FlowNode,
    FlowTouchpoint,
    FlowTransition,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NODE_CATEGORIES = {
    # Action nodes: schedule a touchpoint, wait for execution
    "voice_call": "action",
    "whatsapp_template": "action",
    "whatsapp_session": "action",
    "ai_generate_send": "action",
    # Control nodes: evaluate immediately, no external action
    "condition": "control",
    "delay_wait": "control",
    "wait_for_event": "control",
    # Terminal nodes: end the flow
    "goal_met": "terminal",
    "end": "terminal",
}

ACTION_NODE_TYPES = {k for k, v in NODE_CATEGORIES.items() if v == "action"}
CONTROL_NODE_TYPES = {k for k, v in NODE_CATEGORIES.items() if v == "control"}
TERMINAL_NODE_TYPES = {k for k, v in NODE_CATEGORIES.items() if v == "terminal"}


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def get_node_category(node_type: str) -> str:
    """Return 'action', 'control', or 'terminal' for a node type."""
    cat = NODE_CATEGORIES.get(node_type)
    if cat is None:
        raise ValueError(f"Unknown node_type: {node_type}")
    return cat


def evaluate_edges(edges: list, outcome: str):
    """Find the first matching edge for the given outcome.

    Edges are sorted by sort_order. First exact match wins.
    If no exact match, falls back to 'default' edge.
    Returns the matched edge or None.
    """
    sorted_edges = sorted(edges, key=lambda e: e.sort_order)
    default_edge = None
    for edge in sorted_edges:
        if edge.condition_label == outcome:
            return edge
        if edge.condition_label == "default":
            default_edge = edge
    return default_edge


def evaluate_condition(config: dict, context_data: dict) -> str:
    """Evaluate a condition node's expression against instance context.

    Returns 'true' or 'false' as the outcome string.

    Config schema:
        {
            "field": "call_analysis.interest_level",
            "operator": "in" | "eq" | "neq" | "gt" | "lt" | "contains" | "exists",
            "value": <comparison value>
        }
    """
    field_path = config.get("field", "")
    operator = config.get("operator", "eq")
    expected = config.get("value")

    # Resolve dotted field path from context_data
    actual = context_data
    for part in field_path.split("."):
        if isinstance(actual, dict):
            actual = actual.get(part)
        else:
            actual = None
            break

    if operator == "eq":
        return "true" if actual == expected else "false"
    elif operator == "neq":
        return "true" if actual != expected else "false"
    elif operator == "in":
        return "true" if actual in (expected or []) else "false"
    elif operator == "gt":
        try:
            return "true" if float(actual) > float(expected) else "false"
        except (TypeError, ValueError):
            return "false"
    elif operator == "lt":
        try:
            return "true" if float(actual) < float(expected) else "false"
        except (TypeError, ValueError):
            return "false"
    elif operator == "contains":
        return "true" if expected and expected in str(actual or "") else "false"
    elif operator == "exists":
        return "true" if actual is not None else "false"
    else:
        logger.warning("unknown_condition_operator", operator=operator)
        return "false"


def _snapshot_node(node) -> dict:
    """Create a frozen snapshot of node config for the touchpoint record."""
    return {
        "node_type": node.node_type,
        "name": node.name,
        "config": node.config,
    }


# ---------------------------------------------------------------------------
# DB-dependent functions
# ---------------------------------------------------------------------------


async def node_completed(
    db: AsyncSession,
    instance: FlowInstance,
    node: FlowNode,
    outcome: str,
    outcome_data: dict | None = None,
) -> None:
    """Called when a node finishes execution. Traverses the graph to the next node.

    Steps:
    1. Record FlowTransition
    2. Get outgoing edges, evaluate against outcome
    3. Transition to target node (activate it)
    4. Update instance.current_node_id
    On no matching edge → mark instance as error.
    """
    log = logger.bind(
        instance_id=str(instance.id),
        node_id=str(node.id),
        node_type=node.node_type,
        outcome=outcome,
    )

    # 1. Get outgoing edges sorted by sort_order
    result = await db.execute(
        select(FlowEdge)
        .where(FlowEdge.source_node_id == node.id)
        .order_by(FlowEdge.sort_order)
    )
    edges = result.scalars().all()

    # 2. Evaluate edges
    matched_edge = evaluate_edges(edges, outcome)

    if matched_edge is None:
        log.error("flow_no_matching_edge", available_edges=[e.condition_label for e in edges])
        instance.status = "error"
        instance.error_message = f"No matching edge for outcome '{outcome}' on node '{node.name}'"
        # Still record the transition attempt
        transition = FlowTransition(
            instance_id=instance.id,
            from_node_id=node.id,
            to_node_id=node.id,  # self-reference for error
            outcome_data={"outcome": outcome, "error": "no_matching_edge", **(outcome_data or {})},
            transitioned_at=datetime.now(timezone.utc),
        )
        db.add(transition)
        await db.commit()
        return

    # 3. Fetch target node
    target_result = await db.execute(
        select(FlowNode).where(FlowNode.id == matched_edge.target_node_id)
    )
    target_node = target_result.scalar_one_or_none()
    if target_node is None:
        log.error("flow_target_node_not_found", target_node_id=str(matched_edge.target_node_id))
        instance.status = "error"
        instance.error_message = f"Target node {matched_edge.target_node_id} not found"
        await db.commit()
        return

    # 4. Record transition
    transition = FlowTransition(
        instance_id=instance.id,
        from_node_id=node.id,
        to_node_id=target_node.id,
        edge_id=matched_edge.id,
        outcome_data={"outcome": outcome, **(outcome_data or {})},
        transitioned_at=datetime.now(timezone.utc),
    )
    db.add(transition)

    # 5. Update instance pointer
    instance.current_node_id = target_node.id
    log.info("flow_transition", target_node=target_node.name, target_type=target_node.node_type,
             edge_label=matched_edge.condition_label)

    # 6. Activate target node
    await activate_node(db, instance, target_node)

    await db.commit()


async def activate_node(
    db: AsyncSession,
    instance: FlowInstance,
    node: FlowNode,
) -> None:
    """Activate a node — create the appropriate touchpoint or handle immediately.

    - Action nodes: create FlowTouchpoint(status=pending, scheduled_at=now or send_window)
    - Control nodes:
        - condition: evaluate immediately, call node_completed recursively
        - delay_wait: create FlowTouchpoint(status=pending, scheduled_at=now+delay)
        - wait_for_event: create FlowTouchpoint(status=waiting)
    - Terminal nodes: complete/cancel the instance
    """
    log = logger.bind(
        instance_id=str(instance.id),
        node_id=str(node.id),
        node_type=node.node_type,
    )

    category = get_node_category(node.node_type)
    now = datetime.now(timezone.utc)

    if category == "terminal":
        await _handle_terminal_node(db, instance, node, now, log)

    elif category == "action":
        await _handle_action_node(db, instance, node, now, log)

    elif category == "control":
        await _handle_control_node(db, instance, node, now, log)


async def _handle_terminal_node(db, instance, node, now, log):
    """Handle goal_met and end nodes — complete the instance."""
    if node.node_type == "goal_met":
        goal_label = node.config.get("goal_label", "goal_met")
        instance.context_data = {**instance.context_data, "goal_label": goal_label}
        log.info("flow_goal_met", goal_label=goal_label)

    end_reason = node.config.get("end_reason", node.node_type)
    instance.status = "completed"
    instance.completed_at = now
    instance.context_data = {**instance.context_data, "end_reason": end_reason}
    log.info("flow_instance_completed", end_reason=end_reason)

    # Record a terminal touchpoint for audit trail
    tp = FlowTouchpoint(
        instance_id=instance.id,
        node_id=node.id,
        org_id=instance.org_id,
        lead_id=instance.lead_id,
        node_snapshot=_snapshot_node(node),
        status="completed",
        scheduled_at=now,
        executed_at=now,
        completed_at=now,
        outcome=end_reason,
    )
    db.add(tp)


async def _handle_action_node(db, instance, node, now, log):
    """Create a pending touchpoint for action nodes (voice_call, whatsapp_*, ai_generate_send)."""
    scheduled_at = now

    # Apply send_window if configured
    send_window = node.config.get("send_window")
    if send_window and send_window.get("enabled"):
        # The scheduler will defer execution if outside business hours.
        # We schedule for now and let the scheduler apply the window check.
        pass

    tp = FlowTouchpoint(
        instance_id=instance.id,
        node_id=node.id,
        org_id=instance.org_id,
        lead_id=instance.lead_id,
        node_snapshot=_snapshot_node(node),
        status="pending",
        scheduled_at=scheduled_at,
    )
    db.add(tp)
    log.info("flow_touchpoint_created", status="pending", scheduled_at=str(scheduled_at))


async def _handle_control_node(db, instance, node, now, log):
    """Handle control nodes: condition (immediate), delay_wait (future), wait_for_event (waiting)."""
    if node.node_type == "condition":
        # Evaluate immediately and traverse
        outcome = evaluate_condition(node.config, instance.context_data)
        log.info("flow_condition_evaluated", outcome=outcome)

        # Record a completed touchpoint for audit
        tp = FlowTouchpoint(
            instance_id=instance.id,
            node_id=node.id,
            org_id=instance.org_id,
            lead_id=instance.lead_id,
            node_snapshot=_snapshot_node(node),
            status="completed",
            scheduled_at=now,
            executed_at=now,
            completed_at=now,
            outcome=outcome,
        )
        db.add(tp)

        # Immediately traverse to next node
        await node_completed(db, instance, node, outcome)

    elif node.node_type == "delay_wait":
        delay_hours = node.config.get("delay_hours", 0)
        delay_minutes = node.config.get("delay_minutes", 0)
        scheduled_at = now + timedelta(hours=delay_hours, minutes=delay_minutes)

        tp = FlowTouchpoint(
            instance_id=instance.id,
            node_id=node.id,
            org_id=instance.org_id,
            lead_id=instance.lead_id,
            node_snapshot=_snapshot_node(node),
            status="pending",
            scheduled_at=scheduled_at,
        )
        db.add(tp)
        log.info("flow_delay_scheduled", scheduled_at=str(scheduled_at), delay_hours=delay_hours)

    elif node.node_type == "wait_for_event":
        # Create a waiting touchpoint — the scheduler polls for matching FlowEvents
        timeout_hours = node.config.get("timeout_hours", 24)
        timeout_at = now + timedelta(hours=timeout_hours)

        tp = FlowTouchpoint(
            instance_id=instance.id,
            node_id=node.id,
            org_id=instance.org_id,
            lead_id=instance.lead_id,
            node_snapshot=_snapshot_node(node),
            status="waiting",
            scheduled_at=timeout_at,  # scheduled_at = timeout deadline
        )
        db.add(tp)
        log.info("flow_waiting_for_event",
                 event_type=node.config.get("event_type"),
                 timeout_at=str(timeout_at))


async def process_flow_touchpoint(db: AsyncSession, touchpoint: FlowTouchpoint) -> None:
    """Process a due flow touchpoint. Called by the scheduler.

    For action nodes: this is where actual execution happens (call, message, etc).
    For delay_wait nodes: just mark complete and traverse.
    For wait_for_event nodes: check timeout.
    """
    log = logger.bind(
        touchpoint_id=str(touchpoint.id),
        node_type=touchpoint.node_snapshot.get("node_type"),
        status=touchpoint.status,
    )

    now = datetime.now(timezone.utc)
    node_type = touchpoint.node_snapshot.get("node_type")

    # Fetch the instance
    inst_result = await db.execute(
        select(FlowInstance).where(FlowInstance.id == touchpoint.instance_id)
    )
    instance = inst_result.scalar_one_or_none()
    if not instance or instance.status != "active":
        log.info("flow_touchpoint_skip_inactive_instance")
        touchpoint.status = "skipped"
        await db.commit()
        return

    # Fetch the node
    node_result = await db.execute(
        select(FlowNode).where(FlowNode.id == touchpoint.node_id)
    )
    node = node_result.scalar_one_or_none()
    if not node:
        log.error("flow_touchpoint_node_not_found")
        touchpoint.status = "failed"
        touchpoint.error_message = "Node not found"
        await db.commit()
        return

    if node_type == "delay_wait":
        # Delay expired — mark complete and traverse with 'default' outcome
        touchpoint.status = "completed"
        touchpoint.executed_at = now
        touchpoint.completed_at = now
        touchpoint.outcome = "default"
        log.info("flow_delay_completed")
        await node_completed(db, instance, node, "default")
        return

    if node_type in ACTION_NODE_TYPES:
        # Execute the action (call, message, etc.)
        touchpoint.status = "executing"
        touchpoint.executed_at = now
        await db.commit()

        try:
            outcome = await _execute_action(db, touchpoint, instance, node)
            touchpoint.status = "completed"
            touchpoint.completed_at = datetime.now(timezone.utc)
            touchpoint.outcome = outcome
            log.info("flow_action_completed", outcome=outcome)
            await node_completed(db, instance, node, outcome)
        except Exception as exc:
            log.exception("flow_action_failed")
            touchpoint.retry_count += 1
            if touchpoint.retry_count < touchpoint.max_retries:
                # Re-schedule with backoff
                backoff_minutes = touchpoint.retry_count * 5
                touchpoint.status = "pending"
                touchpoint.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
                touchpoint.error_message = str(exc)
                log.info("flow_action_retry", retry=touchpoint.retry_count, backoff_min=backoff_minutes)
            else:
                touchpoint.status = "failed"
                touchpoint.error_message = str(exc)
                touchpoint.completed_at = datetime.now(timezone.utc)
                touchpoint.outcome = "failed"
                await node_completed(db, instance, node, "failed")
            await db.commit()
        return

    log.warning("flow_touchpoint_unhandled_type", node_type=node_type)


async def process_waiting_touchpoints(db: AsyncSession) -> int:
    """Check waiting touchpoints for matching events or timeouts. Returns count processed."""
    now = datetime.now(timezone.utc)
    processed = 0

    # Find all waiting touchpoints
    result = await db.execute(
        select(FlowTouchpoint).where(FlowTouchpoint.status == "waiting")
    )
    waiting_tps = result.scalars().all()

    for tp in waiting_tps:
        node_config = tp.node_snapshot.get("config", {})
        event_type = node_config.get("event_type")

        # Check for matching unconsumed event
        event_result = await db.execute(
            select(FlowEvent).where(
                FlowEvent.instance_id == tp.instance_id,
                FlowEvent.event_type == event_type,
                FlowEvent.consumed == False,  # noqa: E712
            ).order_by(FlowEvent.created_at)
            .limit(1)
        )
        event = event_result.scalar_one_or_none()

        if event:
            # Consume the event and complete the touchpoint
            event.consumed = True
            tp.status = "completed"
            tp.completed_at = now
            tp.outcome = event.event_type

            # Fetch instance and node for traversal
            inst_result = await db.execute(
                select(FlowInstance).where(FlowInstance.id == tp.instance_id)
            )
            instance = inst_result.scalar_one_or_none()
            node_result = await db.execute(
                select(FlowNode).where(FlowNode.id == tp.node_id)
            )
            node = node_result.scalar_one_or_none()

            if instance and node and instance.status == "active":
                await node_completed(db, instance, node, event.event_type,
                                     outcome_data=event.event_data)
                processed += 1
                logger.info("flow_event_consumed",
                            touchpoint_id=str(tp.id),
                            event_type=event.event_type)

        elif tp.scheduled_at <= now:
            # Timeout — scheduled_at is the timeout deadline for waiting touchpoints
            tp.status = "completed"
            tp.completed_at = now
            timeout_label = node_config.get("timeout_label", "timed_out")
            tp.outcome = timeout_label

            inst_result = await db.execute(
                select(FlowInstance).where(FlowInstance.id == tp.instance_id)
            )
            instance = inst_result.scalar_one_or_none()
            node_result = await db.execute(
                select(FlowNode).where(FlowNode.id == tp.node_id)
            )
            node = node_result.scalar_one_or_none()

            if instance and node and instance.status == "active":
                await node_completed(db, instance, node, timeout_label)
                processed += 1
                logger.info("flow_event_timeout",
                            touchpoint_id=str(tp.id),
                            timeout_label=timeout_label)

    if processed > 0:
        await db.commit()

    return processed


async def _execute_action(
    db: AsyncSession,
    touchpoint: FlowTouchpoint,
    instance: FlowInstance,
    node: FlowNode,
) -> str:
    """Execute an action node. Returns the outcome string.

    This delegates to the appropriate channel handler:
    - voice_call → enqueue in call_queue
    - whatsapp_template → send via messaging_client
    - whatsapp_session → send via messaging_client
    - ai_generate_send → generate content then send

    NOTE: Actual channel handlers are implemented in Plan 3 (API & Integration).
    This stub returns 'executed' for now. Each channel will be wired in later.
    """
    node_type = node.node_type
    config = node.config

    if node_type == "voice_call":
        # TODO (Plan 3): Enqueue call via call_queue, return actual outcome from callback
        logger.info("flow_action_voice_call_stub",
                     bot_id=config.get("bot_id"),
                     touchpoint_id=str(touchpoint.id))
        return "executed"

    elif node_type == "whatsapp_template":
        # TODO (Plan 3): Send template via messaging_client
        logger.info("flow_action_whatsapp_template_stub",
                     template=config.get("template_name"),
                     touchpoint_id=str(touchpoint.id))
        return "executed"

    elif node_type == "whatsapp_session":
        # TODO (Plan 3): Generate AI content + send session message
        logger.info("flow_action_whatsapp_session_stub",
                     touchpoint_id=str(touchpoint.id))
        return "executed"

    elif node_type == "ai_generate_send":
        # TODO (Plan 3): Generate with AI router, send via channel
        logger.info("flow_action_ai_generate_stub",
                     touchpoint_id=str(touchpoint.id))
        return "executed"

    else:
        raise ValueError(f"Unknown action node type: {node_type}")
```

Run: `pytest tests/test_flow_engine.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add app/services/flow_engine.py tests/test_flow_engine.py
git commit -m "feat: implement flow engine with graph traversal

Core engine with node_completed(), activate_node(), evaluate_edges(),
evaluate_condition(), process_flow_touchpoint(), and
process_waiting_touchpoints(). Action execution stubs for Plan 3."
```

---

## Task 4: Scheduler Adaptation — Parallel Flow Polling Loop

**Files:**
- Modify: `app/services/sequence_scheduler.py`
- Create: `tests/test_flow_scheduler.py`

- [ ] **Step 1: Write scheduler integration tests**

Create `tests/test_flow_scheduler.py`:

```python
"""Tests for flow scheduler polling loop integration."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFlowSchedulerBatch:
    """Test the flow touchpoint polling logic."""

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_process_flow_batch_finds_due_touchpoints(self):
        """The flow batch should query for pending touchpoints with scheduled_at <= now."""
        from app.services.sequence_scheduler import _process_flow_batch

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_db = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # No touchpoints due
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db.execute.return_value = mock_result

            with patch("app.services.sequence_scheduler.flow_engine") as mock_engine:
                await _process_flow_batch()
                # Should have queried the DB
                assert mock_db.execute.called

    @pytest.mark.asyncio
    async def test_process_flow_batch_calls_process_touchpoint(self):
        """Due touchpoints should be processed by flow_engine.process_flow_touchpoint."""
        from app.services.sequence_scheduler import _process_flow_batch

        tp = MagicMock()
        tp.id = uuid.uuid4()
        tp.status = "pending"

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_db = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [tp]
            mock_db.execute.return_value = mock_result

            with patch("app.services.sequence_scheduler.flow_engine") as mock_engine:
                mock_engine.process_flow_touchpoint = AsyncMock()
                mock_engine.process_waiting_touchpoints = AsyncMock(return_value=0)

                # Mock the per-touchpoint DB session
                mock_tp_db = AsyncMock()
                mock_tp_result = MagicMock()
                mock_tp_result.scalar_one_or_none.return_value = tp
                mock_tp_db.execute.return_value = mock_tp_result

                with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx2:
                    mock_ctx2.return_value.__aenter__ = AsyncMock(return_value=mock_tp_db)
                    mock_ctx2.return_value.__aexit__ = AsyncMock(return_value=False)
                    await _process_flow_batch()

    @pytest.mark.asyncio
    async def test_process_flow_batch_checks_waiting_events(self):
        """Each batch should also check waiting touchpoints for events/timeouts."""
        from app.services.sequence_scheduler import _process_flow_batch

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_db = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db.execute.return_value = mock_result

            with patch("app.services.sequence_scheduler.flow_engine") as mock_engine:
                mock_engine.process_waiting_touchpoints = AsyncMock(return_value=0)
                await _process_flow_batch()
                mock_engine.process_waiting_touchpoints.assert_called_once()
```

Run: `pytest tests/test_flow_scheduler.py -v`
Expected: ImportError (`_process_flow_batch` doesn't exist yet)

- [ ] **Step 2: Add flow polling loop to scheduler**

Read the current `app/services/sequence_scheduler.py` and add the following changes:

**a) Add flow engine import at the top (after existing imports):**

```python
from app.models.flow import FlowTouchpoint, FlowInstance
from app.services import flow_engine
```

**b) Add `FLOW_POLL_INTERVAL` constant:**

```python
FLOW_POLL_INTERVAL = 10  # seconds — same cadence as linear sequences
```

**c) Add `_flow_task` tracking variable alongside existing `_task`:**

```python
_flow_task: asyncio.Task | None = None
```

**d) Modify `start()` to launch both loops:**

```python
def start():
    """Start the sequence scheduler background tasks (linear + flow)."""
    global _task, _flow_task, _shutdown
    _shutdown = False
    _task = asyncio.create_task(_scheduler_loop())
    _flow_task = asyncio.create_task(_flow_scheduler_loop())
    logger.info("sequence_scheduler_started", poll_interval=POLL_INTERVAL)
    logger.info("flow_scheduler_started", poll_interval=FLOW_POLL_INTERVAL)
```

**e) Modify `stop()` to cancel both tasks:**

```python
async def stop():
    """Stop both schedulers gracefully."""
    global _shutdown, _task, _flow_task
    _shutdown = True
    for t in [_task, _flow_task]:
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    _task = None
    _flow_task = None
    logger.info("sequence_scheduler_stopped")
    logger.info("flow_scheduler_stopped")
```

**f) Add the flow scheduler loop and batch processor (new functions at the bottom of the file):**

```python
async def _flow_scheduler_loop():
    """Flow engine polling loop — runs alongside the linear sequence loop."""
    cycle_count = 0
    while not _shutdown:
        try:
            await _process_flow_batch()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("flow_scheduler_error")

        # Every 5th cycle, retry failed flow touchpoints
        cycle_count += 1
        if cycle_count % 5 == 0:
            try:
                await _retry_failed_flow_touchpoints()
            except Exception:
                logger.exception("flow_retry_failed_error")

        await asyncio.sleep(FLOW_POLL_INTERVAL)


async def _process_flow_batch():
    """Find and process all due flow touchpoints + check waiting events."""
    now = datetime.utcnow()

    async with get_db_session() as db:
        # 1. Poll pending flow touchpoints that are due
        result = await db.execute(
            select(FlowTouchpoint)
            .where(
                FlowTouchpoint.status == "pending",
                FlowTouchpoint.scheduled_at <= now,
            )
            .join(FlowInstance, FlowInstance.id == FlowTouchpoint.instance_id)
            .where(FlowInstance.status == "active")
            .order_by(FlowTouchpoint.scheduled_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        touchpoints = result.scalars().all()

        if touchpoints:
            logger.info("flow_scheduler_batch", count=len(touchpoints))

            semaphore = asyncio.Semaphore(MAX_CONCURRENT)

            async def _process_one_flow_tp(tp_id):
                async with semaphore:
                    async with get_db_session() as tp_db:
                        tp_result = await tp_db.execute(
                            select(FlowTouchpoint)
                            .where(FlowTouchpoint.id == tp_id)
                            .with_for_update(skip_locked=True)
                        )
                        tp = tp_result.scalar_one_or_none()
                        if not tp or tp.status != "pending":
                            return

                        try:
                            await flow_engine.process_flow_touchpoint(tp_db, tp)
                        except Exception:
                            logger.exception("flow_touchpoint_processing_failed",
                                             touchpoint_id=str(tp_id))
                            tp.status = "failed"
                            tp.error_message = "Unexpected processing error"
                            tp.retry_count += 1
                            await tp_db.commit()

            tasks = [asyncio.create_task(_process_one_flow_tp(tp.id)) for tp in touchpoints]
            await asyncio.gather(*tasks, return_exceptions=True)

        # Release the FOR UPDATE lock
        await db.commit()

    # 2. Check waiting touchpoints for events/timeouts (separate session)
    async with get_db_session() as db:
        await flow_engine.process_waiting_touchpoints(db)


async def _retry_failed_flow_touchpoints():
    """Re-queue failed flow touchpoints that haven't hit max retries."""
    async with get_db_session() as db:
        result = await db.execute(
            select(FlowTouchpoint).where(
                FlowTouchpoint.status == "failed",
                FlowTouchpoint.retry_count < FlowTouchpoint.max_retries,
            )
        )
        retryable = result.scalars().all()
        for tp in retryable:
            tp.status = "pending"
            logger.info("flow_touchpoint_retry", touchpoint_id=str(tp.id), retry=tp.retry_count)
        if retryable:
            await db.commit()
```

Run: `pytest tests/test_flow_scheduler.py -v`
Expected: All tests PASS

- [ ] **Step 3: Verify existing scheduler tests still pass**

Run: `pytest tests/ -v --timeout=30 -k "sequence"`
Expected: No regressions in existing sequence tests

- [ ] **Step 4: Commit**

```bash
git add app/services/sequence_scheduler.py tests/test_flow_scheduler.py
git commit -m "feat: add parallel flow polling loop to scheduler

Scheduler now runs two loops: linear sequence touchpoints (existing)
and flow touchpoints (new). Flow loop polls pending FlowTouchpoints,
processes them via flow_engine, and checks waiting touchpoints for
events/timeouts. Same bounded concurrency pattern as linear loop."
```

---

## Task 5: Condition Evaluation Tests

**Files:**
- Modify: `tests/test_flow_engine.py` (add condition evaluation tests)

- [ ] **Step 1: Add comprehensive condition tests**

Append to `tests/test_flow_engine.py`:

```python
class TestEvaluateCondition:
    """Test condition node evaluation against context data."""

    def test_eq_match(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "interest_level", "operator": "eq", "value": "high"}
        assert evaluate_condition(config, {"interest_level": "high"}) == "true"

    def test_eq_no_match(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "interest_level", "operator": "eq", "value": "high"}
        assert evaluate_condition(config, {"interest_level": "low"}) == "false"

    def test_neq(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "status", "operator": "neq", "value": "cancelled"}
        assert evaluate_condition(config, {"status": "active"}) == "true"
        assert evaluate_condition(config, {"status": "cancelled"}) == "false"

    def test_in_operator(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "interest_level", "operator": "in", "value": ["high", "medium"]}
        assert evaluate_condition(config, {"interest_level": "high"}) == "true"
        assert evaluate_condition(config, {"interest_level": "low"}) == "false"

    def test_gt_operator(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "score", "operator": "gt", "value": 50}
        assert evaluate_condition(config, {"score": 75}) == "true"
        assert evaluate_condition(config, {"score": 30}) == "false"

    def test_lt_operator(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "attempts", "operator": "lt", "value": 3}
        assert evaluate_condition(config, {"attempts": 1}) == "true"
        assert evaluate_condition(config, {"attempts": 5}) == "false"

    def test_contains_operator(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "notes", "operator": "contains", "value": "interested"}
        assert evaluate_condition(config, {"notes": "Lead seems very interested"}) == "true"
        assert evaluate_condition(config, {"notes": "Not available"}) == "false"

    def test_exists_operator(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "email", "operator": "exists", "value": None}
        assert evaluate_condition(config, {"email": "a@b.com"}) == "true"
        assert evaluate_condition(config, {"phone": "123"}) == "false"

    def test_nested_field_path(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "call_analysis.interest_level", "operator": "eq", "value": "high"}
        context = {"call_analysis": {"interest_level": "high", "sentiment": "positive"}}
        assert evaluate_condition(config, context) == "true"

    def test_deeply_nested_field(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "call_analysis.goals.primary", "operator": "eq", "value": "booking"}
        context = {"call_analysis": {"goals": {"primary": "booking"}}}
        assert evaluate_condition(config, context) == "true"

    def test_missing_nested_field(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "call_analysis.interest_level", "operator": "eq", "value": "high"}
        context = {"other_data": "foo"}
        assert evaluate_condition(config, context) == "false"

    def test_unknown_operator_returns_false(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "x", "operator": "regex", "value": ".*"}
        assert evaluate_condition(config, {"x": "test"}) == "false"

    def test_gt_with_non_numeric_returns_false(self):
        from app.services.flow_engine import evaluate_condition
        config = {"field": "name", "operator": "gt", "value": 5}
        assert evaluate_condition(config, {"name": "Alice"}) == "false"
```

Run: `pytest tests/test_flow_engine.py -v`
Expected: All tests PASS (including existing + new condition tests)

- [ ] **Step 2: Commit**

```bash
git add tests/test_flow_engine.py
git commit -m "test: add comprehensive condition evaluation tests

Covers eq, neq, in, gt, lt, contains, exists operators plus nested
field paths and edge cases (missing fields, non-numeric gt)."
```

---

## Summary

| Task | What it does | Files |
|------|-------------|-------|
| 1 | 8 SQLAlchemy flow models | `app/models/flow.py`, `tests/test_flow_models.py` |
| 2 | Alembic migration for all tables | `alembic/versions/032_add_flow_builder_tables.py`, `alembic/env.py` |
| 3 | Flow engine: graph traversal + node activation | `app/services/flow_engine.py`, `tests/test_flow_engine.py` |
| 4 | Scheduler: parallel flow polling loop | `app/services/sequence_scheduler.py`, `tests/test_flow_scheduler.py` |
| 5 | Condition evaluation tests | `tests/test_flow_engine.py` |

**Total:** 5 tasks, ~15 steps, 5 commits.

After completing this plan, proceed to **Plan 3: Flow CRUD API & Channel Integration**.
