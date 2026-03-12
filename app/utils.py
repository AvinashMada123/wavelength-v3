"""Shared utility helpers."""

from __future__ import annotations

import re


def normalize_phone_india(phone: str) -> str:
    """Normalize an Indian phone number to E.164 format (+91XXXXXXXXXX).

    Handles common variants:
      - 09609775259   → +919609775259  (leading 0)
      - 9609775259    → +919609775259  (no prefix)
      - 919609775259  → +919609775259  (91 without +)
      - +919609775259 → +919609775259  (already correct)
      - 009609775259  → +919609775259  (double zero prefix)

    Non-Indian numbers (already have + with a non-91 code) are returned as-is.
    """
    # Strip whitespace, dashes, parens, dots
    phone = re.sub(r"[\s\-().]+", "", phone.strip())

    # Already has a + prefix with non-91 country code → leave as-is
    if phone.startswith("+") and not phone.startswith("+91"):
        return phone

    # Strip leading + if present
    if phone.startswith("+"):
        phone = phone[1:]

    # Strip leading 00 (international dialing prefix)
    if phone.startswith("00"):
        phone = phone[2:]

    # Strip leading 91 country code if present (and remaining is 10 digits)
    if phone.startswith("91") and len(phone) == 12:
        phone = phone[2:]

    # Strip single leading 0 (domestic trunk prefix)
    if phone.startswith("0") and len(phone) == 11:
        phone = phone[1:]

    # At this point we should have a 10-digit Indian number
    if len(phone) == 10 and phone.isdigit():
        return f"+91{phone}"

    # Fallback: return with + if it looks like it has a country code
    if phone.isdigit() and len(phone) > 10:
        return f"+{phone}"

    # Can't normalize — return original with + prefix
    return f"+{phone}" if not phone.startswith("+") else phone
