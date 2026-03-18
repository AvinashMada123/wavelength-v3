# Sequence Analytics Dashboard — Design Spec

## Overview

Add a dedicated analytics dashboard at `/sequences/analytics` for the engagement sequence builder. Provides aggregated metrics across templates, channels, and leads with an overview + drill-down interaction pattern. All data derived from existing tables with in-memory caching (5-min TTL).

## Goals

- Answer "which sequences are working?" (template performance)
- Answer "which channels perform best?" (channel comparison)
- Answer "how engaged is this lead?" (engagement scoring)
- Surface operational issues (failures, skips, retry rates)
- Support filtering by date range, template, channel, bot, and lead status

## Non-Goals

- Real-time streaming/websocket updates (on-demand with caching is sufficient)
- New database tables or migrations (all data from existing tables)
- Historical trend storage (computed from raw touchpoint data)
- Email/export of analytics reports
- AI cost tracking (requires schema changes to store token/latency metadata — deferred to v2)

---

## API Endpoints

All endpoints under `/api/sequences/analytics/`, authenticated via `get_current_user`.

### Common Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `start_date` | ISO date string | Filter start (inclusive) |
| `end_date` | ISO date string | Filter end (inclusive) |
| `template_id` | UUID (optional) | Filter to specific template |
| `channel` | string (optional) | Filter to specific channel (`whatsapp_template`, `whatsapp_session`, `sms`, `voice_call`) |
| `bot_id` | UUID (optional) | Filter to specific bot |

Note: `lead_status` (engagement tier) filtering is only available on the `/leads` endpoint, since it requires computing engagement scores first.

### Endpoints

#### `GET /overview`
Top-level KPI cards.

**Definitions:**
- `reply_rate`: `total_replied / total_sent` counting only touchpoints where the linked step has `expects_reply=true`. Touchpoints with null `step_id` (deleted steps) are excluded from this calculation.
- `completion_rate`: `completed_instances / (completed + cancelled + active instances)` — paused instances excluded from denominator
- `avg_time_to_reply_hours`: Approximate — computed as `touchpoint.updated_at - touchpoint.sent_at` for touchpoints in "replied" status. Uses `updated_at` as proxy for reply time since no dedicated `replied_at` column exists. Accurate when the only update after "sent" is the reply status change (typical case).
- `trend`: compares current period to equivalent previous period. Returns `null` for any trend value when comparison period has < 5 touchpoints.
- `pending` touchpoints are excluded from sent/failed/replied counts but their existence is noted in funnel step counts (they indicate in-progress, not drop-off).

Response:
```json
{
  "total_sent": 1247,
  "total_failed": 49,
  "total_replied": 427,
  "reply_rate": 0.342,
  "completion_rate": 0.678,
  "avg_time_to_reply_hours": 4.2,
  "trend": {
    "sent_change": 0.12,
    "reply_rate_change": 0.031,
    "completion_rate_change": -0.024,
    "avg_reply_time_change": -1.1
  }
}
```
Trend values are fractional changes (0.12 = +12%). Returns `null` for individual trend fields when comparison period has insufficient data.

#### `GET /funnel`
Step-by-step funnel for a specific template.

**`template_id` is required.** Funnels are per-template structures — aggregating across templates with different step counts/semantics is not meaningful.

Response:
```json
{
  "template_name": "Masterclass Engagement",
  "total_entered": 489,
  "steps": [
    {
      "step_order": 1,
      "name": "Gift Message",
      "sent": 489,
      "skipped": 0,
      "failed": 3,
      "replied": 0,
      "drop_off_rate": 0.0
    },
    {
      "step_order": 2,
      "name": "Hope Question",
      "sent": 381,
      "skipped": 42,
      "failed": 5,
      "replied": 160,
      "drop_off_rate": 0.22
    }
  ]
}
```
`drop_off_rate`: fraction of leads that did not reach this step compared to step 1.

#### `GET /channels`
Per-channel performance breakdown.

Response:
```json
{
  "channels": [
    {
      "channel": "whatsapp_template",
      "sent": 892,
      "failed": 22,
      "replied": 312,
      "reply_rate": 0.358,
      "percentage_of_total": 0.71
    }
  ]
}
```
Note: No "delivered" status — the system tracks `sent` and `failed`. Delivery receipts are not currently captured.

#### `GET /templates`
Template performance table (sortable).

