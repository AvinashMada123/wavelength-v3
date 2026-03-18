# Sequence Analytics Dashboard — Design Spec

## Overview

Add a dedicated analytics dashboard at `/sequences/analytics` for the engagement sequence builder. Provides aggregated metrics across templates, channels, and leads with an overview + drill-down interaction pattern. All data derived from existing tables with in-memory caching (5-min TTL).

## Goals

- Answer "which sequences are working?" (template performance)
- Answer "which channels perform best?" (channel comparison)
- Answer "how engaged is this lead?" (engagement scoring)
- Surface operational issues (failures, skips, AI costs)
- Support filtering by date range, template, channel, bot, and lead status

## Non-Goals

- Real-time streaming/websocket updates (on-demand with caching is sufficient)
- New database tables or migrations (all data from existing tables)
- Historical trend storage (computed from raw touchpoint data)
- Email/export of analytics reports

---

## API Endpoints

All endpoints under `/api/sequences/analytics/`, authenticated via `get_current_user`.

### Common Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `start_date` | ISO date string | Filter start (inclusive) |
| `end_date` | ISO date string | Filter end (inclusive) |
| `template_id` | UUID (optional) | Filter to specific template |
| `channel` | string (optional) | Filter to specific channel |
| `bot_id` | UUID (optional) | Filter to specific bot |
| `lead_status` | string (optional) | Filter by engagement tier (hot/warm/cold/inactive) |

### Endpoints

#### `GET /overview`
Top-level KPI cards.

Response:
```json
{
  "total_sent": 1247,
  "total_delivered": 1198,
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
Trend compares current period to the equivalent previous period (e.g., last 30d vs prior 30d).

#### `GET /funnel`
Step-by-step funnel for a template (or all templates aggregated).

Requires `template_id` param (optional — aggregates across all if omitted).

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

#### `GET /channels`
Per-channel performance breakdown.

Response:
```json
{
  "channels": [
    {
      "channel": "whatsapp_template",
      "sent": 892,
      "delivered": 870,
      "failed": 22,
      "replied": 312,
      "reply_rate": 0.358,
      "percentage_of_total": 0.71
    }
  ]
}
```

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
      "funnel_summary": [489, 381, 284, 347]
    }
  ]
}
```

#### `GET /leads`
Lead engagement table with scores.

Query params: `page` (default 1), `page_size` (default 20), `sort_by` (default "score"), `sort_order` (default "desc").

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
      "status": "sent",
      "content_preview": null,
      "reply_text": null
    },
    {
      "timestamp": "2026-03-15T19:30:00Z",
      "template_name": "Masterclass Engagement",
      "step_name": "Hope Question",
      "status": "replied",
      "content_preview": null,
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

#### `GET /ai-costs`
AI generation stats.

Response:
```json
{
  "total_cost_usd": 42.30,
  "total_generations": 892,
  "avg_latency_ms": 1240,
  "total_input_tokens": 245000,
  "total_output_tokens": 89000,
  "per_template": [
    {
      "template_name": "Masterclass Engagement",
      "cost_usd": 12.40,
      "generations": 312,
      "avg_latency_ms": 1180
    }
  ]
}
```

---

## Engagement Scoring Model

Composite score (0-100) computed from 3 weighted dimensions.

### Dimensions

| Dimension | Weight | Calculation |
|-----------|--------|-------------|
| Activity (40%) | 0-40 pts | Points per touchpoint: replied=3, sent=1, failed=-1. Raw score capped at 10, scaled to 40pts. |
| Recency (30%) | 0-30 pts | `e^(-0.05 × days_since_last_interaction) × 30`. Yesterday ≈ 29pts, 30 days ago ≈ 7pts. |
| Outcome (30%) | 0-30 pts | `(completed_sequences / total_sequences) × 15 + (total_replies / total_sent) × 15` |

### Tiers

| Tier | Score Range | Meaning |
|------|-------------|---------|
| Hot | 70-100 | Actively replying, completing sequences |
| Warm | 40-69 | Some engagement, partial completion |
| Cold | 10-39 | Low interaction |
| Inactive | 0-9 | No meaningful engagement |

Score is computed on demand from touchpoint data and cached for 5 minutes per lead.

---

## Caching Strategy

- **Storage:** In-memory Python `dict` in the service module
- **Key:** `(org_id, endpoint_name, hash(sorted_filter_params))`
- **TTL:** 5 minutes
- **Eviction:** Lazy — checked on access, stale entries returned never
- **Size limit:** None needed at current scale (coaching businesses, dozens of orgs)
- **No Redis dependency**

---

## Backend Architecture

### New Files

| File | Purpose |
|------|---------|
| `app/api/sequence_analytics.py` | FastAPI router with 8 endpoints |
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

1. **Filter Bar** — Date range picker + template/channel/bot/status dropdowns + preset buttons (7d/30d/90d/all)
2. **KPI Cards Row** — Total Sent, Reply Rate, Completion Rate, Avg Time to Reply — each with trend indicator (↑/↓ vs previous period)
3. **Charts Row** — Delivery trend (Recharts stacked bar) + Channel split (horizontal bars)
4. **Bottom Row** — Template performance table (sortable, with mini funnel sparklines) + Lead engagement (tier cards + top leads list)

### Drill-Down Component

- Replaces main content (not modal) with back button to overview
- **Template mode:** Template KPIs → Step funnel bars → Failure/skip reason tables
- **Lead mode:** Score breakdown bars (activity/recency/outcome) → Quick stats → Engagement timeline

### Data Fetching

- `useEffect` + `useState` (consistent with existing pages, no SWR/React Query)
- `Promise.all` for parallel endpoint calls on page load
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
  → Backend checks in-memory cache
    → Hit: return cached data
    → Miss: SQL aggregation on touchpoints/instances/templates → cache → return
  → Frontend renders KPI cards, charts, tables

User clicks template row
  → Frontend calls GET /api/sequences/analytics/funnel?template_id=X (+ /failures, /ai-costs)
  → Drill-down component renders funnel + failure breakdown

User clicks lead
  → Frontend calls GET /api/sequences/analytics/leads/{id}
  → Drill-down component renders score breakdown + timeline
```
