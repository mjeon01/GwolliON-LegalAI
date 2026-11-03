"""Chat follows the selected language without enabling any cloud provider."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.analysis import extract, evaluate
from backend.app import create_app
from backend.chat_translation import local_fields
from backend.schemas import AnalyzeRequest

ROOT = Path(__file__).resolve().parents[1]


def translator(schema, prompt, **kwargs):
    if 'equivalent' in schema['properties']:
        return {'equivalent': True, 'errors': []}, 'mock-qwen'
    fields = json.loads(prompt.split('\n', 1)[1])
    output = {}
    for key, field in fields.items():
        tokens = ' '.join(re.findall(r'⟪G\d{4}⟫', (field['text'] if isinstance(field, dict) else field)))
        text = ('지급 전에 확인할 서류를 알려주세요.' if ('into Korean.' in prompt or '韩语 (Korean)' in prompt) else
                '请先书面确认文件提供日期和付款时间。' if 'Simplified Chinese' in prompt else
                'Confirme por escrito la entrega de documentos y la fecha de pago.')
        output[key] = text + ' ' + tokens
    return output, 'mock-qwen'


def answer_model(schema, prompt, **kwargs):
    if kwargs.get('on_progress'):
        kwargs['on_progress']('generating')
    return {'answer': '지급 전에 서류 제공일을 서면으로 확인하세요.',
            'evidence_ids': [schema['properties']['evidence_ids']['items']['enum'][0]],
            'source_ids': [], 'citations': []}, 'mock-qwen'


class ChatLanguageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.app = create_app(Path(folder.name) / 'test.sqlite3')
        self.client = TestClient(self.app); self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        request = AnalyzeRequest(text=(ROOT / 'tests/fixtures/samples/sale-risk.txt').read_text(), contract_type='sale')
        b, t, x = extract(request)
        result = evaluate(request, b, t, x, 'language-fixture', 1)
        self.app.state.store.create('language-fixture', request.model_dump(mode='json'))
        self.app.state.store.start('language-fixture')
        self.app.state.store.finish('language-fixture', result=result)
        self.base = '/api/analyses/language-fixture'
        self.body = {'analysis_revision': 1, 'finding_id': result['review']['findings'][0]['finding_id'], 'engine': 'ollama'}
        for target, side_effect in [('backend.chat_translation.generate', translator),
                                    ('backend.chat.generate', answer_model), ('backend.chat.generate_stream', answer_model),
                                    ('backend.translation.generate', AssertionError('No cloud translation')),
                                    ('backend.openai_client.generate', AssertionError('No cloud calls'))]:
            mock = patch(target, side_effect=side_effect); mock.start(); self.addCleanup(mock.stop)

    def test_chinese_and_spanish_questions_return_selected_language_and_keep_originals(self):
        for language, question, expected in [('zh', '支付余款前需要哪些文件？', '请先书面'),
                                              ('es', '¿Qué documentos debo solicitar?', 'Confirme por escrito')]:
            response = self.client.post(self.base + '/chat/stream', json={**self.body, 'language': language, 'question': question})
            self.assertEqual(response.status_code, 200)
            self.assertIn('event: done', response.text)
            payload = json.loads(response.text.split('event: done\ndata: ')[1].split('\n\n')[0])
            turn = payload['turn']
            self.assertEqual(turn['language'], language)
            self.assertEqual(turn['question'], question)
            self.assertRegex(turn['question_ko'], r'[가-힣]')
            self.assertIn(expected, turn['answer']['text'])
            self.assertIn('서면으로 확인', turn['answer']['text_ko'])
            self.assertIn('translating', response.text)
        saved = self.client.get(self.base + '/chat?analysis_revision=1').json()['turns']
        self.assertEqual([v['language'] for v in saved], ['zh', 'es'])

    def test_quick_prompt_is_translated_and_existing_korean_chat_is_cached_per_language(self):
        original = self.client.post(self.base + '/chat', json={**self.body, 'question': '쉽게 설명해줘', 'intent': 'explain'}).json()['turn']
        path = self.base + '/chat/1/translation'
        with patch('backend.chat_translation.generate', side_effect=translator) as model:
            zh = self.client.post(path, json={'analysis_revision': 1, 'language': 'zh'})
            calls = model.call_count
            cached = self.client.post(path, json={'analysis_revision': 1, 'language': 'zh'})
            self.assertEqual(model.call_count, calls)
            es = self.client.post(path, json={'analysis_revision': 1, 'language': 'es'})
            self.assertGreater(model.call_count, calls)
        self.assertEqual(zh.json(), cached.json())
        self.assertIn('请先书面', zh.json()['text'])
        self.assertIn('Confirme', es.json()['text'])
        self.assertEqual(zh.json()['text_ko'], original['answer']['text'])
        self.assertIn('“', zh.json()['text'])  # quoted Korean contract remains intact
        saved = self.client.get(self.base + '/chat?analysis_revision=1').json()['turns']
        self.assertEqual(saved, [original])
        self.assertEqual(self.client.post(path, json={'analysis_revision': 2, 'language': 'zh'}).status_code, 409)
        self.assertEqual(self.client.post(self.base + '/chat/99/translation', json={'analysis_revision': 1, 'language': 'zh'}).status_code, 404)

    def test_korean_echo_is_not_accepted_as_chinese_and_failed_answer_is_not_saved(self):
        def echo(schema, prompt, **kwargs):
            if 'equivalent' in schema['properties']:
                return {'equivalent': True, 'errors': []}, 'fake'
            fields = json.loads(prompt.split('\n', 1)[1])
            return {key: field['text'] if isinstance(field, dict) else field for key, field in fields.items()}, 'fake'
        with patch('backend.chat_translation.generate', side_effect=echo):
            response = self.client.post(self.base + '/chat', json={**self.body, 'language': 'zh', 'question': '쉽게 설명해줘', 'intent': 'explain'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('선택한 언어', response.json()['detail'])
        self.assertEqual(self.client.get(self.base + '/chat?analysis_revision=1').json()['turns'], [])

    def test_locked_money_dates_quotes_survive_local_translation(self):
        text = '매수인은 2026-11-03에 5,000,000원을 지급합니다. “잔금과 서류는 동시에 교환한다.”'
        result = local_fields({'answer': text}, 'zh')['answer']
        for expected in ['2026-11-03', '5,000,000원', '“잔금과 서류는 동시에 교환한다.”', '매수인 (买方)']:
            self.assertIn(expected, result)

    def test_semantic_mismatch_is_rejected_and_never_cached(self):
        self.client.post(self.base + '/chat', json={**self.body, 'question': '쉽게 설명해줘', 'intent': 'explain'})

        def incorrect(schema, prompt, **kwargs):
            if 'equivalent' in schema['properties']:
                return {'errors': ['The payer and recipient have been reversed.'], 'equivalent': False}, 'mock-qwen'
            return translator(schema, prompt, **kwargs)

        path = self.base + '/chat/1/translation'
        body = {'analysis_revision': 1, 'language': 'zh'}
        with patch('backend.chat_translation.generate', side_effect=incorrect):
            failed = self.client.post(path, json=body)
        self.assertEqual(failed.status_code, 422)
        self.assertIn('의미·당사자', failed.json()['detail'])
        self.assertEqual(self.client.post(path, json=body).status_code, 200)

    def test_missing_locked_values_are_rejected(self):
        def missing(schema, prompt, **kwargs):
            translated, model = translator(schema, prompt, **kwargs)
            return {key: re.sub(r'⟪G\d{4}⟫', '', value) for key, value in translated.items()}, model

        with patch('backend.chat_translation.generate', side_effect=missing):
            with self.assertRaisesRegex(ValueError, '보존 검사'):
                local_fields({'answer': '매수인은 5,000,000원을 지급합니다.'}, 'zh')


if __name__ == '__main__':
    unittest.main()
