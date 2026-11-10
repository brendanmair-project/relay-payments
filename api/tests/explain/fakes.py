"""A fake model client for every explanation test: no test needs a real model or the network."""

import json
import threading
from collections.abc import Sequence

from app.explain.model import ModelUnavailable


def answer(text: str, seqs: Sequence[int], cause: str | None = None) -> str:
    """The JSON a well-behaved model returns."""
    body: dict[str, object] = {"text": text, "cited_event_seqs": list(seqs)}
    if cause is not None:
        body["cause"] = cause
    return json.dumps(body)


class FakeModel:
    name = "granite3.3:2b"

    def __init__(
        self,
        reply: str | None = None,
        *,
        unavailable: str | None = None,
        block: threading.Event | None = None,
    ) -> None:
        self.reply = reply
        self.unavailable = unavailable
        self.block = block
        self.prompts: list[str] = []
        self.started = threading.Event()

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.started.set()
        if self.block is not None:
            self.block.wait(timeout=30)
        if self.unavailable is not None:
            raise ModelUnavailable(self.unavailable)
        assert self.reply is not None
        return self.reply
