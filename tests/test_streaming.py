"""Streaming must preserve validation, revision boundaries and complete turns."""
from io import BytesIO
import json
from pathlib import Path
from threading import Event
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.app import create_app
from backend.extraction import generate_stream, GenerationCancelled
from backend.store import StaleRevision

ROOT = Path(__file__).resolve().parents[1]


def events(response):
    result = []
    for frame in response.text.split('\n\n'):
        lines = frame.splitlines()
        if not lines or not lines[0].startswith('event: '):
            continue
        result.append((lines[0][7:], json.loads(lines[1][6:])))
    return result


class OllamaStreamTests(unittest.TestCase):
    def test_ndjson_unicode_and_completion_are_required(self):
        lines = [{'response': '{"answer": "한국', 'done': False},
                 {'response': '어"}', 'done': True, 'done_reason': 'stop'}]
        raw = '\n'.join(json.dumps(line, ensure_ascii=False) for line in lines).encode()
        phases = []
        with patch('backend.extraction.urlopen', return_value=BytesIO(raw)) as request:
            result, _ = generate_stream({}, 'synthetic', on_progress=phases.append)
        self.assertEqual(result, {'answer': '한국어'})
        self.assertEqual(phases, ['generating', 'generating'])
        self.assertTrue(json.loads(request.call_args.args[0].data)['stream'])
        with patch('backend.extraction.urlopen', return_value=BytesIO(json.dumps(lines[0]).encode())):
            with self.assertRaisesRegex(ValueError, '중단'):
                generate_stream({}, 'synthetic')

    def test_cancel_and_token_limit_do_not_return_partial_json(self):
        cancelled = Event(); cancelled.set()
        with patch('backend.extraction.urlopen', return_value=BytesIO(b'')):
            with self.assertRaises(GenerationCancelled):
                generate_stream({}, 'synthetic', cancelled=cancelled)
        line = json.dumps({'response': '{}', 'done': True, 'done_reason': 'length'}).encode()
        with patch('backend.extraction.urlopen', return_value=BytesIO(line)):
            with self.assertRaisesRegex(ValueError, '길어'):
                generate_stream({}, 'synthetic')


class ChatStreamTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.client = TestClient(create_app(Path(folder.name) / 'test.sqlite3'))
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        started = self.client.post('/api/analyses', json={
            'text': (ROOT / 'tests/fixtures/samples/sale-risk.txt').read_text(), 'contract_type': 'sale',
            'engine': 'rules', 'context': {'document_complete': True},
        }).json()
        self.base = '/api/analyses/' + started['analysis_id']
        for _ in range(100):
            self.result = self.client.get(self.base).json()
            if self.result['status'] not in {'queued', 'running'}:
                break
            time.sleep(0.01)
        self.assertIn(self.result['status'], {'completed', 'awaiting_input'})
        self.body = {'analysis_revision': 1, 'question': '서류 제공일을 어떻게 확인하나요?',
                     'finding_id': self.result['review']['findings'][0]['finding_id'], 'engine': 'ollama'}

    def valid(self, schema, prompt, **kwargs):
        kwargs['on_progress']('generating')
        block = schema['properties']['evidence_ids']['items']['enum'][0]
        return {'answer': '서류 제공일과 대금 지급 시점을 서면으로 확인하세요.', 'evidence_ids': [block],
                'source_ids': [], 'citations': []}, 'mock-qwen'

    def history(self):
        return self.client.get(self.base + '/chat?analysis_revision=1').json()['turns']

    def test_streams_validated_text_and_saves_one_complete_turn(self):
        with patch('backend.chat.generate_stream', side_effect=self.valid):
            response = self.client.post(self.base + '/chat/stream', json=self.body)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        received = events(response)
        self.assertEqual(received[0], ('status', {'phase': 'preparing'}))
        self.assertIn(('status', {'phase': 'generating'}), received)
        self.assertIn(('status', {'phase': 'verifying'}), received)
        self.assertEqual(received[-1][0], 'done')
        text = ''.join(data['text'] for name, data in received if name == 'delta')
        self.assertEqual(text, received[-1][1]['turn']['answer']['text'])
        self.assertEqual(self.history(), [received[-1][1]['turn']])

    def test_rejected_first_attempt_never_leaks_to_browser(self):
        calls = []
        def model(schema, prompt, **kwargs):
            result = self.valid(schema, prompt, **kwargs)
            calls.append(True)
            if len(calls) == 1:
                result[0]['answer'] = '이 계약은 사기죄입니다.'
            return result
        with patch('backend.chat.generate_stream', side_effect=model):
            response = self.client.post(self.base + '/chat/stream', json=self.body)
        self.assertNotIn('사기죄', response.text)
        self.assertIn(('status', {'phase': 'retrying'}), events(response))
        self.assertEqual(events(response)[-1][0], 'done')
        self.assertEqual(len(self.history()), 1)

    def test_error_stream_preserves_history_without_delta(self):
        with patch('backend.chat.generate_stream', side_effect=TimeoutError):
            response = self.client.post(self.base + '/chat/stream', json=self.body)
        self.assertEqual([name for name, _ in events(response)], ['status', 'status', 'error'])
        self.assertEqual(self.history(), [])

    def test_stale_commit_never_exposes_an_answer(self):
        with patch('backend.chat.generate_stream', side_effect=self.valid), \
             patch('backend.store.Store.append_chat', side_effect=StaleRevision):
            response = self.client.post(self.base + '/chat/stream', json=self.body)
        received = events(response)
        self.assertEqual(received[-1][0], 'error')
        self.assertEqual(received[-1][1]['status'], 409)
        self.assertNotIn('delta', [name for name, _ in received])
        self.assertEqual(self.history(), [])
        response = self.client.post(self.base + '/chat/stream', json={**self.body, 'analysis_revision': 2})
        self.assertEqual(response.status_code, 409)

    def test_quick_explanation_streams_without_model(self):
        with patch('backend.chat.generate_stream', side_effect=AssertionError('No model for quick explanation')):
            response = self.client.post(self.base + '/chat/stream', json={**self.body, 'intent': 'explain'})
        self.assertEqual(events(response)[-1][1]['turn']['answer']['method'], 'verified_explanation')
        self.assertEqual(len(self.history()), 1)


if __name__ == '__main__':
    unittest.main()
