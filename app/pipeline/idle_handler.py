"""Deterministic silence/idle handler for Pipecat voice calls.

Silence recovery should not go through the LLM. The previous implementation
injected synthetic system turns, which made the model improvise lines like
"Yeah, I am here!" even when nobody had spoken. This handler uses fixed
spoken phrases and hangs up predictably.
"""

from __future__ import annotations

import structlog
from pipecat.frames.frames import EndFrame, TTSSpeakFrame

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
            await processor.push_frame(TTSSpeakFrame(text="Hello? Can you hear me?"))
            return True

        if retry_count >= 2:
            await processor.push_frame(
                TTSSpeakFrame(text="Looks like this is not a good time. I will try again later. Take care!")
            )
            await processor.push_frame(EndFrame())
            return False

        return True
