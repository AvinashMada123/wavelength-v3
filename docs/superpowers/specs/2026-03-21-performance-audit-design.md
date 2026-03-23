# Performance Audit & Load Testing — Design Spec

**Date:** 2026-03-21
**Approach:** Fix First, Test Later (Approach A)

## Overview

Audit and fix performance bottlenecks in the Wavelength v3 backend, then set up Locust load testing to validate fixes and establish baselines. Target: handle 50-200 concurrent calls, 10K-100K leads without degradation.

---

## Phase 1: Critical Database Fixes

### 1.1 Add Missing Indexes

```sql
-- Call logs: contact_phone lookups (call_memory, lead matching)
CREATE INDEX idx_call_logs_contact_phone ON call_logs (contact_phone);

-- Call logs: bot_id + date range (analytics, list filtering)
CREATE INDEX idx_call_logs_bot_date ON call_logs (bot_id, created_at DESC);

-- Call analytics: org + date range (analytics endpoints)
CREATE INDEX idx_call_analytics_org_date ON call_analytics (org_id, created_at DESC);

-- Sequence touchpoints: lead scoring queries
CREATE INDEX idx_seqtp_lead_status_sched ON sequence_touchpoints (lead_id, status, scheduled_at);
```

**Files:** New Alembic migration (or direct SQL if no Alembic)

### 1.2 Fix Unbounded Query Limits

| Endpoint | Current Default | Fix |
|----------|----------------|-----|
| `GET /api/calls` | `limit=10000` | `limit=50, max=500` |
| `GET /api/calls/export` | `limit=10000` | `limit=1000, max=5000` |

**File:** `app/api/calls.py`

### 1.3 Move Sequence Leads Scoring to Database

Current: Fetches ALL lead_ids, scores in Python, sorts in Python, then paginates.
Fix: Use SQL window functions for scoring + pagination.

```sql
-- Score = activity (replies) + recency + outcome bonuses
-- Sort + paginate in DB, not Python
SELECT lead_id, score, tier, ...
FROM (scoring CTE)
ORDER BY score DESC
LIMIT :page_size OFFSET :offset
```

**File:** `app/api/sequence_analytics.py`

### 1.4 Batch Sequence Analytics Queries

Current: 8 sequential DB queries for `/analytics/overview`.
Fix: Combine into 2-3 queries using CTEs or UNION ALL.

**File:** `app/api/sequence_analytics.py`

---

## Phase 2: Connection Pool & Memory Fixes

### 2.1 Increase Database Pool Size

Current: `pool_size=10, max_overflow=5` (15 total).
Fix: `pool_size=20, max_overflow=10` (30 total).
Add pool pre-ping and recycle settings.

**File:** `app/database.py`

### 2.2 Cap Call Memory Prompt Size

Current: Builds unbounded string from past call transcripts.
Fix: Truncate to max 2000 chars total, summarize if needed.

**File:** `app/services/call_memory.py`

### 2.3 Add Query Timeouts

Set statement_timeout per query type:
- API endpoints: 5s
- Background tasks: 30s
- Analytics: 10s

**File:** `app/database.py` (engine config)

---

## Phase 3: Locust Load Testing Setup

### 3.1 Test Scenarios

| Scenario | What it tests | Target |
|----------|--------------|--------|
| API Burst | 100 concurrent users hitting /api/calls, /api/leads, /api/bots | p95 < 500ms |
| Call Queue Flood | Enqueue 200 calls in 30s, measure processing throughput | All processed < 5min |
| Analytics Under Load | 20 users hitting analytics endpoints while calls run | p95 < 2s |
| Sequence Scheduler Saturation | 1000 pending touchpoints, measure processing rate | > 50/min throughput |
| WebSocket Lifecycle | Simulate 50 concurrent WS connections with mock audio | No connection drops |

### 3.2 File Structure

```
tests/load/
  locustfile.py          # Main entry — all user classes
  users/
    api_user.py          # API endpoint load tests
    call_queue_user.py   # Call queue flood test
    analytics_user.py    # Analytics endpoint tests
    websocket_user.py    # WebSocket lifecycle test
  config.py              # Base URL, auth tokens, test data
  README.md              # How to run
```

### 3.3 Baseline Metrics to Capture

- p50, p95, p99 response times per endpoint
- Requests/sec throughput
- Error rate under load
- DB connection pool utilization
- Memory usage over time

---

## Out of Scope (for now)

- Redis caching (needed at 200+ concurrent, not immediate)
- Horizontal scaling / multi-worker (single container is fine for medium scale)
- CDN / frontend performance
- Service decomposition

## Success Criteria

1. All missing indexes added
2. No endpoint defaults to >500 rows
3. Sequence analytics leads endpoint uses DB-side scoring
4. DB pool handles 30 concurrent connections
5. Locust test suite covers 5 scenarios above
6. Baseline metrics documented for current production scale
