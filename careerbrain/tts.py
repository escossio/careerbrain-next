"""Dedicated CareerBrain TTS boundary.  It has no route to shared TTS services by default."""
from __future__ import annotations

from dataclasses import dataclass

from tools.contracts import validate


class TtsUnavailable(Exception):
    """The G-TTS runtime authorization/configuration is intentionally absent."""


@dataclass(frozen=True)
class TtsCommand:
    template: str
    count: int
    language: str


class DisabledTtsAdapter:
    """Fail closed without a network request or a provider credential."""
    def synthesize(self, command: TtsCommand) -> bytes:
        raise TtsUnavailable()


class TtsService:
    """Resolve notification ownership server-side, then pass only a minimized command."""
    def __init__(self, adapter=None, notification_owner=None):
        self.adapter = adapter or DisabledTtsAdapter()
        # The runtime implementation must query a dedicated private notification store.
        self.notification_owner = notification_owner or (lambda tenant_id, notification_id: False)

    def speak(self, tenant_id, payload: dict) -> bytes:
        validate('tts-request', payload)
        if not self.notification_owner(tenant_id, payload['notification_id']):
            raise LookupError('notification is not available to this tenant')
        result = self.adapter.synthesize(TtsCommand(payload['template'], payload['count'], payload['language']))
        if not isinstance(result, bytes) or not result:
            raise TtsUnavailable()
        return result
