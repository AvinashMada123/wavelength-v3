"""Phrase-level text aggregator for lower TTS latency.

Splits LLM output at commas, semicolons, colons, and sentence boundaries
instead of waiting for full sentences. Reduces time-to-first-audio by
~300-600ms in typical conversational responses.
"""

from __future__ import annotations

from typing import AsyncIterator, Optional

from pipecat.utils.text.base_text_aggregator import (
    Aggregation,
    AggregationType,
    BaseTextAggregator,
)


class PhraseTextAggregator(BaseTextAggregator):
    """Split text at phrase boundaries for faster TTS delivery.

    Standard SENTENCE aggregation waits for . ! ? + lookahead before sending
    text to TTS. For a 40-word response, this means ~650ms of LLM token
    accumulation before TTS even starts.

    This aggregator also splits at commas, semicolons, and colons, sending
    shorter phrases to TTS sooner. The first phrase reaches the user
    significantly faster while the pipeline overlaps LLM generation with
    TTS synthesis of earlier phrases.

    Sentence endings always trigger a split. Phrase delimiters only trigger
    a split when the accumulated text meets min_phrase_chars, preventing
    excessively short TTS fragments.

    When adaptive=True, uses a lower threshold for the first phrase (fast TTFB)
    and a higher threshold for subsequent phrases (fewer TTS round-trips,
    fewer inter-phrase gaps).
    """

    _PHRASE_DELIMS = frozenset(",;:")
    _SENTENCE_ENDS = frozenset(".!?")

    def __init__(
        self,
        *,
        min_phrase_chars: int = 10,
        subsequent_phrase_chars: int = 25,
        adaptive: bool = False,
        **kwargs,
    ):
        super().__init__(aggregation_type=AggregationType.SENTENCE, **kwargs)
        self._text = ""
        self._first_phrase_chars = min_phrase_chars
        self._subsequent_phrase_chars = subsequent_phrase_chars
        self._adaptive = adaptive
        self._min_phrase_chars = min_phrase_chars  # active threshold
        self._emissions = 0
        self._pending_pos: int | None = None
        self._is_sentence_end: bool = False

    @property
    def text(self) -> Aggregation:
        return Aggregation(text=self._text.strip(), type="phrase")

    async def aggregate(self, text: str) -> AsyncIterator[Aggregation]:
        for char in text:
            self._text += char

            # Waiting for non-whitespace lookahead after a delimiter
            if self._pending_pos is not None:
                if not char.strip():
                    continue  # whitespace — keep waiting

                # Non-whitespace after delimiter: decide whether to split
                split_text = self._text[: self._pending_pos].strip()
                should_split = self._is_sentence_end or (
                    len(split_text) >= self._min_phrase_chars
                )

                if should_split and split_text:
                    remainder = self._text[self._pending_pos :]
                    self._text = remainder
                    self._pending_pos = None
                    self._is_sentence_end = False
                    self._emissions += 1
                    # Adaptive: raise threshold after first phrase for fewer gaps
                    if self._adaptive and self._emissions == 1:
                        self._min_phrase_chars = self._subsequent_phrase_chars
                    yield Aggregation(text=split_text, type="phrase")
                    # Check if the lookahead char is itself a delimiter
                    self._check_delimiter(char)
                else:
                    self._pending_pos = None
                    self._is_sentence_end = False
                continue

            self._check_delimiter(char)

    def _check_delimiter(self, char: str):
        """Mark a potential split point if char is a delimiter."""
        if char in self._SENTENCE_ENDS:
            self._pending_pos = len(self._text)
            self._is_sentence_end = True
        elif char in self._PHRASE_DELIMS:
            self._pending_pos = len(self._text)
            self._is_sentence_end = False

    async def flush(self) -> Optional[Aggregation]:
        if self._text.strip():
            result = self._text.strip()
            await self.reset()
            return Aggregation(text=result, type="phrase")
        return None

    async def handle_interruption(self):
        self._text = ""
        self._pending_pos = None
        self._is_sentence_end = False
        # Reset adaptive threshold so next response starts with fast TTFB
        self._emissions = 0
        if self._adaptive:
            self._min_phrase_chars = self._first_phrase_chars

    async def reset(self):
        self._text = ""
        self._pending_pos = None
        self._is_sentence_end = False
        self._emissions = 0
        if self._adaptive:
            self._min_phrase_chars = self._first_phrase_chars
