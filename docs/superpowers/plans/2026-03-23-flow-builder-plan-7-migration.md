# Flow Builder Plan 7: Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate from the linear sequence engine to the flow builder engine in three phases: coexistence (both engines running), auto-convert (linear templates to flow definitions), and deprecation (sunset linear engine). Also implement flow export/import.

**Architecture:** The migration is additive — no existing tables are dropped until Phase 3. The `SequenceInstance` table gets an `engine_type` column for routing. The scheduler runs dual polling loops. A migration script converts `SequenceTemplate` + `SequenceStep` rows into `FlowDefinition` + `FlowVersion` + `FlowNode` + `FlowEdge` rows. Export/import uses a portable JSON format.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, SQLAlchemy (async), Alembic, pytest

**Spec Reference:** `docs/superpowers/specs/2026-03-23-sequence-flow-builder-design.md` §13, §15

**Dependencies:** Plans 1-6 must be complete (flow tables, flow engine, flow API, scheduler adaptation all exist).

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `alembic/versions/xxxx_add_engine_type_to_sequence_instance.py` | Add `engine_type` column migration |
| Modify | `app/models/sequence.py` | Add `engine_type` column to `SequenceInstance` |
| Modify | `app/services/sequence_scheduler.py` | Dual-loop: linear + flow polling |
| Create | `app/services/flow_migrator.py` | Convert SequenceTemplate → FlowDefinition |
| Create | `app/api/flow_migration.py` | Migration admin endpoints |
| Modify | `app/api/flows.py` | Add export/import endpoints |
| Modify | `app/api/sequences.py` | Add deprecation warnings |
| Modify | `app/main.py` | Register migration router |
| Create | `tests/test_flow_migrator.py` | Tests for template-to-flow conversion |
| Create | `tests/test_flow_export_import.py` | Tests for export/import |
| Create | `tests/test_scheduler_dual_loop.py` | Tests for dual-loop scheduler |
| Create | `tests/test_migration_api.py` | Tests for migration admin endpoints |

---

## Task 1: Add `engine_type` Column to SequenceInstance

**Files:**
- Modify: `app/models/sequence.py`
- Create: `alembic/versions/xxxx_add_engine_type_to_sequence_instance.py`

- [ ] **Step 1: Add engine_type to SequenceInstance model**

In `app/models/sequence.py`, add the `engine_type` column to `SequenceInstance`:

```python
# In class SequenceInstance, after the status column (line ~104):
    engine_type: Mapped[str] = mapped_column(
        Text, server_default=text("'linear'"), nullable=False
    )
```

Also update the `__table_args__` to add an index for scheduler queries:

```python
class SequenceInstance(Base):
    __tablename__ = "sequence_instances"
    __table_args__ = (
        Index("ix_seqinst_lead", "lead_id"),
        Index("ix_seqinst_org_status", "org_id", "status"),
        Index("ix_seqinst_template_status", "template_id", "status"),
        Index("ix_seqinst_engine_type_status", "engine_type", "status"),  # NEW
        # Partial unique index: only one active instance per lead per template
        Index(
            "uq_seqinst_template_lead_active",
            "template_id",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )
```

- [ ] **Step 2: Create Alembic migration**

```bash
cd "/Users/animeshmahato/Wavelength v3"
alembic revision --autogenerate -m "add engine_type to sequence_instances"
```

Verify the generated migration adds the column with a default and the new index. Edit if needed to ensure:

```python
"""add engine_type to sequence_instances"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "sequence_instances",
        sa.Column("engine_type", sa.Text(), server_default=sa.text("'linear'"), nullable=False),
    )
    op.create_index(
        "ix_seqinst_engine_type_status",
        "sequence_instances",
        ["engine_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_seqinst_engine_type_status", table_name="sequence_instances")
    op.drop_column("sequence_instances", "engine_type")
```

- [ ] **Step 3: Verify migration applies cleanly**

```bash
alembic upgrade head
alembic downgrade -1
alembic upgrade head
```

- [ ] **Step 4: Commit**

```bash
git add app/models/sequence.py alembic/versions/*engine_type*
git commit -m "feat: add engine_type column to SequenceInstance for migration routing

Defaults to 'linear' for all existing instances. Scheduler will use
this to route between linear and flow engines during coexistence."
```

---

## Task 2: Scheduler Dual-Loop (Coexistence)

**Files:**
- Modify: `app/services/sequence_scheduler.py`
- Create: `tests/test_scheduler_dual_loop.py`

- [ ] **Step 1: Write tests for dual-loop scheduler**

Create `tests/test_scheduler_dual_loop.py`:

```python
"""Tests for scheduler dual-loop: linear + flow polling."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.services.sequence_scheduler import _process_batch, _process_flow_batch


@pytest.fixture
def mock_db():
    """Create a mock async DB session."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    return db


class TestLinearBatchFiltering:
    """Verify _process_batch only picks up engine_type='linear' touchpoints."""

    @pytest.mark.asyncio
    async def test_process_batch_filters_linear_only(self, mock_db):
        """_process_batch query should include engine_type='linear' filter."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await _process_batch()

        # Verify the SQL query was executed (contains engine_type filter)
        call_args = mock_db.execute.call_args
        assert call_args is not None


class TestFlowBatchPolling:
    """Verify _process_flow_batch polls FlowTouchpoint table."""

    @pytest.mark.asyncio
    async def test_process_flow_batch_polls_pending_touchpoints(self, mock_db):
        """_process_flow_batch should query FlowTouchpoint with status=pending."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        with patch("app.services.sequence_scheduler.get_db_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await _process_flow_batch()

        assert mock_db.execute.called


class TestSchedulerLoopDual:
    """Verify the scheduler loop calls both batch processors."""

    @pytest.mark.asyncio
    async def test_scheduler_calls_both_loops(self):
        """_scheduler_loop should call both _process_batch and _process_flow_batch."""
        with patch("app.services.sequence_scheduler._process_batch", new_callable=AsyncMock) as mock_linear, \
             patch("app.services.sequence_scheduler._process_flow_batch", new_callable=AsyncMock) as mock_flow, \
             patch("app.services.sequence_scheduler._retry_failed", new_callable=AsyncMock), \
             patch("app.services.sequence_scheduler.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

            # Make sleep raise to break the loop after one iteration
            mock_sleep.side_effect = [None, asyncio.CancelledError()]

            import asyncio
            from app.services.sequence_scheduler import _scheduler_loop
            try:
                await _scheduler_loop()
            except asyncio.CancelledError:
                pass

            assert mock_linear.called
            assert mock_flow.called
```

- [ ] **Step 2: Add engine_type filter to existing `_process_batch`**

In `app/services/sequence_scheduler.py`, modify the `_process_batch()` query to only select linear-engine touchpoints:

```python
# In _process_batch(), update the main query (around line 70):
# BEFORE:
        result = await db.execute(
            select(SequenceTouchpoint)
            .join(SequenceInstance, SequenceTouchpoint.instance_id == SequenceInstance.id)
            .where(
                SequenceTouchpoint.status.in_(["pending", "scheduled"]),
                SequenceTouchpoint.scheduled_at <= now,
                SequenceInstance.status == "active",
            )
            .order_by(SequenceTouchpoint.scheduled_at.asc())
            .limit(MAX_CONCURRENT * 2)
            .with_for_update(skip_locked=True)
        )

# AFTER:
        result = await db.execute(
            select(SequenceTouchpoint)
            .join(SequenceInstance, SequenceTouchpoint.instance_id == SequenceInstance.id)
            .where(
                SequenceTouchpoint.status.in_(["pending", "scheduled"]),
                SequenceTouchpoint.scheduled_at <= now,
                SequenceInstance.status == "active",
                SequenceInstance.engine_type == "linear",  # Only linear engine
            )
            .order_by(SequenceTouchpoint.scheduled_at.asc())
            .limit(MAX_CONCURRENT * 2)
            .with_for_update(skip_locked=True)
        )
```