Response:
```json
{
  "templates": [
    {
      "template_id": "uuid",
      "name": "Masterclass Engagement",
      "total_sent": 489,
      "completion_rate": 0.71,
      "reply_rate": 0.42,
      "avg_steps_completed": 3.2,
      "total_steps": 4,
      "active_instances": 12,
      "funnel_summary": [489, 381, 284, 247]
    }
  ]
}
```
`funnel_summary`: array of `sent` counts per step in step_order. Typically descending as leads drop off, but not enforced — values reflect actual counts (e.g., mid-sequence additions could cause non-monotonic counts).

#### `GET /leads`
Lead engagement table with scores.

Query params: `page` (default 1), `page_size` (default 20), `sort_by` (default "score"), `sort_order` (default "desc"), `tier` (optional — filter by engagement tier: hot/warm/cold/inactive).

Response:
```json
{
  "leads": [
    {
      "lead_id": "uuid",
      "lead_name": "Ramesh K.",
      "lead_phone": "+91...",
      "score": 92,
      "tier": "hot",
      "active_sequences": 1,
      "total_replies": 5,
      "last_interaction_at": "2026-03-17T09:00:00Z"
    }
  ],
  "tier_summary": {
    "hot": 23,
    "warm": 87,
    "cold": 145,
    "inactive": 62
  },
  "total": 317,
  "page": 1,
  "page_size": 20
}
```

#### `GET /leads/{lead_id}`
Single lead drill-down.

Response:
```json
{
  "lead_id": "uuid",
  "lead_name": "Ramesh K.",
  "score": 92,
  "tier": "hot",
  "score_breakdown": {
    "activity": { "score": 38, "max": 40 },
    "recency": { "score": 28, "max": 30 },
    "outcome": { "score": 26, "max": 30 }
  },
  "active_sequences": 1,
  "total_replies": 5,
  "avg_reply_time_hours": 2.1,
  "timeline": [
    {
      "timestamp": "2026-03-15T10:30:00Z",
      "template_name": "Masterclass Engagement",
      "step_name": "Gift Message",
      "channel": "whatsapp_template",
      "status": "sent",
      "content_preview": "Hi Ramesh! Here's your personalized...",
      "reply_text": null
    },
    {
      "timestamp": "2026-03-15T19:30:00Z",
      "template_name": "Masterclass Engagement",
      "step_name": "Hope Question",
      "channel": "whatsapp_template",
      "status": "replied",
      "content_preview": "What would you do if AI could...",
      "reply_text": "I want to automate my factory reports"
    }
  ]
}
```

#### `GET /failures`
Failure reasons breakdown.

Response:
```json
{
  "total_failed": 49,
  "reasons": [
    { "reason": "Session window expired", "count": 18 },
    { "reason": "Provider timeout", "count": 7 },
    { "reason": "Invalid phone", "count": 3 }
  ],
  "retry_stats": {
    "total_retried": 32,
    "retry_success_rate": 0.56
  }
}
```
Failure reasons extracted from `error_message` field, grouped by common prefixes.

---

## Engagement Scoring Model

Composite score (0-100) computed from 3 weighted dimensions.

### Dimensions

| Dimension | Weight | Calculation |
|-----------|--------|-------------|
| Activity (40%) | 0-40 pts | Points per touchpoint: replied=3, sent=1, failed=-1. Raw score capped at 20, scaled to 40pts via `min(raw, 20) / 20 * 40`. This ensures a lead with many replies (raw=15) scores higher than a merely-contacted lead (raw=10). |
| Recency (30%) | 0-30 pts | `e^(-0.05 × days_since_last_interaction) × 30`. Yesterday ≈ 29pts, 14 days ≈ 15pts, 30 days ≈ 7pts. |
| Outcome (30%) | 0-30 pts | `(completed_sequences / total_sequences) × 15 + (total_replies / total_sent) × 15`. Only counts touchpoints where `expects_reply=true` for reply ratio. |

### Tiers

| Tier | Score Range | Meaning |
|------|-------------|---------|
| Hot | 70-100 | Actively replying, completing sequences |
| Warm | 40-69 | Some engagement, partial completion |
| Cold | 10-39 | Low interaction |
| Inactive | 0-9 | No meaningful engagement |

### Edge Cases

- **New lead with no touchpoints:** Score = 0, tier = Inactive
- **Lead with only failed touchpoints:** Activity goes negative, clamped to 0. Score comes only from recency (if recent).
- **Lead with 0 sent touchpoints:** Outcome reply ratio = 0 (avoid division by zero)

Score is computed on demand from touchpoint data and cached for 5 minutes per lead.

---

## Caching Strategy

