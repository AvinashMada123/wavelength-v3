# Lead Engagement Tracking System — Design Spec

## Goal

Store personalized engagement data (Gemini extraction) and message analytics (WATI/GHL message IDs, open/click status) in Wavelength's own database instead of GHL custom fields. GHL only gets tags and 3 essential custom fields for workflow routing.

## Architecture

### Database: `lead_engagements` table

```sql
CREATE TABLE lead_engagements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES organizations(id),
  call_log_id UUID NOT NULL REFERENCES call_logs(id) UNIQUE,
  contact_phone TEXT NOT NULL,
  contact_email TEXT,
  extraction_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  touchpoints JSONB NOT NULL DEFAULT '{}'::jsonb,
  report_link TEXT,
  ghl_contact_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_lead_engagements_org ON lead_engagements(org_id);
CREATE INDEX idx_lead_engagements_phone ON lead_engagements(contact_phone);
CREATE INDEX idx_lead_engagements_created ON lead_engagements(created_at);
```

### extraction_data JSONB shape

```json
{
  "profession_spoken": "backend developer",
  "pain_or_goal": "wants to use AI to automate test cases",
  "specific_task": "test cases",
  "energy_level": "high",
  "confirmed_saturday": "yes",
  "personalized_hook": "When Avinash sir builds a full app...",
  "gift_plan": "1. Auto-generate test cases...\n2. ...\n3. ...\nAnd that's just the summary."
}
```

### touchpoints JSONB shape

```json
{
  "t1_wa": {
    "sent_at": "2026-04-01T10:30:00Z",
    "message_id": "wati-msg-123",
    "template": "sneha_post_call_links",
    "status": "sent"
  },
  "t1_email": {
    "sent_at": "2026-04-01T10:30:05Z",
    "message_id": "ghl-msg-456",
    "conversation_id": "ghl-conv-789",
    "subject": "Great talking to you, Animesh...",
    "status": "sent"
  },
  "t2_wa": { ... },
  "t2_email": { ... }
}
```

Status values: `pending`, `sent`, `delivered`, `read`, `failed`

### Service: `app/services/engagement_service.py`

Functions:
- `create_engagement(db, org_id, call_log_id, contact_phone, contact_email, extraction_data, ghl_contact_id)` → LeadEngagement
- `update_touchpoint(db, call_log_id, touchpoint_key, message_data)` → LeadEngagement
- `update_report_link(db, call_log_id, report_link)` → LeadEngagement
- `get_engagement(db, call_log_id)` → LeadEngagement | None
- `get_engagement_by_phone(db, org_id, contact_phone)` → LeadEngagement | None
- `get_analytics_summary(db, org_id, start_date, end_date)` → dict with aggregated stats

All functions use async SQLAlchemy sessions.

### API: `app/api/engagements.py`

#### POST /api/engagements
Create engagement record after Gemini extraction.

Request:
```json
{
  "call_log_id": "uuid",
  "contact_phone": "+919609775259",
  "contact_email": "animesh@example.com",
  "extraction_data": { ... },
  "ghl_contact_id": "ghl-123"
}
```

Response: 201
```json
{
  "id": "uuid",
  "call_log_id": "uuid",
  "status": "created"
}
```

#### PATCH /api/engagements/{call_log_id}/touchpoint
Update a specific touchpoint after message send.

Request:
```json
{
  "touchpoint_key": "t1_wa",
  "message_id": "wati-msg-123",
  "conversation_id": null,
  "template": "sneha_post_call_links",
  "subject": null,
  "status": "sent"
}
```

Response: 200
```json
{
  "call_log_id": "uuid",
  "touchpoint_key": "t1_wa",
  "status": "updated"
}
```

#### PATCH /api/engagements/{call_log_id}/report-link
Update report link after GCS upload.

Request:
```json
{
  "report_link": "https://storage.googleapis.com/fwai-reports/roadmaps/xxx.pdf"
}
```

#### GET /api/engagements/{call_log_id}
Get full engagement record.

#### GET /api/engagements/analytics?org_id={uuid}&start={date}&end={date}
Aggregated stats:
```json
{
  "total_engagements": 150,
  "touchpoints": {
    "t1_wa": {"sent": 150, "delivered": 142, "read": 98, "failed": 3},
    "t1_email": {"sent": 150, "delivered": 145, "opened": 67, "clicked": 23},
    "t2_wa": {"sent": 120, "delivered": 115, "read": 78, "failed": 2},
    "t2_email": {"sent": 120, "delivered": 118, "opened": 54, "clicked": 31}
  },
  "qualification_rate": 0.80,
  "report_generated": 120
}
```

### GHL — what stays there

Only these 3 things go to GHL:
1. **Tags**: `sneha_connected`, `personalized_track`
2. **Custom fields**: `profession_spoken`, `confirmed_saturday`, `report_link`
3. These are needed for GHL T3-T8 workflow automations

### n8n integration

The n8n workflow calls these Wavelength API endpoints:
1. After Gemini extraction → `POST /api/engagements`
2. After T1 WA send → `PATCH /api/engagements/{id}/touchpoint` (key: t1_wa)
3. After T1 Email send → `PATCH /api/engagements/{id}/touchpoint` (key: t1_email)
4. After GCS upload → `PATCH /api/engagements/{id}/report-link`
5. After T2 WA send → `PATCH /api/engagements/{id}/touchpoint` (key: t2_wa)
6. After T2 Email send → `PATCH /api/engagements/{id}/touchpoint` (key: t2_email)

Auth: Same `x-api-key` header used by the webhook endpoint.

### Tests

#### Unit tests (test_engagement_service.py)
- create_engagement: valid data, duplicate call_log_id rejected
- update_touchpoint: valid key, invalid key rejected, merges with existing touchpoints
- update_report_link: sets link, works when engagement exists
- get_engagement: found, not found returns None
- get_analytics_summary: correct aggregation, empty date range

#### Integration tests (test_engagement_api.py)
- POST create → PATCH touchpoint → GET full flow
- POST with missing required fields → 400
- PATCH non-existent engagement → 404
- GET analytics with date range filtering
- Duplicate call_log_id → 409 conflict

### Files to create/modify

New files:
- `app/models/lead_engagement.py` — SQLAlchemy model
- `app/services/engagement_service.py` — service layer
- `app/api/engagements.py` — API routes
- `alembic/versions/040_add_lead_engagements_table.py` — migration
- `tests/test_engagement_service.py` — unit tests
- `tests/test_engagement_api.py` — integration tests

Modify:
- `app/main.py` — register engagements router
