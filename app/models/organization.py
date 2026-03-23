"""Organization model settings schema documentation.

The Organization table has a `settings` JSONB column that stores
per-org configuration. No migration is needed for new keys -- they
are read at runtime with safe defaults.

settings JSONB schema:
  {
    "business_hours": {
      "enabled": true,
      "start": "09:00",
      "end": "19:00",
      "days": ["mon", "tue", "wed", "thu", "fri", "sat"],
      "timezone": "Asia/Kolkata"
    },
    "rate_limits": {
      "daily_cap": 5,
      "hourly_cap": 2,
      "cooldown_seconds": 60
    }
  }

Usage:
  business_hours = org.settings.get("business_hours", {})
  rate_limits = org.settings.get("rate_limits", {})
"""