- [ ] **Step 3: Add `_process_flow_batch` function**

Add the flow polling loop to `app/services/sequence_scheduler.py`:

```python
# Add imports at top of file:
from app.models.flow import FlowInstance, FlowTouchpoint
from app.services import flow_engine

# Add after _process_batch() function:

async def _process_flow_batch() -> None:
    """Find and process all due flow touchpoints."""
    now = datetime.now(timezone.utc)

    async with get_db_session() as db:
        # Poll FlowTouchpoint where status=pending and scheduled_at <= now
        result = await db.execute(
            select(FlowTouchpoint)
            .join(FlowInstance, FlowTouchpoint.instance_id == FlowInstance.id)
            .where(
                FlowTouchpoint.status == "pending",
                FlowTouchpoint.scheduled_at <= now,
                FlowInstance.status == "active",
            )
            .order_by(FlowTouchpoint.scheduled_at.asc())
            .limit(MAX_CONCURRENT * 2)
            .with_for_update(skip_locked=True)
        )
        touchpoints = result.scalars().all()

        if not touchpoints:
            return

        logger.info("flow_scheduler_batch", count=len(touchpoints))

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)

        async def _process_one_flow(tp_id: uuid.UUID) -> None:
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
                        await flow_engine.execute_touchpoint(tp_db, tp)
                    except Exception:
                        logger.exception(
                            "flow_touchpoint_processing_failed",
                            touchpoint_id=str(tp_id),
                        )
                        tp.status = "failed"
                        tp.error_message = "Unexpected processing error"
                        tp.retry_count += 1
                        await tp_db.commit()

        tasks = [asyncio.create_task(_process_one_flow(tp.id)) for tp in touchpoints]
        await asyncio.gather(*tasks, return_exceptions=True)
        await db.commit()


async def _process_flow_events() -> None:
    """Poll FlowEvent for wait_for_event nodes and consume matching events."""
    async with get_db_session() as db:
        from app.models.flow import FlowEvent

        # Find unconsumed events
        result = await db.execute(
            select(FlowEvent).where(FlowEvent.consumed == False)  # noqa: E712
        )
        events = result.scalars().all()

        for event in events:
            # Find waiting touchpoints that match this event
            tp_result = await db.execute(
                select(FlowTouchpoint)
                .join(FlowInstance, FlowTouchpoint.instance_id == FlowInstance.id)
                .where(
                    FlowTouchpoint.status == "waiting",
                    FlowInstance.lead_id == event.lead_id,
                    FlowInstance.status == "active",
                )
            )
            waiting_tps = tp_result.scalars().all()

            for tp in waiting_tps:
                # Check if this touchpoint's node is a wait_for_event that matches
                node_config = tp.node_snapshot or {}
                if node_config.get("node_type") != "wait_for_event":
                    continue
                config = node_config.get("config", {})
                if config.get("event_type") == event.event_type:
                    event.consumed = True
                    try:
                        await flow_engine.node_completed(
                            tp_db=db,
                            touchpoint=tp,
                            outcome="event_received",
                            outcome_data=event.payload,
                        )
                    except Exception:
                        logger.exception(
                            "flow_event_processing_failed",
                            event_id=str(event.id),
                            touchpoint_id=str(tp.id),
                        )
                    break  # One event consumed by one touchpoint

        if events:
            await db.commit()
```

- [ ] **Step 4: Update `_scheduler_loop` to call both loops**

```python
# Replace the existing _scheduler_loop:
async def _scheduler_loop():
    """Main loop — polls DB for due touchpoints (linear + flow)."""
    cycle_count = 0
    while not _shutdown:
        try:
            await _process_batch()  # Linear engine
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("sequence_scheduler_error")

        try:
            await _process_flow_batch()  # Flow engine
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("flow_scheduler_error")

        try:
            await _process_flow_events()  # Wait-for-event consumption
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("flow_event_scheduler_error")

        # Every 5th cycle, retry failed touchpoints that haven't hit max retries
        cycle_count += 1
        if cycle_count % 5 == 0:
            try:
                await _retry_failed()
            except Exception:
                logger.exception("sequence_retry_failed_error")

        await asyncio.sleep(POLL_INTERVAL)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_scheduler_dual_loop.py -v --timeout=30
```

- [ ] **Step 6: Commit**

```bash
git add app/services/sequence_scheduler.py tests/test_scheduler_dual_loop.py
git commit -m "feat: scheduler dual-loop for linear + flow engine coexistence

Scheduler now runs two parallel polling loops:
1. _process_batch() — linear engine (SequenceTouchpoint, engine_type=linear)
2. _process_flow_batch() — flow engine (FlowTouchpoint)
3. _process_flow_events() — wait-for-event node consumption

Both engines run side by side during migration."
```

---

## Task 3: Auto-Convert Migration Script

**Files:**
- Create: `app/services/flow_migrator.py`
- Create: `tests/test_flow_migrator.py`

- [ ] **Step 1: Write tests for the migration converter**

Create `tests/test_flow_migrator.py`:

```python
"""Tests for SequenceTemplate → FlowDefinition auto-conversion."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.flow_migrator import (
    convert_step_to_node,
    build_flow_graph,
    convert_skip_conditions_to_condition_node,
    map_channel_to_node_type,
    map_timing_to_delay_node,
)


class TestChannelMapping:
    """Map SequenceStep.channel to FlowNode.node_type."""

    def test_voice_call_channel(self):
        assert map_channel_to_node_type("voice_call") == "voice_call"

    def test_whatsapp_template_channel(self):
        assert map_channel_to_node_type("whatsapp_template") == "whatsapp_template"

    def test_whatsapp_session_channel(self):
        assert map_channel_to_node_type("whatsapp_session") == "whatsapp_session"

    def test_ai_channel(self):
        assert map_channel_to_node_type("ai_message") == "ai_generate_send"

    def test_unknown_channel_defaults(self):
        """Unknown channels should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown channel"):
            map_channel_to_node_type("carrier_pigeon")


class TestStepToNodeConversion:
    """Convert a SequenceStep dict to FlowNode config."""

    def test_voice_call_step(self):
        step = {
            "name": "Follow-up Call",
            "channel": "voice_call",
            "voice_bot_id": str(uuid.uuid4()),
            "content_type": "voice",
            "skip_conditions": None,
            "timing_type": "delay",
            "timing_value": {"days": 1},
        }
        node = convert_step_to_node(step, step_index=0)
        assert node["node_type"] == "voice_call"
        assert node["name"] == "Follow-up Call"
        assert node["config"]["bot_id"] == step["voice_bot_id"]

    def test_whatsapp_template_step(self):
        step = {
            "name": "Welcome Message",
            "channel": "whatsapp_template",
            "content_type": "template",
            "whatsapp_template_name": "welcome_v2",
            "whatsapp_template_params": {"1": "{{contact_name}}"},
            "skip_conditions": None,
            "timing_type": "immediate",
            "timing_value": {},
        }
        node = convert_step_to_node(step, step_index=0)
        assert node["node_type"] == "whatsapp_template"
        assert node["config"]["template_name"] == "welcome_v2"
        assert node["config"]["params"] == {"1": "{{contact_name}}"}

    def test_ai_generate_step(self):
        step = {
            "name": "AI Follow-up",
            "channel": "whatsapp_session",
            "content_type": "ai_generated",
            "ai_prompt": "Write a follow-up message for {{contact_name}}",
            "ai_model": "claude-sonnet",
            "skip_conditions": None,
            "timing_type": "delay",
            "timing_value": {"hours": 2},
        }
        node = convert_step_to_node(step, step_index=0)
        assert node["node_type"] == "ai_generate_send"
        assert node["config"]["prompt"] == step["ai_prompt"]
        assert node["config"]["model"] == "claude-sonnet"
        assert node["config"]["send_via"] == "whatsapp_session"


class TestSkipConditionConversion:
    """Convert skip_conditions to Condition nodes."""

    def test_equals_condition(self):
        skip = {"field": "interest_level", "equals": "low"}
        cond_node = convert_skip_conditions_to_condition_node(skip, step_name="Call Step")
        assert cond_node["node_type"] == "condition"
        assert cond_node["config"]["rules"][0]["field"] == "interest_level"
        assert cond_node["config"]["rules"][0]["operator"] == "equals"
        assert cond_node["config"]["rules"][0]["value"] == "low"

    def test_not_equals_condition(self):
        skip = {"field": "goal_outcome", "not_equals": "interested"}
        cond_node = convert_skip_conditions_to_condition_node(skip, step_name="Call Step")
        assert cond_node["node_type"] == "condition"
        assert cond_node["config"]["rules"][0]["operator"] == "not_equals"

    def test_none_skip_returns_none(self):
        assert convert_skip_conditions_to_condition_node(None, step_name="X") is None


class TestTimingToDelayNode:
    """Convert timing_type + timing_value to a Delay node."""

    def test_delay_days(self):
        delay = map_timing_to_delay_node("delay", {"days": 2})
        assert delay["node_type"] == "delay_wait"
        assert delay["config"]["delay_hours"] == 48

    def test_delay_hours(self):
        delay = map_timing_to_delay_node("delay", {"hours": 6})
        assert delay["config"]["delay_hours"] == 6

    def test_delay_minutes(self):
        delay = map_timing_to_delay_node("delay", {"minutes": 30})
        assert delay["config"]["delay_hours"] == 0.5

    def test_immediate_returns_none(self):
        """Immediate timing needs no delay node."""
        assert map_timing_to_delay_node("immediate", {}) is None

    def test_relative_to_event(self):
        delay = map_timing_to_delay_node(
            "relative_to_event",
            {"days": -1, "time": "09:00", "event_variable": "event_date"},
        )
        assert delay["node_type"] == "delay_wait"
        assert delay["config"]["relative_to"] == "event_date"
        assert delay["config"]["offset_days"] == -1
        assert delay["config"]["at_time"] == "09:00"


class TestBuildFlowGraph:
    """Build a complete FlowDefinition graph from a list of steps."""

    def test_simple_linear_chain(self):
        steps = [
            {
                "step_order": 1,
                "name": "Welcome",
                "channel": "whatsapp_template",
                "content_type": "template",
                "timing_type": "immediate",
                "timing_value": {},
                "skip_conditions": None,
                "whatsapp_template_name": "welcome",
                "whatsapp_template_params": {},
                "ai_prompt": None,
                "ai_model": None,
                "voice_bot_id": None,
                "expects_reply": False,
                "reply_handler": None,
            },
            {
                "step_order": 2,
                "name": "Follow-up Call",
                "channel": "voice_call",
                "content_type": "voice",
                "timing_type": "delay",
                "timing_value": {"days": 1},
                "skip_conditions": None,
                "whatsapp_template_name": None,
                "whatsapp_template_params": None,
                "ai_prompt": None,
                "ai_model": None,
                "voice_bot_id": str(uuid.uuid4()),
                "expects_reply": False,
                "reply_handler": None,
            },
        ]
        nodes, edges = build_flow_graph(steps)

        # Should have: WA Template → Delay(1d) → Voice Call → End
        # At minimum: 2 action nodes + 1 delay + 1 end = 4 nodes
        assert len(nodes) >= 3  # 2 action + 1 end minimum
        assert any(n["node_type"] == "end" for n in nodes)
        # Edges should form a chain
        assert len(edges) >= 2

    def test_steps_with_skip_condition_adds_condition_node(self):
        steps = [
            {
                "step_order": 1,
                "name": "Call",
                "channel": "voice_call",
                "content_type": "voice",
                "timing_type": "immediate",
                "timing_value": {},
                "skip_conditions": {"field": "interest_level", "equals": "low"},
                "whatsapp_template_name": None,
                "whatsapp_template_params": None,
                "ai_prompt": None,
                "ai_model": None,
                "voice_bot_id": str(uuid.uuid4()),
                "expects_reply": False,
                "reply_handler": None,
            },
        ]
        nodes, edges = build_flow_graph(steps)

        # Should have a condition node before the action
        condition_nodes = [n for n in nodes if n["node_type"] == "condition"]
        assert len(condition_nodes) == 1

    def test_empty_steps_produces_just_end(self):
        nodes, edges = build_flow_graph([])
        assert len(nodes) == 1
        assert nodes[0]["node_type"] == "end"
        assert len(edges) == 0
```

- [ ] **Step 2: Run tests (expect failures)**

```bash
pytest tests/test_flow_migrator.py -v --timeout=30
```