- **Storage:** In-memory Python `dict` in the service module
- **Key:** `(org_id, endpoint_name, hash(sorted_filter_params))`
- **TTL:** 5 minutes
- **Eviction:** Lazy — checked on access, stale entries discarded
- **Size limit:** None needed at current scale (coaching businesses, dozens of orgs)
- **Invalidation:** Expose `_invalidate_cache(org_id)` function. Called on touchpoint status changes from write operations (retry, cancel, pause/resume). Users may see up to 5 min stale data for background touchpoint processing — this is acceptable.
- **No Redis dependency**

---

## Backend Architecture

### New Files

| File | Purpose |
|------|---------|
| `app/api/sequence_analytics.py` | FastAPI router with 7 endpoints |
| `app/services/sequence_analytics.py` | SQL aggregation queries, engagement scoring, caching |

### Modified Files

| File | Change |
|------|--------|
| `app/main.py` | Register `sequence_analytics` router |

### Query Strategy

All queries use existing tables:
- `sequence_touchpoints` — primary data source (status, timing, replies, errors)
- `sequence_instances` — instance lifecycle (active, completed, cancelled)
- `sequence_templates` — template metadata
- `sequence_steps` — step metadata for funnel labeling

Queries use `JOIN` + `GROUP BY` with filter `WHERE` clauses. No new tables or migrations.

### Route Prefix

Analytics router mounted at `/api/sequences/analytics` as a separate router from the existing `/api/sequences` router. No route conflicts since existing template routes use `/templates/{template_id}` pattern.

---

## Frontend Architecture

### New Files

| File | Purpose |
|------|---------|
| `frontend/src/app/(app)/sequences/analytics/page.tsx` | Main analytics dashboard page |
| `frontend/src/components/sequences/AnalyticsDrillDown.tsx` | Template and lead drill-down views |

### Modified Files

| File | Change |
|------|--------|
| `frontend/src/lib/sequences-api.ts` | Add analytics API functions |
| Sequences nav (in existing pages) | Add "Analytics" link |

### Page Layout (Overview)

1. **Filter Bar** — Date range picker + template/channel/bot dropdowns + preset buttons (7d/30d/90d/all)
2. **KPI Cards Row** — Total Sent, Reply Rate, Completion Rate, Avg Time to Reply — each with trend indicator (↑/↓ vs previous period, or "—" if insufficient data)
3. **Charts Row** — Delivery trend (Recharts stacked bar) + Channel split (horizontal bars)
4. **Bottom Row** — Template performance table (sortable, with mini funnel sparklines) + Lead engagement (tier cards + top leads list)

### Drill-Down Component

- Replaces main content (not modal) with back button to overview
- **Template mode:** Template KPIs → Step funnel bars → Failure/skip reason tables
- **Lead mode:** Score breakdown bars (activity/recency/outcome) → Quick stats → Engagement timeline

### Data Fetching

- `useEffect` + `useState` (consistent with existing pages, no SWR/React Query)
- `Promise.allSettled` for parallel endpoint calls — graceful degradation if one endpoint fails (show error per section, not blank page)
- Refetch on filter change with loading states
- URL query params for shareable filter state

### Charting

- Recharts (already installed) for all visualizations
- Bar charts for delivery trend and funnel
- Horizontal bars for channel breakdown
- No new dependencies

---

## UI Navigation

Analytics accessible at `/sequences/analytics`, linked from the sequences section navigation alongside Templates and Monitor.

---

## Data Flow Summary

```
User opens /sequences/analytics
  → Frontend calls GET /api/sequences/analytics/overview (+ /channels, /templates, /leads)
    via Promise.allSettled — each section renders independently
  → Backend checks in-memory cache
    → Hit: return cached data
    → Miss: SQL aggregation on touchpoints/instances/templates → cache → return
  → Frontend renders KPI cards, charts, tables

User clicks template row
  → Frontend calls GET /api/sequences/analytics/funnel?template_id=X (+ /failures)
  → Drill-down component renders funnel + failure breakdown

User clicks lead
  → Frontend calls GET /api/sequences/analytics/leads/{id}
  → Drill-down component renders score breakdown + timeline

User changes filters
  → All visible endpoints re-fetched with new params
  → Cache may hit if same filters were queried within 5 min
```

---

## Future (v2)

- **AI cost tracking:** Add `ai_input_tokens`, `ai_output_tokens`, `ai_latency_ms`, `ai_cost_usd` columns to `sequence_touchpoints` via migration. Build `/ai-costs` endpoint.
- **Delivery receipts:** Integrate WhatsApp delivery webhooks to track actual delivery vs. sent.
- **Reply timestamp:** Add dedicated `replied_at` column to `sequence_touchpoints` for precise reply time tracking (currently using `updated_at` as proxy).
- **Export:** CSV/PDF export of analytics data.
