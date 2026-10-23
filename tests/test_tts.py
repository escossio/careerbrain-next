import unittest
from uuid import uuid4

from careerbrain.tts import TtsService, TtsUnavailable


class SyntheticAdapter:
    def __init__(self): self.command = None
    def synthesize(self, command): self.command = command; return b'ID3synthetic'


class TtsBoundaryTests(unittest.TestCase):
    def payload(self):
        return {'schema_version': 'careerbrain.tts.v1', 'notification_id': 'notice-1',
                'template': 'NEW_MATCHES', 'count': 2, 'language': 'pt-BR'}

    def test_owner_is_resolved_server_side_and_adapter_gets_minimized_command(self):
        adapter = SyntheticAdapter(); tenant = uuid4()
        service = TtsService(adapter, lambda candidate, notification: candidate == tenant and notification == 'notice-1')
        self.assertEqual(service.speak(tenant, self.payload()), b'ID3synthetic')
        self.assertEqual((adapter.command.template, adapter.command.count, adapter.command.language), ('NEW_MATCHES', 2, 'pt-BR'))
        self.assertFalse(hasattr(adapter.command, 'notification_id'))

    def test_missing_authorization_or_runtime_adapter_fails_closed(self):
        with self.assertRaises(LookupError): TtsService(SyntheticAdapter()).speak(uuid4(), self.payload())
        with self.assertRaises(TtsUnavailable): TtsService(notification_owner=lambda *_: True).speak(uuid4(), self.payload())


if __name__ == '__main__': unittest.main()