All tests should fail (module doesn't exist yet).

- [ ] **Step 3: Implement `flow_migrator.py`**

Create `app/services/flow_migrator.py`:

```python
"""Migrate SequenceTemplate → FlowDefinition + FlowVersion.

Converts linear sequence steps into a chain of FlowNodes with edges.
Handles channel mapping, timing-to-delay conversion, and skip_conditions-to-condition conversion.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sequence import SequenceStep, SequenceTemplate
from app.models.flow import FlowDefinition, FlowEdge, FlowNode, FlowVersion

logger = structlog.get_logger(__name__)

# ── Channel mapping ──────────────────────────────────────────────────────────

CHANNEL_MAP: dict[str, str] = {
    "voice_call": "voice_call",
    "whatsapp_template": "whatsapp_template",
    "whatsapp_session": "whatsapp_session",
    "ai_message": "ai_generate_send",
    "ai_generated": "ai_generate_send",
}


def map_channel_to_node_type(channel: str) -> str:
    """Map a SequenceStep.channel value to a FlowNode.node_type."""
    node_type = CHANNEL_MAP.get(channel)
    if node_type is None:
        raise ValueError(f"Unknown channel: {channel}")
    return node_type


# ── Step → Node conversion ───────────────────────────────────────────────────

def convert_step_to_node(step: dict[str, Any], step_index: int) -> dict[str, Any]:
    """Convert a single SequenceStep snapshot to a FlowNode dict.

    Returns a dict with: node_type, name, config, position_x, position_y.
    """
    channel = step["channel"]
    content_type = step.get("content_type", "")

    # Determine node_type based on channel + content_type
    if content_type == "ai_generated":
        node_type = "ai_generate_send"
    else:
        node_type = map_channel_to_node_type(channel)

    # Build node-type-specific config
    config: dict[str, Any] = {}

    if node_type == "voice_call":
        config["bot_id"] = step.get("voice_bot_id")
        config["quick_retry"] = {"enabled": False, "max_attempts": 1, "interval_hours": 1}
        config["send_window"] = {"enabled": False}

    elif node_type == "whatsapp_template":
        config["template_name"] = step.get("whatsapp_template_name", "")
        config["params"] = step.get("whatsapp_template_params") or {}

    elif node_type == "whatsapp_session":
        config["message_type"] = "text"
        config["text_body"] = ""
        if step.get("expects_reply"):
            config["wait_for_reply"] = True
            config["reply_timeout_hours"] = 24
        else:
            config["wait_for_reply"] = False

    elif node_type == "ai_generate_send":
        config["prompt"] = step.get("ai_prompt", "")
        config["model"] = step.get("ai_model", "claude-sonnet")
        config["send_via"] = channel if channel != "ai_message" else "whatsapp_session"
        config["max_tokens"] = 500

    # Canvas position: vertical chain layout
    position_x = 400.0
    position_y = 100.0 + (step_index * 200.0)

    return {
        "node_type": node_type,
        "name": step.get("name", f"Step {step_index + 1}"),
        "config": config,
        "position_x": position_x,
        "position_y": position_y,
    }


# ── Skip conditions → Condition node ─────────────────────────────────────────

def convert_skip_conditions_to_condition_node(
    skip_conditions: dict[str, Any] | None,
    step_name: str,
) -> dict[str, Any] | None:
    """Convert a step's skip_conditions to a Condition FlowNode.

    The linear engine skips the step when condition matches.
    In the flow graph, a Condition node branches:
      - "skip" edge → next step (bypass this one)
      - "default" edge → this step (execute it)
    """
    if not skip_conditions:
        return None

    field = skip_conditions.get("field", "")
    rules = []

    if "equals" in skip_conditions:
        rules.append({
            "field": field,
            "operator": "equals",
            "value": skip_conditions["equals"],
        })
    elif "not_equals" in skip_conditions:
        rules.append({
            "field": field,
            "operator": "not_equals",
            "value": skip_conditions["not_equals"],
        })

    if not rules:
        return None

    return {
        "node_type": "condition",
        "name": f"Check before {step_name}",
        "config": {
            "logic": "and",
            "rules": rules,
        },
        "position_x": 400.0,
        "position_y": 0.0,  # Will be repositioned in build_flow_graph
    }


# ── Timing → Delay node ──────────────────────────────────────────────────────

def map_timing_to_delay_node(
    timing_type: str, timing_value: dict[str, Any]
) -> dict[str, Any] | None:
    """Convert timing_type + timing_value to a Delay/Wait FlowNode.

    Returns None for 'immediate' timing (no delay needed).
    """
    if timing_type == "immediate":
        return None

    config: dict[str, Any] = {}

    if timing_type == "delay":
        total_hours = (
            timing_value.get("days", 0) * 24
            + timing_value.get("hours", 0)
            + timing_value.get("minutes", 0) / 60
        )
        config["delay_hours"] = total_hours
        if "time" in timing_value:
            config["at_time"] = timing_value["time"]

    elif timing_type == "relative_to_event":
        config["relative_to"] = timing_value.get("event_variable", "event_date")
        config["offset_days"] = timing_value.get("days", 0)
        if "time" in timing_value:
            config["at_time"] = timing_value["time"]
        config["delay_hours"] = abs(timing_value.get("days", 0)) * 24

    elif timing_type == "relative_to_previous":
        total_hours = (
            timing_value.get("days", 0) * 24
            + timing_value.get("hours", 0)
            + timing_value.get("minutes", 0) / 60
        )
        config["delay_hours"] = total_hours
        if "time" in timing_value:
            config["at_time"] = timing_value["time"]

    else:
        logger.warning("unknown_timing_type", timing_type=timing_type)
        config["delay_hours"] = 0

    return {
        "node_type": "delay_wait",
        "name": f"Wait",
        "config": config,
        "position_x": 400.0,
        "position_y": 0.0,
    }


# ── Build full flow graph ────────────────────────────────────────────────────

def build_flow_graph(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert an ordered list of step snapshots into nodes + edges.

    Returns (nodes, edges) where each node has a temporary 'temp_id' for edge linking,
    and each edge has 'source_temp_id' and 'target_temp_id'.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if not steps:
        nodes.append({
            "temp_id": str(uuid.uuid4()),
            "node_type": "end",
            "name": "End",
            "config": {"end_reason": "completed"},
            "position_x": 400.0,
            "position_y": 100.0,
        })
        return nodes, edges

    y_cursor = 100.0
    prev_temp_id: str | None = None

    for i, step in enumerate(steps):
        # 1) Delay node (if timing is not immediate and not first step)
        delay_node = None
        if i > 0:  # First step timing is handled by enrollment
            delay_node = map_timing_to_delay_node(
                step.get("timing_type", "immediate"),
                step.get("timing_value", {}),
            )

        if delay_node:
            delay_temp_id = str(uuid.uuid4())
            delay_node["temp_id"] = delay_temp_id
            delay_node["position_y"] = y_cursor
            nodes.append(delay_node)

            if prev_temp_id:
                edges.append({
                    "source_temp_id": prev_temp_id,
                    "target_temp_id": delay_temp_id,
                    "condition_label": "default",
                    "sort_order": 0,
                })
            prev_temp_id = delay_temp_id
            y_cursor += 150.0

        # 2) Condition node (if skip_conditions exist)
        skip_cond = step.get("skip_conditions")
        cond_node = convert_skip_conditions_to_condition_node(skip_cond, step.get("name", ""))

        if cond_node:
            cond_temp_id = str(uuid.uuid4())
            cond_node["temp_id"] = cond_temp_id
            cond_node["position_y"] = y_cursor
            nodes.append(cond_node)

            if prev_temp_id:
                edges.append({
                    "source_temp_id": prev_temp_id,
                    "target_temp_id": cond_temp_id,
                    "condition_label": "default",
                    "sort_order": 0,
                })

            # "skip" edge will connect to the next step's first node (resolved later)
            # "default" edge connects to this step's action node
            cond_prev_id = cond_temp_id
            y_cursor += 150.0
        else:
            cond_prev_id = None

        # 3) Action node
        action = convert_step_to_node(step, step_index=i)
        action_temp_id = str(uuid.uuid4())
        action["temp_id"] = action_temp_id
        action["position_y"] = y_cursor
        nodes.append(action)

        if cond_prev_id:
            # Condition → action (default path = condition NOT met, so execute)
            edges.append({
                "source_temp_id": cond_prev_id,
                "target_temp_id": action_temp_id,
                "condition_label": "default",
                "sort_order": 1,
            })
        elif prev_temp_id:
            edges.append({
                "source_temp_id": prev_temp_id,
                "target_temp_id": action_temp_id,
                "condition_label": "default",
                "sort_order": 0,
            })

        prev_temp_id = action_temp_id
        y_cursor += 150.0

    # 4) End node
    end_temp_id = str(uuid.uuid4())
    nodes.append({
        "temp_id": end_temp_id,
        "node_type": "end",
        "name": "End",
        "config": {"end_reason": "completed"},
        "position_x": 400.0,
        "position_y": y_cursor,
    })

    if prev_temp_id:
        edges.append({
            "source_temp_id": prev_temp_id,
            "target_temp_id": end_temp_id,
            "condition_label": "default",
            "sort_order": 0,
        })

    # 5) Resolve skip-condition "skip" edges
    # For each condition node, the "skip" edge bypasses its action and goes to the
    # next node in the chain (or End if it's the last step).
    cond_indices = [i for i, n in enumerate(nodes) if n["node_type"] == "condition"]
    for ci in cond_indices:
        cond = nodes[ci]
        # Find the action node right after this condition
        action_idx = ci + 1
        if action_idx >= len(nodes):
            continue
        # Find the node after the action (next delay, condition, or end)
        skip_target_idx = action_idx + 1
        if skip_target_idx >= len(nodes):
            skip_target_idx = len(nodes) - 1  # End node

        edges.append({
            "source_temp_id": cond["temp_id"],
            "target_temp_id": nodes[skip_target_idx]["temp_id"],
            "condition_label": "skip",
            "sort_order": 0,
        })

    return nodes, edges


# ── DB-level migration ────────────────────────────────────────────────────────

async def migrate_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Convert a SequenceTemplate into a FlowDefinition + FlowVersion (draft).

    Returns a summary dict with flow_id, version_id, node_count, edge_count.
    If dry_run=True, returns the summary without persisting.
    """
    # Load template
    tmpl_result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id,
            SequenceTemplate.org_id == org_id,
        )
    )
    template = tmpl_result.scalar_one_or_none()
    if template is None:
        raise ValueError(f"Template {template_id} not found for org {org_id}")

    # Load steps
    steps_result = await db.execute(
        select(SequenceStep)
        .where(
            SequenceStep.template_id == template_id,
            SequenceStep.is_active == True,  # noqa: E712
        )
        .order_by(SequenceStep.step_order)
    )
    steps = steps_result.scalars().all()

    # Snapshot steps
    step_dicts = []
    for s in steps:
        step_dicts.append({
            "step_order": s.step_order,
            "name": s.name,
            "channel": s.channel,
            "content_type": s.content_type,
            "timing_type": s.timing_type,
            "timing_value": s.timing_value,
            "skip_conditions": s.skip_conditions,
            "whatsapp_template_name": s.whatsapp_template_name,
            "whatsapp_template_params": s.whatsapp_template_params,
            "ai_prompt": s.ai_prompt,
            "ai_model": s.ai_model,
            "voice_bot_id": str(s.voice_bot_id) if s.voice_bot_id else None,
            "expects_reply": s.expects_reply,
            "reply_handler": s.reply_handler,
        })

    # Build graph
    nodes_data, edges_data = build_flow_graph(step_dicts)

    summary = {
        "template_id": str(template_id),
        "template_name": template.name,
        "node_count": len(nodes_data),
        "edge_count": len(edges_data),
        "nodes": [{"name": n["name"], "type": n["node_type"]} for n in nodes_data],
    }

    if dry_run:
        summary["dry_run"] = True
        return summary

    # Create FlowDefinition
    flow = FlowDefinition(
        org_id=org_id,
        name=f"{template.name} (migrated)",
        description=f"Auto-converted from linear sequence '{template.name}'",
        trigger_type=template.trigger_type,
        trigger_config=template.trigger_conditions,
        is_active=False,  # Draft — must be reviewed before activating
    )
    db.add(flow)
    await db.flush()

    # Create FlowVersion (draft)
    version = FlowVersion(
        flow_id=flow.id,
        org_id=org_id,
        version_number=1,
        status="draft",
    )
    db.add(version)
    await db.flush()

    # Create nodes — map temp_id → real UUID
    temp_to_real: dict[str, uuid.UUID] = {}
    for node_data in nodes_data:
        node = FlowNode(
            version_id=version.id,
            org_id=org_id,
            node_type=node_data["node_type"],
            name=node_data["name"],
            position_x=node_data["position_x"],
            position_y=node_data["position_y"],
            config=node_data["config"],
        )
        db.add(node)
        await db.flush()
        temp_to_real[node_data["temp_id"]] = node.id

    # Create edges
    for edge_data in edges_data:
        source_id = temp_to_real.get(edge_data["source_temp_id"])
        target_id = temp_to_real.get(edge_data["target_temp_id"])
        if source_id and target_id:
            edge = FlowEdge(
                version_id=version.id,
                org_id=org_id,
                source_node_id=source_id,
                target_node_id=target_id,
                condition_label=edge_data["condition_label"],
                sort_order=edge_data["sort_order"],
            )
            db.add(edge)

    await db.flush()

    summary["flow_id"] = str(flow.id)
    summary["version_id"] = str(version.id)
    summary["status"] = "draft"

    logger.info(
        "template_migrated_to_flow",
        template_id=str(template_id),
        flow_id=str(flow.id),
        node_count=len(nodes_data),
        edge_count=len(edges_data),
    )

    return summary


async def migrate_all_templates(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Migrate all active SequenceTemplates for an org to FlowDefinitions.

    Returns a list of summary dicts.
    """
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,  # noqa: E712
        )
    )
    templates = result.scalars().all()

    summaries = []
    for template in templates:
        try:
            summary = await migrate_template(
                db, template.id, org_id, dry_run=dry_run,
            )
            summaries.append(summary)
        except Exception as e:
            logger.exception(
                "template_migration_failed",
                template_id=str(template.id),
                error=str(e),
            )
            summaries.append({
                "template_id": str(template.id),
                "template_name": template.name,
                "error": str(e),
            })

    return summaries
```

- [ ] **Step 4: Run tests (expect pass)**

```bash
pytest tests/test_flow_migrator.py -v --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add app/services/flow_migrator.py tests/test_flow_migrator.py
git commit -m "feat: auto-convert migration script (SequenceTemplate → FlowDefinition)

Pure-function converters for channel mapping, timing-to-delay,
skip_conditions-to-condition, and full graph builder. DB-level
migrate_template() creates FlowDefinition + FlowVersion as draft
for review before publishing."
```

---

## Task 4: Migration Admin API

**Files:**
- Create: `app/api/flow_migration.py`
- Modify: `app/main.py`
- Create: `tests/test_migration_api.py`

- [ ] **Step 1: Write tests for migration endpoints**

Create `tests/test_migration_api.py`:

```python
"""Tests for migration admin endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest


class TestMigrationPreview:
    """Test dry-run migration preview endpoint."""

    @pytest.mark.asyncio
    async def test_preview_returns_node_count(self):
        """Preview should return node_count and edge_count without persisting."""
        from app.services.flow_migrator import build_flow_graph

        steps = [
            {
                "step_order": 1,
                "name": "Call",
                "channel": "voice_call",
                "content_type": "voice",
                "timing_type": "immediate",
                "timing_value": {},
                "skip_conditions": None,
                "whatsapp_template_name": None,
                "whatsapp_template_params": None,
                "ai_prompt": None,
                "ai_model": None,
                "voice_bot_id": str(uuid.uuid4()),
                "expects_reply": False,
                "reply_handler": None,
            },
        ]
        nodes, edges = build_flow_graph(steps)
        # Should produce: VoiceCall → End (2 nodes, 1 edge)
        assert len(nodes) == 2
        assert len(edges) == 1


class TestMigrationStatus:
    """Test migration status tracking."""

    def test_status_response_shape(self):
        """Status should report total, migrated, remaining, active_linear counts."""
        status = {
            "total_templates": 5,
            "migrated": 3,
            "remaining": 2,
            "active_linear_instances": 10,
        }
        assert status["remaining"] == status["total_templates"] - status["migrated"]
```

- [ ] **Step 2: Create migration API router**

Create `app/api/flow_migration.py`:

```python
"""Admin endpoints for linear → flow migration."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org, get_current_user
from app.database import get_db
from app.models.sequence import SequenceInstance, SequenceTemplate
from app.models.flow import FlowDefinition
from app.services.flow_migrator import migrate_template, migrate_all_templates

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/migration", tags=["migration"])


class MigrationStatusResponse(BaseModel):
    total_templates: int
    migrated: int
    remaining: int
    active_linear_instances: int
    templates: list[dict[str, Any]]


class MigrationPreviewResponse(BaseModel):
    template_id: str
    template_name: str
    node_count: int
    edge_count: int
    nodes: list[dict[str, str]]
    dry_run: bool = True


class MigrationResultResponse(BaseModel):
    template_id: str
    template_name: str
    flow_id: str | None = None
    version_id: str | None = None
    status: str | None = None
    node_count: int
    edge_count: int
    error: str | None = None


class BulkMigrationResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[dict[str, Any]]


@router.get("/status", response_model=MigrationStatusResponse)
async def migration_status(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> MigrationStatusResponse:
    """Get migration status for the current org."""
    # Count total active templates
    total_result = await db.execute(
        select(func.count()).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,  # noqa: E712
        )
    )
    total_templates = total_result.scalar_one()

    # Count templates that have a corresponding migrated flow
    # (FlowDefinition with name ending in " (migrated)")
    migrated_result = await db.execute(
        select(func.count()).where(
            FlowDefinition.org_id == org_id,
            FlowDefinition.name.like("% (migrated)"),
        )
    )
    migrated = migrated_result.scalar_one()

    # Count active linear instances
    active_result = await db.execute(
        select(func.count()).where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.status == "active",
            SequenceInstance.engine_type == "linear",
        )
    )
    active_linear = active_result.scalar_one()

    # List templates with migration status
    templates_result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,  # noqa: E712
        )
    )
    templates = templates_result.scalars().all()

    template_list = []
    for t in templates:
        # Check if already migrated
        flow_result = await db.execute(
            select(FlowDefinition.id).where(
                FlowDefinition.org_id == org_id,
                FlowDefinition.name == f"{t.name} (migrated)",
            )
        )
        flow_id = flow_result.scalar_one_or_none()
        template_list.append({
            "id": str(t.id),
            "name": t.name,
            "migrated": flow_id is not None,
            "flow_id": str(flow_id) if flow_id else None,
        })

    return MigrationStatusResponse(
        total_templates=total_templates,
        migrated=migrated,
        remaining=total_templates - migrated,
        active_linear_instances=active_linear,
        templates=template_list,
    )


@router.post("/preview/{template_id}", response_model=MigrationPreviewResponse)
async def preview_migration(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> MigrationPreviewResponse:
    """Preview what the migrated flow would look like (dry run)."""
    try:
        result = await migrate_template(db, template_id, org_id, dry_run=True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return MigrationPreviewResponse(**result)


@router.post("/convert/{template_id}", response_model=MigrationResultResponse)
async def convert_template(
    template_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> MigrationResultResponse:
    """Convert a single template to a flow (creates as draft)."""
    try:
        result = await migrate_template(db, template_id, org_id, dry_run=False)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await db.commit()
    return MigrationResultResponse(**result)


@router.post("/convert-all", response_model=BulkMigrationResponse)
async def convert_all_templates(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> BulkMigrationResponse:
    """Convert all active templates to flows (creates as drafts)."""
    results = await migrate_all_templates(db, org_id, dry_run=False)
    await db.commit()

    succeeded = sum(1 for r in results if "error" not in r)
    failed = sum(1 for r in results if "error" in r)

    return BulkMigrationResponse(
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )
```

- [ ] **Step 3: Register migration router in `app/main.py`**

```python
# In app/main.py, add with other router imports:
from app.api.flow_migration import router as migration_router

# In the router registration section:
app.include_router(migration_router)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_migration_api.py -v --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add app/api/flow_migration.py app/main.py tests/test_migration_api.py
git commit -m "feat: migration admin API (preview, convert, bulk convert, status)

Admin endpoints for managing the linear-to-flow migration:
- GET /api/migration/status — migration progress per org
- POST /api/migration/preview/{id} — dry-run conversion
- POST /api/migration/convert/{id} — convert single template
- POST /api/migration/convert-all — bulk convert all templates"
```

---

## Task 5: Export/Import Flow JSON

**Files:**
- Modify: `app/api/flows.py`
- Create: `tests/test_flow_export_import.py`

- [ ] **Step 1: Write tests for export/import**

Create `tests/test_flow_export_import.py`:

```python
"""Tests for flow export/import JSON format."""

import uuid
from datetime import datetime

import pytest

from app.services.flow_export import (
    export_flow_version,
    strip_org_ids,
    validate_import_payload,
    prepare_import_nodes,
)


class TestStripOrgIds:
    """Exported JSON must not contain org-specific UUIDs."""

    def test_strips_org_id(self):
        data = {
            "org_id": str(uuid.uuid4()),
            "name": "My Flow",
            "nodes": [
                {"id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "name": "Call"},
            ],
            "edges": [
                {"id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "source_node_id": "a"},
            ],
        }
        cleaned = strip_org_ids(data)
        assert "org_id" not in cleaned
        assert "org_id" not in cleaned["nodes"][0]
        assert "org_id" not in cleaned["edges"][0]

    def test_preserves_non_org_fields(self):
        data = {"name": "Flow", "description": "Test", "org_id": "x"}
        cleaned = strip_org_ids(data)
        assert cleaned["name"] == "Flow"
        assert cleaned["description"] == "Test"

    def test_strips_db_ids(self):
        """Export should replace UUIDs with portable temp IDs."""
        node_id = str(uuid.uuid4())
        data = {
            "nodes": [{"id": node_id, "name": "Call"}],
            "edges": [{"id": str(uuid.uuid4()), "source_node_id": node_id, "target_node_id": node_id}],
        }
        cleaned = strip_org_ids(data)
        # IDs should be replaced or removed
        assert cleaned["nodes"][0].get("id") != node_id


class TestValidateImportPayload:
    """Import validation checks."""

    def test_valid_payload(self):
        payload = {
            "name": "Imported Flow",
            "nodes": [
                {"temp_id": "n1", "node_type": "voice_call", "name": "Call", "config": {}, "position_x": 0, "position_y": 0},
                {"temp_id": "n2", "node_type": "end", "name": "End", "config": {}, "position_x": 0, "position_y": 200},
            ],
            "edges": [
                {"source_temp_id": "n1", "target_temp_id": "n2", "condition_label": "default"},
            ],
        }
        errors = validate_import_payload(payload)
        assert len(errors) == 0

    def test_missing_name(self):
        payload = {"nodes": [], "edges": []}
        errors = validate_import_payload(payload)
        assert any("name" in e.lower() for e in errors)

    def test_missing_end_node(self):
        payload = {
            "name": "Bad Flow",
            "nodes": [
                {"temp_id": "n1", "node_type": "voice_call", "name": "Call", "config": {}},
            ],
            "edges": [],
        }
        errors = validate_import_payload(payload)
        assert any("end" in e.lower() for e in errors)

    def test_dangling_edge_reference(self):
        payload = {
            "name": "Bad Flow",
            "nodes": [
                {"temp_id": "n1", "node_type": "end", "name": "End", "config": {}},
            ],
            "edges": [
                {"source_temp_id": "n1", "target_temp_id": "n_missing", "condition_label": "default"},
            ],
        }
        errors = validate_import_payload(payload)
        assert any("dangling" in e.lower() or "missing" in e.lower() for e in errors)


class TestPrepareImportNodes:
    """Map temp IDs to new UUIDs for import."""

    def test_maps_temp_ids_to_uuids(self):
        nodes = [
            {"temp_id": "n1", "node_type": "voice_call", "name": "Call", "config": {}},
            {"temp_id": "n2", "node_type": "end", "name": "End", "config": {}},
        ]
        edges = [{"source_temp_id": "n1", "target_temp_id": "n2", "condition_label": "default"}]

        mapped_nodes, mapped_edges, id_map = prepare_import_nodes(nodes, edges)

        assert "n1" in id_map
        assert "n2" in id_map
        assert id_map["n1"] != id_map["n2"]
        assert mapped_edges[0]["source_node_id"] == id_map["n1"]
        assert mapped_edges[0]["target_node_id"] == id_map["n2"]
```

- [ ] **Step 2: Create `app/services/flow_export.py`**

```python
"""Flow export/import — portable JSON format."""

import uuid
from copy import deepcopy
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import FlowDefinition, FlowEdge, FlowNode, FlowVersion

logger = structlog.get_logger(__name__)

# Fields to strip on export (org-specific)
_STRIP_FIELDS = {"org_id", "created_at", "updated_at"}


def strip_org_ids(data: dict[str, Any]) -> dict[str, Any]:
    """Remove org-specific IDs and replace DB UUIDs with portable temp IDs.

    Makes the exported JSON portable between organizations.
    """
    result = deepcopy(data)

    # Strip top-level org fields
    for field in _STRIP_FIELDS:
        result.pop(field, None)

    # Build ID → temp_id map for nodes
    id_map: dict[str, str] = {}
    for node in result.get("nodes", []):
        old_id = node.pop("id", None)
        for field in _STRIP_FIELDS:
            node.pop(field, None)
        if old_id:
            temp_id = f"n_{uuid.uuid4().hex[:8]}"
            node["temp_id"] = temp_id
            id_map[str(old_id)] = temp_id

    # Remap edge references
    for edge in result.get("edges", []):
        old_id = edge.pop("id", None)
        for field in _STRIP_FIELDS:
            edge.pop(field, None)
        edge.pop("version_id", None)

        source = str(edge.pop("source_node_id", ""))
        target = str(edge.pop("target_node_id", ""))
        edge["source_temp_id"] = id_map.get(source, source)
        edge["target_temp_id"] = id_map.get(target, target)

    return result


def validate_import_payload(payload: dict[str, Any]) -> list[str]:
    """Validate an import payload. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not payload.get("name"):
        errors.append("Missing required field: name")

    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])

    if not any(n.get("node_type") == "end" for n in nodes):
        errors.append("Flow must have at least one End node")

    # Check for dangling edge references
    temp_ids = {n.get("temp_id") for n in nodes if n.get("temp_id")}
    for edge in edges:
        if edge.get("source_temp_id") not in temp_ids:
            errors.append(f"Dangling edge: missing source node {edge.get('source_temp_id')}")
        if edge.get("target_temp_id") not in temp_ids:
            errors.append(f"Dangling edge: missing target node {edge.get('target_temp_id')}")

    return errors


def prepare_import_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, uuid.UUID]]:
    """Map temp_ids to new UUIDs for import.

    Returns (mapped_nodes, mapped_edges, id_map).
    """
    id_map: dict[str, uuid.UUID] = {}

    # Assign new UUIDs to each temp_id
    for node in nodes:
        temp_id = node.get("temp_id", str(uuid.uuid4()))
        new_id = uuid.uuid4()
        id_map[temp_id] = new_id

    # Remap edges
    mapped_edges = []
    for edge in edges:
        source_temp = edge.get("source_temp_id", "")
        target_temp = edge.get("target_temp_id", "")
        mapped_edges.append({
            "source_node_id": id_map.get(source_temp),
            "target_node_id": id_map.get(target_temp),
            "condition_label": edge.get("condition_label", "default"),
            "sort_order": edge.get("sort_order", 0),
        })

    return nodes, mapped_edges, id_map


async def export_flow_version(
    db: AsyncSession,
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Export a FlowVersion as portable JSON."""
    # Load flow definition
    flow_result = await db.execute(
        select(FlowDefinition).where(
            FlowDefinition.id == flow_id,
            FlowDefinition.org_id == org_id,
        )
    )
    flow = flow_result.scalar_one_or_none()
    if not flow:
        raise ValueError(f"Flow {flow_id} not found")

    # Load version
    ver_result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.id == version_id,
            FlowVersion.flow_id == flow_id,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise ValueError(f"Version {version_id} not found")

    # Load nodes
    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = nodes_result.scalars().all()

    # Load edges
    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = edges_result.scalars().all()

    # Build export dict
    export_data = {
        "name": flow.name,
        "description": flow.description,
        "trigger_type": flow.trigger_type,
        "trigger_config": flow.trigger_config,
        "org_id": str(org_id),
        "nodes": [
            {
                "id": str(n.id),
                "org_id": str(n.org_id),
                "node_type": n.node_type,
                "name": n.name,
                "position_x": n.position_x,
                "position_y": n.position_y,
                "config": n.config,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": str(e.id),
                "org_id": str(e.org_id),
                "source_node_id": str(e.source_node_id),
                "target_node_id": str(e.target_node_id),
                "condition_label": e.condition_label,
                "sort_order": e.sort_order,
            }
            for e in edges
        ],
    }

    # Strip org-specific data
    return strip_org_ids(export_data)


async def import_flow(
    db: AsyncSession,
    org_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    target_flow_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Import a flow from JSON. Creates new flow or new version of existing.

    Args:
        target_flow_id: If provided, creates a new version of this flow.
                        If None, creates a new FlowDefinition.
    """
    errors = validate_import_payload(payload)
    if errors:
        raise ValueError(f"Invalid import payload: {'; '.join(errors)}")

    nodes_data = payload.get("nodes", [])
    edges_data = payload.get("edges", [])
    _, mapped_edges, id_map = prepare_import_nodes(nodes_data, edges_data)

    if target_flow_id:
        # New version of existing flow
        flow_result = await db.execute(
            select(FlowDefinition).where(
                FlowDefinition.id == target_flow_id,
                FlowDefinition.org_id == org_id,
            )
        )
        flow = flow_result.scalar_one_or_none()
        if not flow:
            raise ValueError(f"Flow {target_flow_id} not found")

        # Get next version number
        ver_result = await db.execute(
            select(FlowVersion.version_number)
            .where(FlowVersion.flow_id == target_flow_id)
            .order_by(FlowVersion.version_number.desc())
            .limit(1)
        )
        last_ver = ver_result.scalar_one_or_none() or 0
        next_ver = last_ver + 1
    else:
        # New flow
        flow = FlowDefinition(
            org_id=org_id,
            name=payload.get("name", "Imported Flow"),
            description=payload.get("description", ""),
            trigger_type=payload.get("trigger_type", "manual"),
            trigger_config=payload.get("trigger_config", {}),
            is_active=False,
        )
        db.add(flow)
        await db.flush()
        next_ver = 1

    # Create version
    version = FlowVersion(
        flow_id=flow.id,
        org_id=org_id,
        version_number=next_ver,
        status="draft",
    )
    db.add(version)
    await db.flush()

    # Create nodes
    for node_data in nodes_data:
        temp_id = node_data.get("temp_id")
        real_id = id_map.get(temp_id)
        node = FlowNode(
            id=real_id,
            version_id=version.id,
            org_id=org_id,
            node_type=node_data["node_type"],
            name=node_data.get("name", ""),
            position_x=node_data.get("position_x", 0.0),
            position_y=node_data.get("position_y", 0.0),
            config=node_data.get("config", {}),
        )
        db.add(node)

    # Create edges
    for edge_data in mapped_edges:
        if edge_data["source_node_id"] and edge_data["target_node_id"]:
            edge = FlowEdge(
                version_id=version.id,
                org_id=org_id,
                source_node_id=edge_data["source_node_id"],
                target_node_id=edge_data["target_node_id"],
                condition_label=edge_data.get("condition_label", "default"),
                sort_order=edge_data.get("sort_order", 0),
            )
            db.add(edge)

    await db.flush()

    return {
        "flow_id": str(flow.id),
        "version_id": str(version.id),
        "version_number": next_ver,
        "node_count": len(nodes_data),
        "edge_count": len(mapped_edges),
        "status": "draft",
    }
```

- [ ] **Step 3: Add export/import API endpoints**

In `app/api/flows.py`, add:

```python
from app.services.flow_export import export_flow_version, import_flow

@router.get("/{flow_id}/versions/{version_id}/export")
async def export_flow(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Export a flow version as portable JSON."""
    try:
        data = await export_flow_version(db, flow_id, version_id, org_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return data


class FlowImportRequest(BaseModel):
    name: str
    description: str = ""
    trigger_type: str = "manual"
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


@router.post("/import", status_code=201)
async def import_flow_endpoint(
    body: FlowImportRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Import a flow from JSON (creates new flow as draft)."""
    try:
        result = await import_flow(db, org_id, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return result


@router.post("/{flow_id}/import-version", status_code=201)
async def import_flow_version_endpoint(
    flow_id: uuid.UUID,
    body: FlowImportRequest,
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Import JSON as a new version of an existing flow."""
    try:
        result = await import_flow(db, org_id, body.model_dump(), target_flow_id=flow_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await db.commit()
    return result
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_flow_export_import.py -v --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add app/services/flow_export.py app/api/flows.py tests/test_flow_export_import.py
git commit -m "feat: flow export/import as portable JSON

Export strips org-specific IDs and replaces DB UUIDs with temp IDs.
Import validates payload, maps temp IDs to new UUIDs, creates
FlowDefinition + FlowVersion as draft. Supports importing as new
flow or new version of existing flow."
```

---

## Task 6: Deprecation Warnings & Linear Sunset

**Files:**
- Modify: `app/api/sequences.py`
- Modify: `app/api/flow_migration.py`

- [ ] **Step 1: Add deprecation headers to sequence API endpoints**

In `app/api/sequences.py`, add a dependency that injects deprecation warnings:

```python
from fastapi import Response

DEPRECATION_MESSAGE = (
    "This endpoint is deprecated. Use /api/flows/* instead. "
    "Migrate existing sequences with POST /api/migration/convert-all"
)


def add_deprecation_warning(response: Response) -> None:
    """Inject Deprecation and Sunset headers into response."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-06-01"  # Grace period end date
    response.headers["Link"] = '</api/flows>; rel="successor-version"'


# Apply to all template CRUD endpoints:
@router.post("/templates", response_model=TemplateListItem, status_code=201,
             deprecated=True)
async def create_template(
    body: TemplateCreate,
    response: Response,
    user: User = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Create a new sequence template. DEPRECATED: Use POST /api/flows instead."""
    add_deprecation_warning(response)
    # ... existing implementation unchanged ...
```

Apply the same pattern to: `list_templates`, `get_template`, `update_template`, `delete_template`, `create_step`, `update_step`, `delete_step`.

Instance management endpoints (`list_instances`, `pause`, `resume`, `cancel`) remain non-deprecated until all linear instances complete.

- [ ] **Step 2: Add linear completion tracker to migration API**

In `app/api/flow_migration.py`, add:

```python
@router.get("/linear-instances")
async def list_active_linear_instances(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """List all active linear instances (for tracking completion before sunset)."""
    base = select(SequenceInstance).where(
        SequenceInstance.org_id == org_id,
        SequenceInstance.status == "active",
        SequenceInstance.engine_type == "linear",
    )

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base.order_by(SequenceInstance.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(rows_q)
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": str(i.id),
                "template_id": str(i.template_id),
                "lead_id": str(i.lead_id),
                "status": i.status,
                "started_at": i.started_at.isoformat() if i.started_at else None,
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/cancel-all-linear")
async def cancel_all_linear_instances(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Cancel all remaining active linear instances (use with caution)."""
    from sqlalchemy import update

    result = await db.execute(
        update(SequenceInstance)
        .where(
            SequenceInstance.org_id == org_id,
            SequenceInstance.status == "active",
            SequenceInstance.engine_type == "linear",
        )
        .values(status="cancelled")
        .returning(SequenceInstance.id)
    )
    cancelled_ids = result.scalars().all()
    await db.commit()

    logger.info(
        "linear_instances_bulk_cancelled",
        org_id=str(org_id),
        count=len(cancelled_ids),
    )

    return {"cancelled": len(cancelled_ids)}
```

- [ ] **Step 3: Commit**

```bash
git add app/api/sequences.py app/api/flow_migration.py
git commit -m "feat: deprecation warnings on sequence API + linear instance tracker

Template CRUD endpoints marked deprecated with Sunset header.
Migration API gains linear-instances listing and bulk cancel for
completing the Phase 3 sunset."
```

---

## Task 7: Rollback Plan

**No code changes** — this task documents the rollback procedure.

- [ ] **Step 1: Document rollback procedure**

The rollback strategy depends on which phase has failed:

**Phase 1 (Coexistence) rollback:**
- The `engine_type` column is additive — all existing rows default to `linear`.
- To rollback: revert scheduler to single-loop by removing `_process_flow_batch()` call.
- Flow tables can remain (they're unused by linear engine).
- No data loss risk.

```python
# Revert _scheduler_loop to single-loop:
async def _scheduler_loop():
    cycle_count = 0
    while not _shutdown:
        try:
            await _process_batch()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("sequence_scheduler_error")
        cycle_count += 1
        if cycle_count % 5 == 0:
            try:
                await _retry_failed()
            except Exception:
                logger.exception("sequence_retry_failed_error")
        await asyncio.sleep(POLL_INTERVAL)
```

**Phase 2 (Auto-Convert) rollback:**
- Migrated flows are created as drafts (not active). No impact on running sequences.
- To rollback: delete migrated FlowDefinitions where name ends in " (migrated)".

```python
# Cleanup script — run in a management command or ad-hoc:
async def rollback_migrations(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Delete all auto-migrated flow definitions (drafts only)."""
    from sqlalchemy import delete
    from app.models.flow import FlowDefinition

    # Only delete flows that were auto-migrated and never published
    result = await db.execute(
        select(FlowDefinition).where(
            FlowDefinition.org_id == org_id,
            FlowDefinition.name.like("% (migrated)"),
            FlowDefinition.is_active == False,  # noqa: E712
        )
    )
    flows = result.scalars().all()

    count = 0
    for flow in flows:
        await db.delete(flow)  # CASCADE deletes versions, nodes, edges
        count += 1

    await db.commit()
    return count
```

**Phase 3 (Deprecate) rollback:**
- If issues arise after deprecation, re-enable the old UI by removing the feature flag.
- Sequence API endpoints remain functional (just marked deprecated).
- Linear engine code is never deleted until confirmed safe.

```python
# Feature flag in app/config.py:
HIDE_LINEAR_UI = os.getenv("HIDE_LINEAR_UI", "false").lower() == "true"

# To rollback: set HIDE_LINEAR_UI=false in environment and redeploy.
```

**Critical rule:** Never drop the `sequence_templates`, `sequence_steps`, `sequence_instances`, or `sequence_touchpoints` tables until all of the following are true:
1. Zero active linear instances (`SELECT count(*) FROM sequence_instances WHERE status = 'active' AND engine_type = 'linear'` returns 0)
2. All templates have been migrated to flows
3. At least 30 days have passed since the last linear instance completed
4. Database backup has been taken

- [ ] **Step 2: Add rollback endpoint to migration API**

In `app/api/flow_migration.py`, add:

```python
@router.post("/rollback-migrations")
async def rollback_migrations(
    org_id: uuid.UUID = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
):
    """Delete all auto-migrated flow drafts (rollback Phase 2)."""
    result = await db.execute(
        select(FlowDefinition).where(
            FlowDefinition.org_id == org_id,
            FlowDefinition.name.like("% (migrated)"),
            FlowDefinition.is_active == False,  # noqa: E712
        )
    )
    flows = result.scalars().all()

    deleted = 0
    for flow in flows:
        await db.delete(flow)
        deleted += 1

    await db.commit()
    logger.info("migration_rollback", org_id=str(org_id), deleted=deleted)
    return {"deleted": deleted}
```

- [ ] **Step 3: Commit**

```bash
git add app/api/flow_migration.py
git commit -m "feat: migration rollback endpoint + documented rollback procedure

POST /api/migration/rollback-migrations deletes auto-migrated draft
flows. Rollback plan covers all three migration phases with specific
revert procedures and safety checks."
```

---

## Summary

| Task | What it does | Files |
|------|-------------|-------|
| 1 | Add `engine_type` column to SequenceInstance | `sequence.py`, migration |
| 2 | Scheduler dual-loop (linear + flow) | `sequence_scheduler.py`, tests |
| 3 | Auto-convert migration script | `flow_migrator.py`, tests |
| 4 | Migration admin API | `flow_migration.py`, `main.py`, tests |
| 5 | Flow export/import JSON | `flow_export.py`, `flows.py`, tests |
| 6 | Deprecation warnings + linear sunset | `sequences.py`, `flow_migration.py` |
| 7 | Rollback plan + rollback endpoint | `flow_migration.py` |

**Total:** 7 tasks, ~30 steps, 7 commits.

After completing this plan, the migration path from linear sequences to the flow builder is fully operational. Proceed to user communication and staged rollout.
