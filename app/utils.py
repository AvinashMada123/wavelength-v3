"""Shared utility helpers."""

from __future__ import annotations

import re


def normalize_phone(phone: str) -> str:
    """Normalize a phone number to E.164 format.

    If the number already has a '+' prefix, it is assumed to be valid E.164
    and returned as-is (after stripping whitespace/punctuation).

    For numbers without '+', applies Indian-default heuristics:
      - 09609775259   → +919609775259  (leading 0, 11 digits → Indian)
      - 9609775259    → +919609775259  (bare 10 digits → Indian)
      - 919609775259  → +919609775259  (91 prefix, 12 digits → Indian)
      - 009609775259  → +919609775259  (00 prefix, remaining 10 digits → Indian)
      - 13177127687   → +13177127687   (11+ digits → already has country code)
    """
    # Strip whitespace, dashes, parens, dots
    phone = re.sub(r"[\s\-().]+", "", phone.strip())

    # Already has + prefix → valid E.164, return as-is
    if phone.startswith("+"):
        return phone

    # Strip leading 00 (international dialing prefix)
    if phone.startswith("00"):
        phone = phone[2:]
        # After stripping 00, if remaining is 10 digits it could be Indian
        # Otherwise it has a country code already
        if len(phone) != 10:
            return f"+{phone}"

    # Strip leading 91 country code if present (and remaining is 10 digits)
    if phone.startswith("91") and len(phone) == 12:
        phone = phone[2:]

    # Strip single leading 0 (Indian domestic trunk prefix)
    if phone.startswith("0") and len(phone) == 11:
        phone = phone[1:]

    # 10-digit number → assume Indian
    if len(phone) == 10 and phone.isdigit():
        return f"+91{phone}"

    # Longer number → assume it already includes a country code
    if phone.isdigit() and len(phone) > 10:
        return f"+{phone}"

    # Can't normalize — return with + prefix
    return f"+{phone}" if not phone.startswith("+") else phone


# Keep old name as alias for backward compatibility
normalize_phone_india = normalize_phone
