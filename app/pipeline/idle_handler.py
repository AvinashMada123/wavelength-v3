"""
Silence/idle escalation handler for Pipecat voice calls.

Uses UserIdleProcessor's retry callback pattern:
  retry_count 1 → gentle nudge
  retry_count 2 → firmer check-in
  retry_count 3 → goodbye + hang up (return False to stop monitoring)
"""

from __future__ import annotations

import structlog
from pipecat.frames.frames import EndFrame, LLMMessagesAppendFrame

logger = structlog.get_logger(__name__)


class IdleEscalationHandler:
    def __init__(self, silence_timeout: int = 5):
        self._silence_timeout = silence_timeout

    async def on_idle(self, processor, retry_count: int) -> bool:
        """Called by UserIdleProcessor when user is idle.

        Args:
            processor: The UserIdleProcessor instance.
            retry_count: How many times idle has fired (1, 2, 3, ...).

        Returns:
            True to keep monitoring, False to stop.
        """
        logger.info("user_idle_escalation", level=retry_count, timeout=self._silence_timeout)

        if retry_count == 1:
            message = {
                "role": "user",
                "content": "[SYSTEM: The user has been silent. Gently check if they're still there.]",
            }
            await processor.push_frame(LLMMessagesAppendFrame(messages=[message], run_llm=True))
            return True

        elif retry_count == 2:
            message = {
                "role": "user",
                "content": (
                    "[SYSTEM: The user is still silent after your check-in. "
                    "Ask once more if they can hear you. Keep it short — just "
                    "'Hello? Can you hear me?' Do NOT share any information or say goodbye yet.]"
                ),
            }
            await processor.push_frame(LLMMessagesAppendFrame(messages=[message], run_llm=True))
            return True

        else:
            # Level 3+: say goodbye and hang up.
            message = {
                "role": "user",
                "content": "[SYSTEM: The user has been completely silent for a long time. Say ONLY a brief goodbye like 'Looks like you are busy, I will try again later. Take care!' Do NOT dump any information. Just a short goodbye.]",
            }
            await processor.push_frame(LLMMessagesAppendFrame(messages=[message], run_llm=True))
            await processor.push_frame(EndFrame())
            return False
