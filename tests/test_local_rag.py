"""Local model routing and document-grounded reference retrieval."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend import auto_translation
from backend import openai_client
import tests  # noqa: F401 (hermetic test settings)
from backend.analysis import extract, evaluate
from backend.chat import answer_question
from backend.config import ai_provider
from backend.corpus import Corpus, matching_excerpt
from backend.extraction import blocks_from_text, ollama_extract
from backend.retrieval import chat_references, plan, prompt_sources
from backend.schemas import AnalyzeRequest, ChatRequest, IncidentFacts
from backend.translation import translate_document, translate_incident
from scripts.build_reference_index import build


class LocalProviderTests(unittest.TestCase):
    def test_local_mode_rejects_explicit_paid_requests_before_network_or_quota(self):
        with patch('backend.openai_client.ai_provider', return_value='ollama'), \
             patch('backend.openai_client.settings', return_value=('test-only', 'test-model')), \
             patch('backend.openai_client.httpx.Client') as network, \
             patch('backend.openai_client.quota') as quota, \
             self.assertRaises(openai_client.OpenAIError) as raised:
            openai_client.generate({'type': 'object', 'properties': {}}, 'synthetic request')
        self.assertEqual(raised.exception.code, 'openai_disabled')
        network.assert_not_called()
        quota.assert_not_called()

    def test_key_presence_does_not_select_paid_translation(self):
        with patch('backend.config.load_env', return_value={'OPENAI_API_KEY': 'test-only'}), \
             patch.dict('os.environ', {'GWOLLION_AI_PROVIDER': 'ollama'}), \
             patch('backend.auto_translation.openai_client.generate', side_effect=AssertionError('Paid call')), \
             patch('backend.auto_translation.generate', return_value=({'T0': '请确认文件提供日期。'}, 'qwen')) as model:
            result = translate_document('서류 제공일을 확인하세요.', 'zh')
        self.assertEqual(result['method'], 'ollama')
        self.assertIn('请确认', result['text'])
        model.assert_called_once()

    def test_provider_is_explicit_and_invalid_setting_does_not_fall_back(self):
        with patch('backend.config.load_env', return_value={}), patch.dict('os.environ', {'GWOLLION_AI_PROVIDER': 'openai'}):
            self.assertEqual(ai_provider(), 'openai')
        with patch.dict('os.environ', {'GWOLLION_AI_PROVIDER': 'typo'}), self.assertRaises(ValueError):
            ai_provider()

    def test_incident_uses_local_interpretation_and_preserves_original(self):
        facts = IncidentFacts(summary='没有收到答复。', writer='가상인')
        with patch('backend.translation.ai_provider', return_value='ollama'), \
             patch('backend.chat_translation.local_fields', return_value={'summary': '답변을 받지 못했습니다.'}), \
             patch('backend.translation.generate', side_effect=AssertionError('Paid call')):
            result = translate_incident(facts)
        self.assertEqual(result['method'], 'ollama')
        self.assertEqual(result['original']['summary'], facts.summary)
        self.assertEqual(result['incident']['writer'], '가상인')
        self.assertEqual(result['incident']['summary'], '답변을 받지 못했습니다.')


class LocalRetrievalTests(unittest.TestCase):
    def test_all_contract_issues_supply_search_terms(self):
        request = AnalyzeRequest(text='근로계약서\n퇴사하면 위약금을 지급한다.\n근로자는 연차휴가를 포기한다.', contract_type='employment')
        result = plan(request, blocks_from_text(request.text))
        self.assertIn('위약금', result['dataset_terms'])
        self.assertIn('연차휴가', result['dataset_terms'])

    def test_follow_up_search_uses_question_instead_of_previous_issue(self):
        with patch('backend.retrieval.Corpus') as corpus:
            corpus.return_value.search.return_value = []
            result = chat_references({'contract_type': 'employment'}, '연차를 쓰려면 무엇을 확인하나요?', {'issue_type': 'penalty'})
        self.assertEqual(result['topics'][0], 'leave_waiver')
        self.assertEqual(result['terms'][0], '연차휴가')

    def test_excerpt_finds_later_relevant_passage_without_rewriting(self):
        body = '근로계약 ' + '기본 항목 설명. ' * 180 + '연차휴가와 유급휴가에 관한 근로계약 조항 원문입니다.'
        start, text = matching_excerpt(body, ['근로계약', '연차휴가', '유급휴가'])
        self.assertGreater(start, 0)
        self.assertIn('유급휴가', text)
        self.assertEqual(text, body[start:start + len(text)])

    def test_diverse_sources_exclude_validation_and_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            datasets = {
                ('Training', '판결문'): ['보증금 반환 관련 판결문 예시', '보증금 보증금 보증금 관련 추가 판결문', '보증금 중복 원문'],
                ('Training', '유권해석'): ['보증금 관련 유권해석 참고 자료'],
                ('Validation', '판결문'): ['보증금 검증 전용', '보증금 중복 원문'],
            }
            for (split, kind), texts in datasets.items():
                file = root / 'data' / split / (kind + '.zip')
                file.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(file, 'w') as archive:
                    for index, text in enumerate(texts):
                        archive.writestr(f'{index}.json', json.dumps({'sentences': [text]}))
            target = root / 'index.sqlite3'
            build(root / 'data', target)
            results = Corpus(target).search(['보증금'], limit=2, diverse=True)
        self.assertEqual({s['dataset_kind'] for s in results}, {'precedent_reference', 'interpretation_reference'})
        self.assertTrue(all(s['split'] == 'Training' and '중복' not in s['text'] and '검증 전용' not in s['text'] for s in results))

    def test_normal_question_receives_dataset_context_and_keeps_verified_citation(self):
        request = AnalyzeRequest(text='주택 임대차계약서\n특약: 새 임차인이 구해지면 보증금을 반환한다.', contract_type='lease')
        with patch('backend.retrieval.Corpus') as corpus:
            corpus.return_value.search.return_value = []
            b, t, x = extract(request)
            result = evaluate(request, b, t, x, 'rag-test', 1)
        source = {'source_id': 'data-test', 'kind': 'dataset', 'dataset_kind': 'qa_example', 'title': '보증금 상담 예시',
                  'text': '보증금 지급 내역과 반환 요청 기록을 함께 확인하는 상담 예시입니다.', 'split': 'Training'}

        def model(schema, prompt, **kwargs):
            self.assertIn('data-test', prompt)
            return {'answer': '참고 자료의 예시처럼 지급 내역과 요청 기록을 준비하세요.', 'evidence_ids': [b[0]['block_id']],
                    'source_ids': ['data-test'], 'citations': [{'source_id': 'data-test', 'quote': source['text']}]}, 'qwen-test'

        with patch('backend.chat.chat_references', return_value={'status': 'ready', 'topics': ['deposit_return'], 'sources': [source]}), \
             patch('backend.chat.generate', side_effect=model):
            answer = answer_question(result, ChatRequest(analysis_revision=1, question='보증금을 받으려면 무엇을 준비하나요?', engine='ollama'), [])
        self.assertEqual(answer['reference_sources'][0]['source_id'], 'data-test')
        self.assertEqual(answer['citations'][0]['quote'], source['text'])
        self.assertEqual(answer['retrieval']['source_ids'], ['data-test'])

    def test_law_list_does_not_push_all_examples_out_of_prompt(self):
        # Older stored law snapshots omit kind; they must not occupy example slots.
        laws = [{'source_id': str(i), 'title': '법령', 'text': '원문'} for i in range(8)]
        example = {'source_id': 'example', 'kind': 'dataset', 'title': '사례', 'text': '사례 원문'}
        self.assertIn('example', [s['source_id'] for s in prompt_sources({'sources': laws + [example]}, limit=6)])

    def test_official_cases_and_local_examples_both_reach_prompt(self):
        sources = [{'source_id': f'{kind}-{i}', 'kind': kind, 'title': kind, 'text': '참고 원문'}
                   for kind in ('law', 'precedent', 'dataset') for i in range(6)]
        supplied = prompt_sources({'sources': sources}, limit=8)
        self.assertEqual(len(supplied), 8)
        self.assertEqual([s['kind'] for s in supplied].count('law'), 4)
        self.assertEqual([s['kind'] for s in supplied].count('precedent'), 2)
        self.assertEqual([s['kind'] for s in supplied].count('dataset'), 2)

    def test_long_local_extraction_processes_every_block(self):
        blocks = [{'block_id': f'B{i}', 'page': 1, 'text': '확인할 계약 항목입니다. ' * 35} for i in range(40)]
        processed = []

        def model(schema, prompt, **kwargs):
            document = json.loads(prompt.split('\n문서:')[1])
            processed.extend(b['block_id'] for b in document)
            return {'terms': []}, 'qwen-test'

        with patch('backend.extraction.generate', side_effect=model):
            ollama_extract(blocks, 'employment')
        self.assertEqual(processed, [b['block_id'] for b in blocks])


if __name__ == '__main__':
    unittest.main()
