"""Tests for DND gate, dedup fix, and rate limiting in schedule_auto_retry."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Mock heavy imports before importing the module under test
# ---------------------------------------------------------------------------

# structlog
sys.modules.setdefault(
    "structlog", SimpleNamespace(get_logger=lambda *a, **kw: MagicMock())
)

# SQLAlchemy stubs — enough for the select/update/func references to resolve
_sa_mock = MagicMock()
for mod in [
    "sqlalchemy", "sqlalchemy.ext", "sqlalchemy.ext.asyncio",
    "sqlalchemy.dialects", "sqlalchemy.dialects.postgresql",
]:
    sys.modules.setdefault(mod, _sa_mock)


class _ComparableColumn(MagicMock):
    """MagicMock subclass that supports comparison operators (>=, !=, ==)
    needed by SQLAlchemy-style where() clauses built against mocked models."""

    def __ge__(self, other):
        return MagicMock()

    def __le__(self, other):
        return MagicMock()

    def __gt__(self, other):
        return MagicMock()

    def __lt__(self, other):
        return MagicMock()

    def __ne__(self, other):
        return MagicMock()

    def __eq__(self, other):
        return MagicMock()

    def __hash__(self):
        return id(self)


class _ModelMock(MagicMock):
    """Model mock whose column attributes are _ComparableColumn instances."""
    _columns_cache: dict = {}

    def __getattr__(self, name):
        # Return comparable columns for typical model attributes
        if name.startswith("_") or name in ("assert_called", "assert_called_with"):
            return super().__getattr__(name)
        key = (id(self), name)
        if key not in _ModelMock._columns_cache:
            _ModelMock._columns_cache[key] = _ComparableColumn()
        return _ModelMock._columns_cache[key]


# App model stubs — use _ModelMock for CallLog and QueuedCall so their
# column attributes support comparison operators in where() clauses.
_call_log_mock = SimpleNamespace(CallLog=_ModelMock())
_call_queue_mock = SimpleNamespace(QueuedCall=_ModelMock())

for mod in [
    "app.models.campaign",
    "app.models.lead", "app.models.organization", "app.models.phone_number",
    "app.models.bot_config", "app.models.schemas",
    "app.bot_config.loader", "app.services.call_memory",
    "app.services.lead_sync", "app.config", "app.database",
    "app.plivo.client", "app.twilio.client", "app.services.circuit_breaker",
    "app.services.billing", "app.utils",
]:
    sys.modules.setdefault(mod, MagicMock())

sys.modules["app.models.call_log"] = _call_log_mock
sys.modules["app.models.call_queue"] = _call_queue_mock

# Now import the target function
from app.services.queue_processor import schedule_auto_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_call_log(
    *,
    metadata: dict | None = None,
    contact_phone: str = "+919876543210",
    bot_id: str | None = None,
    status: str = "no_answer",
):
    """Return a lightweight CallLog-like object."""
    cl = SimpleNamespace(
        id=uuid4(),
        contact_phone=contact_phone,
        bot_id=bot_id or uuid4(),
        context_data={"bot_id": str(bot_id or uuid4())},
        metadata_=metadata or {},
        status=status,
    )
    return cl


def _make_bot_config(*, callback_enabled=True, callback_retry_delay_hours=2.0,
                     callback_max_retries=3, callback_schedule=None):
    return SimpleNamespace(
        callback_enabled=callback_enabled,
        callback_retry_delay_hours=callback_retry_delay_hours,
        callback_max_retries=callback_max_retries,
        callback_schedule=callback_schedule,
        org_id=uuid4(),
    )


class _FakeScalarResult:
    """Mimics SQLAlchemy result with .scalar_one_or_none() / .scalar()."""

    def __init__(self, value=None):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value


class _FakeSession:
    """Async context-manager that records execute() calls and returns scripted results."""

    def __init__(self, results: list):
        self._results = list(results)
        self._idx = 0
        self.committed = False

    async def execute(self, stmt, *args, **kwargs):
        if self._idx < len(self._results):
            r = self._results[self._idx]
            self._idx += 1
            return r
        return _FakeScalarResult(None)

    async def commit(self):
        self.committed = True

    def add(self, obj):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# DND gate tests
# ---------------------------------------------------------------------------

class TestDNDGate:
    """schedule_auto_retry must skip retry when DND signals are present."""

    def _run(self, call_log, bot_config=None):
        """Run schedule_auto_retry synchronously, returning whether it attempted to queue."""
        bot_config = bot_config or _make_bot_config()
        loader = AsyncMock()
        loader.get = AsyncMock(return_value=bot_config)

        # DB results sequence:
        #   1) select CallLog -> call_log
        #   2) (after DND check) select QueuedCall campaign check -> None
        #   3) bot_config_loader.get() is separate
        #   4) select QueuedCall original -> None
        #   5) dedup check -> None
        #   6) rate limit check -> None
        #   7) commit (add new QueuedCall)
        session = _FakeSession([
            _FakeScalarResult(call_log),         # 1 - load call_log
            _FakeScalarResult(None),              # 2 - campaign check
            _FakeScalarResult(None),              # 3 - original QC
            _FakeScalarResult(None),              # 4 - dedup
            _FakeScalarResult(None),              # 5 - rate limit
        ])

        with patch("app.services.queue_processor.get_db_session", return_value=session):
            asyncio.run(schedule_auto_retry(call_log.id, loader))

        return session

    def test_skip_when_llm_reason_not_interested(self):
        cl = _make_call_log(metadata={"llm_end_reason": "not interested"})
        session = self._run(cl)
        # Should have only executed the first query (load call_log) then returned
        assert session._idx == 1

    def test_skip_when_llm_reason_dont_call(self):
        cl = _make_call_log(metadata={"llm_end_reason": "Customer said don't call me again"})
        session = self._run(cl)
        assert session._idx == 1

    def test_skip_when_llm_reason_hindi_nahi_chahiye(self):
        cl = _make_call_log(metadata={"llm_end_reason": "nahi chahiye bhai"})
        session = self._run(cl)
        assert session._idx == 1

    def test_skip_when_llm_reason_stop_calling(self):
        cl = _make_call_log(metadata={"llm_end_reason": "please stop calling me"})
        session = self._run(cl)
        assert session._idx == 1

    def test_skip_when_dnd_detected_flag(self):
        cl = _make_call_log(metadata={"dnd_detected": True, "dnd_reason": "strong: stop calling"})
        session = self._run(cl)
        assert session._idx == 1

    def test_proceeds_when_reason_is_customer_busy(self):
        cl = _make_call_log(metadata={"llm_end_reason": "customer_busy"})
        session = self._run(cl)
        # Should have progressed past the DND check (idx > 1)
        assert session._idx > 1

    def test_proceeds_when_metadata_empty(self):
        cl = _make_call_log(metadata={})
        session = self._run(cl)
        assert session._idx > 1

    def test_proceeds_when_metadata_none(self):
        cl = _make_call_log(metadata=None)
        # metadata_ will be None; code does `call_log.metadata_ or {}`
        cl.metadata_ = None
        session = self._run(cl)
        assert session._idx > 1


# ---------------------------------------------------------------------------
# Dedup and rate-limit tests
# ---------------------------------------------------------------------------

class TestDedupAndRateLimit:
    """Dedup uses status.in_(["queued", "processing"]) and rate-limit checks recent completed calls."""

    def _run_with_results(self, db_results, bot_config=None):
        bot_config = bot_config or _make_bot_config()
        loader = AsyncMock()
        loader.get = AsyncMock(return_value=bot_config)
        call_log = _make_call_log(metadata={})

        db_results_full = [_FakeScalarResult(call_log)] + db_results
        session = _FakeSession(db_results_full)

        with patch("app.services.queue_processor.get_db_session", return_value=session):
            asyncio.run(schedule_auto_retry(call_log.id, loader))

        return session

    def test_dedup_catches_queued_call_from_any_source(self):
        """Dedup query uses status.in_(["queued","processing"]), not source=="auto_retry"."""
        results = [
            _FakeScalarResult(None),              # campaign check -> no campaign
            # bot_config loaded via loader.get()
            _FakeScalarResult(None),              # original QC
            _FakeScalarResult(uuid4()),           # dedup check -> FOUND existing queued call
        ]
        session = self._run_with_results(results)
        # Should stop at dedup (4 queries: call_log + campaign + original_qc + dedup)
        assert session._idx == 4

    def test_rate_limit_blocks_recent_completed_call(self):
        """Rate limit blocks retry when a completed call exists within delay window.

        The rate-limit query builds: CallLog.created_at >= min_gap.
        Since CallLog is a MagicMock (no __ge__ support), we must patch
        CallLog.created_at to a comparable stub on the already-imported reference.
        """
        import app.services.queue_processor as qp

        bot_config = _make_bot_config()
        loader = AsyncMock()
        loader.get = AsyncMock(return_value=bot_config)
        call_log = _make_call_log(metadata={})

        rate_limit_hit = _FakeScalarResult(uuid4())
        db_results = [
            _FakeScalarResult(call_log),   # call_log
            _FakeScalarResult(None),       # campaign check
            _FakeScalarResult(None),       # original QC
            _FakeScalarResult(None),       # dedup
            rate_limit_hit,                # rate limit -> HIT
        ]
        session = _FakeSession(db_results)

        # Stub CallLog.created_at with an object that supports >= comparison
        class _Comparable:
            def __ge__(self, other): return MagicMock()
            def __le__(self, other): return MagicMock()
            def __gt__(self, other): return MagicMock()
            def __lt__(self, other): return MagicMock()

        mock_logger = MagicMock()
        orig_created_at = qp.CallLog.created_at
        qp.CallLog.created_at = _Comparable()
        try:
            with patch("app.services.queue_processor.get_db_session", return_value=session), \
                 patch("app.services.queue_processor.logger", mock_logger):
                asyncio.run(schedule_auto_retry(call_log.id, loader))
        finally:
            qp.CallLog.created_at = orig_created_at

        # Should have executed all 5 queries (including rate limit)
        assert session._idx == 5
        # Logger should have recorded the rate limit skip
        mock_logger.info.assert_any_call(
            "auto_retry_rate_limit_skip",
            call_log_id=str(call_log.id),
            phone=call_log.contact_phone,
            min_gap_hours=bot_config.callback_retry_delay_hours,
        )
