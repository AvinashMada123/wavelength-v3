"""Comprehensive unit tests for n8n webhook payload builder."""

import sys
from types import SimpleNamespace

# Mock structlog before importing the module under test
sys.modules.setdefault(
    "structlog",
    SimpleNamespace(
        get_logger=lambda *a, **kw: SimpleNamespace(
            info=lambda *a, **kw: None,
            warning=lambda *a, **kw: None,
            error=lambda *a, **kw: None,
            debug=lambda *a, **kw: None,
        )
    ),
)

from app.services.n8n_webhook import build_payload, _parse_json_field, _extract_bot_config_data


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_automation(
    *,
    payload_sections: list[str] | None = None,
    include_transcript: bool = False,
    custom_fields: dict | None = None,
    timing: str = "post_call",
    automation_id: str = "auto-001",
    name: str = "Test Automation",
) -> dict:
    auto: dict = {
        "id": automation_id,
        "name": name,
        "timing": timing,
    }
    if payload_sections is not None:
        auto["payload_sections"] = payload_sections
    if include_transcript:
        auto["include_transcript"] = True
    if custom_fields is not None:
        auto["custom_fields"] = custom_fields
    return auto


def make_call_data(
    *,
    call_sid: str = "CALL-123",
    call_duration: int = 120,
    outcome: str = "completed",
    recording_url: str | None = "https://rec.example.com/abc",
    started_at: str = "2026-03-28T10:00:00Z",
    ended_at: str = "2026-03-28T10:02:00Z",
) -> dict:
    d: dict = {
        "call_sid": call_sid,
        "call_duration": call_duration,
        "outcome": outcome,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    if recording_url is not None:
        d["recording_url"] = recording_url
    return d


def make_analysis(
    *,
    summary: str = "Good conversation about pricing.",
    sentiment: str = "positive",
    sentiment_score: float = 0.85,
    lead_temperature: str = "hot",
    goal_outcome: str = "achieved",
    interest_level: str = "high",
    captured_data: dict | None = None,
    red_flags: list[str] | None = None,
    objections: list[str] | None = None,
    buying_signals: list[str] | None = None,
) -> dict:
    return {
        "summary": summary,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
        "lead_temperature": lead_temperature,
        "goal_outcome": goal_outcome,
        "interest_level": interest_level,
        "captured_data": captured_data or {"email": "test@example.com"},
        "red_flags": red_flags or [],
        "objections": objections or [],
        "buying_signals": buying_signals or ["asked about pricing"],
    }


def make_contact(
    *,
    contact_name: str = "Jane Doe",
    contact_phone: str = "+15551234567",
    ghl_contact_id: str | None = "ghl-999",
    lead_id: str | None = "lead-555",
) -> dict:
    return {
        "contact_name": contact_name,
        "contact_phone": contact_phone,
        "ghl_contact_id": ghl_contact_id,
        "lead_id": lead_id,
    }


def make_bot_config(
    *,
    agent_name: str = "Sales Bot",
    company_name: str = "Wavelength AI",
    context_variables: dict | None = None,
    goal_config: dict | None = None,
    language: str = "en",
) -> dict:
    return {
        "agent_name": agent_name,
        "company_name": company_name,
        "context_variables": context_variables or {"industry": "SaaS"},
        "goal_config": goal_config or {"primary": "book_meeting"},
        "language": language,
    }


def make_transcript() -> list[dict]:
    return [
        {"role": "bot", "text": "Hello, how can I help?"},
        {"role": "user", "text": "Tell me about pricing."},
        {"role": "bot", "text": "Our plans start at $49/month."},
    ]


# ---------------------------------------------------------------------------
# Envelope assertions shared across tests
# ---------------------------------------------------------------------------


def _assert_envelope(payload: dict, automation: dict) -> None:
    """Verify the standard envelope keys are present and correct."""
    assert payload["event"] == automation.get("timing", "unknown")
    assert payload["automation_id"] == automation["id"]
    assert payload["automation_name"] == automation["name"]
    assert "timestamp" in payload
    assert payload["wavelength_version"] == "v3"


# ===========================================================================
# Tests
# ===========================================================================


class TestCallSection:
    """Tests for the 'call' payload section."""

    def test_call_sid_present(self) -> None:
        auto = make_automation(payload_sections=["call"])
        cd = make_call_data(call_sid="SID-ABC")
        result = build_payload(auto, cd, None, None, None)
        assert result["call"]["call_sid"] == "SID-ABC"

    def test_call_duration_present(self) -> None:
        auto = make_automation(payload_sections=["call"])
        cd = make_call_data(call_duration=300)
        result = build_payload(auto, cd, None, None, None)
        assert result["call"]["call_duration"] == 300

    def test_call_outcome_present(self) -> None:
        auto = make_automation(payload_sections=["call"])
        cd = make_call_data(outcome="voicemail")
        result = build_payload(auto, cd, None, None, None)
        assert result["call"]["outcome"] == "voicemail"

    def test_recording_url_present(self) -> None:
        auto = make_automation(payload_sections=["call"])
        cd = make_call_data(recording_url="https://rec.example.com/xyz")
        result = build_payload(auto, cd, None, None, None)
        assert result["call"]["recording_url"] == "https://rec.example.com/xyz"

    def test_recording_url_absent_returns_none(self) -> None:
        auto = make_automation(payload_sections=["call"])
        cd = make_call_data()
        del cd["recording_url"]
        result = build_payload(auto, cd, None, None, None)
        assert result["call"]["recording_url"] is None


class TestAnalysisSection:
    """Tests for the 'analysis' payload section."""

    def test_summary(self) -> None:
        auto = make_automation(payload_sections=["analysis"])
        a = make_analysis(summary="Quick chat.")
        result = build_payload(auto, None, a, None, None)
        assert result["analysis"]["summary"] == "Quick chat."

    def test_sentiment_and_score(self) -> None:
        auto = make_automation(payload_sections=["analysis"])
        a = make_analysis(sentiment="negative", sentiment_score=-0.6)
        result = build_payload(auto, None, a, None, None)
        assert result["analysis"]["sentiment"] == "negative"
        assert result["analysis"]["sentiment_score"] == -0.6

    def test_goal_outcome(self) -> None:
        auto = make_automation(payload_sections=["analysis"])
        a = make_analysis(goal_outcome="failed")
        result = build_payload(auto, None, a, None, None)
        assert result["analysis"]["goal_outcome"] == "failed"

    def test_captured_data(self) -> None:
        auto = make_automation(payload_sections=["analysis"])
        a = make_analysis(captured_data={"email": "a@b.com", "budget": "10k"})
        result = build_payload(auto, None, a, None, None)
        assert result["analysis"]["captured_data"] == {"email": "a@b.com", "budget": "10k"}

    def test_red_flags(self) -> None:
        auto = make_automation(payload_sections=["analysis"])
        a = make_analysis(red_flags=["competitor_mention", "pricing_objection"])
        result = build_payload(auto, None, a, None, None)
        assert result["analysis"]["red_flags"] == ["competitor_mention", "pricing_objection"]

    def test_none_analysis_excluded(self) -> None:
        auto = make_automation(payload_sections=["analysis"])
        result = build_payload(auto, None, None, None, None)
        assert "analysis" not in result


class TestContactSection:
    """Tests for the 'contact' payload section."""

    def test_name_and_phone(self) -> None:
        auto = make_automation(payload_sections=["contact"])
        c = make_contact(contact_name="Alice", contact_phone="+14155550000")
        result = build_payload(auto, None, None, c, None)
        assert result["contact"]["contact_name"] == "Alice"
        assert result["contact"]["contact_phone"] == "+14155550000"

    def test_ghl_contact_id(self) -> None:
        auto = make_automation(payload_sections=["contact"])
        c = make_contact(ghl_contact_id="ghl-42")
        result = build_payload(auto, None, None, c, None)
        assert result["contact"]["ghl_contact_id"] == "ghl-42"

    def test_none_contact_excluded(self) -> None:
        auto = make_automation(payload_sections=["contact"])
        result = build_payload(auto, None, None, None, None)
        assert "contact" not in result


class TestBotConfigSection:
    """Tests for the 'bot_config' payload section."""

    def test_agent_name(self) -> None:
        auto = make_automation(payload_sections=["bot_config"])
        bc = make_bot_config(agent_name="Support Bot")
        result = build_payload(auto, None, None, None, bc)
        assert result["bot_config"]["agent_name"] == "Support Bot"

    def test_company_name(self) -> None:
        auto = make_automation(payload_sections=["bot_config"])
        bc = make_bot_config(company_name="Acme Inc")
        result = build_payload(auto, None, None, None, bc)
        assert result["bot_config"]["company_name"] == "Acme Inc"

    def test_context_variables(self) -> None:
        auto = make_automation(payload_sections=["bot_config"])
        bc = make_bot_config(context_variables={"plan": "enterprise", "seats": 50})
        result = build_payload(auto, None, None, None, bc)
        assert result["bot_config"]["context_variables"] == {"plan": "enterprise", "seats": 50}

    def test_goal_config(self) -> None:
        auto = make_automation(payload_sections=["bot_config"])
        bc = make_bot_config(goal_config={"primary": "qualify_lead", "secondary": "collect_email"})
        result = build_payload(auto, None, None, None, bc)
        assert result["bot_config"]["goal_config"]["primary"] == "qualify_lead"
        assert result["bot_config"]["goal_config"]["secondary"] == "collect_email"


class TestTranscriptToggle:
    """Tests for transcript inclusion controlled by include_transcript flag."""

    def test_included_when_true(self) -> None:
        auto = make_automation(payload_sections=[], include_transcript=True)
        t = make_transcript()
        result = build_payload(auto, None, None, None, None, transcript=t)
        assert result["transcript"] == t

    def test_excluded_when_false(self) -> None:
        auto = make_automation(payload_sections=[])
        auto["include_transcript"] = False
        t = make_transcript()
        result = build_payload(auto, None, None, None, None, transcript=t)
        assert "transcript" not in result

    def test_excluded_by_default(self) -> None:
        auto = make_automation(payload_sections=[])
        t = make_transcript()
        result = build_payload(auto, None, None, None, None, transcript=t)
        assert "transcript" not in result


class TestCustomFields:
    """Tests for custom_fields merging at top level."""

    def test_merged_at_top_level(self) -> None:
        auto = make_automation(
            payload_sections=[],
            custom_fields={"source": "landing_page", "campaign_id": "camp-77"},
        )
        result = build_payload(auto, None, None, None, None)
        assert result["source"] == "landing_page"
        assert result["campaign_id"] == "camp-77"

    def test_does_not_clobber_section_keys(self) -> None:
        auto = make_automation(
            payload_sections=["call"],
            custom_fields={"call": "should_not_overwrite", "extra": "ok"},
        )
        cd = make_call_data()
        result = build_payload(auto, cd, None, None, None)
        # "call" key should remain the section dict, not the custom field string
        assert isinstance(result["call"], dict)
        assert result["call"]["call_sid"] == cd["call_sid"]
        assert result["extra"] == "ok"

    def test_empty_custom_fields(self) -> None:
        auto = make_automation(payload_sections=[], custom_fields={})
        result = build_payload(auto, None, None, None, None)
        # Only envelope keys should be present
        assert set(result.keys()) == {"event", "automation_id", "automation_name", "timestamp", "wavelength_version"}

    def test_none_custom_fields(self) -> None:
        auto = make_automation(payload_sections=[], custom_fields=None)
        result = build_payload(auto, None, None, None, None)
        assert set(result.keys()) == {"event", "automation_id", "automation_name", "timestamp", "wavelength_version"}


class TestSectionCombinations:
    """Tests for various combinations of payload_sections."""

    def test_single_section(self) -> None:
        auto = make_automation(payload_sections=["contact"])
        c = make_contact()
        result = build_payload(auto, make_call_data(), make_analysis(), c, make_bot_config())
        assert "contact" in result
        assert "call" not in result
        assert "analysis" not in result
        assert "bot_config" not in result

    def test_all_sections(self) -> None:
        auto = make_automation(payload_sections=["call", "analysis", "contact", "bot_config"], include_transcript=True)
        result = build_payload(auto, make_call_data(), make_analysis(), make_contact(), make_bot_config(), transcript=make_transcript())
        assert "call" in result
        assert "analysis" in result
        assert "contact" in result
        assert "bot_config" in result
        assert "transcript" in result

    def test_empty_sections_list(self) -> None:
        auto = make_automation(payload_sections=[])
        result = build_payload(auto, make_call_data(), make_analysis(), make_contact(), make_bot_config())
        assert "call" not in result
        assert "analysis" not in result
        assert "contact" not in result
        assert "bot_config" not in result

    def test_unknown_section_ignored(self) -> None:
        auto = make_automation(payload_sections=["call", "nonexistent_section"])
        cd = make_call_data()
        result = build_payload(auto, cd, None, None, None)
        assert "call" in result
        assert "nonexistent_section" not in result


class TestPayloadEnvelope:
    """Tests for the standard envelope present on every payload."""

    def test_event_matches_timing(self) -> None:
        auto = make_automation(payload_sections=[], timing="pre_call")
        result = build_payload(auto, None, None, None, None)
        assert result["event"] == "pre_call"

    def test_automation_id_and_name(self) -> None:
        auto = make_automation(payload_sections=[], automation_id="auto-XYZ", name="My Hook")
        result = build_payload(auto, None, None, None, None)
        assert result["automation_id"] == "auto-XYZ"
        assert result["automation_name"] == "My Hook"

    def test_timestamp_and_version_always_present(self) -> None:
        auto = make_automation(payload_sections=[])
        result = build_payload(auto, None, None, None, None)
        assert "timestamp" in result
        # Timestamp should be a valid ISO string
        assert "T" in result["timestamp"]
        assert result["wavelength_version"] == "v3"


# ---------------------------------------------------------------------------
# _parse_json_field
# ---------------------------------------------------------------------------


class TestParseJsonField:
    def test_string_json_parsed(self):
        result = _parse_json_field('{"key": "value"}')
        assert result == {"key": "value"}

    def test_dict_returned_unchanged(self):
        d = {"key": "value"}
        assert _parse_json_field(d) is d

    def test_list_returned_unchanged(self):
        lst = [1, 2, 3]
        assert _parse_json_field(lst) is lst

    def test_none_returned_unchanged(self):
        assert _parse_json_field(None) is None

    def test_invalid_json_string_returned_as_is(self):
        assert _parse_json_field("not json") == "not json"

    def test_nested_json_string(self):
        result = _parse_json_field('{"event_host": "Avinash", "webinar_link": "https://zoom.us/123"}')
        assert result["event_host"] == "Avinash"
        assert result["webinar_link"] == "https://zoom.us/123"

    def test_json_array_string(self):
        result = _parse_json_field('[{"id": "a"}, {"id": "b"}]')
        assert isinstance(result, list)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _extract_bot_config_data — JSON field parsing
# ---------------------------------------------------------------------------


class TestExtractBotConfigData:
    def test_string_context_variables_parsed(self):
        bot = SimpleNamespace(
            agent_name="Test Bot",
            company_name="Test Co",
            context_variables='{"event_host": "Avinash", "webinar_link": "https://zoom.us/123"}',
            goal_config='{"goal_type": "Event Invitation"}',
            language="en-IN",
        )
        result = _extract_bot_config_data(bot)
        assert isinstance(result["context_variables"], dict)
        assert result["context_variables"]["event_host"] == "Avinash"
        assert result["context_variables"]["webinar_link"] == "https://zoom.us/123"
        assert isinstance(result["goal_config"], dict)
        assert result["goal_config"]["goal_type"] == "Event Invitation"

    def test_already_parsed_dict_unchanged(self):
        bot = SimpleNamespace(
            agent_name="Test Bot",
            company_name="Test Co",
            context_variables={"event_host": "Avinash"},
            goal_config={"goal_type": "Event Invitation"},
            language="en-IN",
        )
        result = _extract_bot_config_data(bot)
        assert result["context_variables"] == {"event_host": "Avinash"}

    def test_none_fields_stay_none(self):
        bot = SimpleNamespace(
            agent_name="Test Bot",
            company_name="Test Co",
            context_variables=None,
            goal_config=None,
            language="en-IN",
        )
        result = _extract_bot_config_data(bot)
        assert result["context_variables"] is None
        assert result["goal_config"] is None
