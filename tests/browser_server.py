"""Isolated synthetic browser server: OpenAI, local OCR and local models are all mocked."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from backend.app import create_app
from backend.knowledge import ROOT


def model(schema, prompt, **kwargs):
    if kwargs.get('on_progress'):
        kwargs['on_progress']('generating')
        time.sleep(0.2)
    props = schema['properties']
    if 'terms' in props:
        return {'terms': []}, 'browser-mock'
    if 'legible' in props:
        return {'text': (ROOT/'tests/fixtures/samples/sale-risk.txt').read_text(), 'legible': True, 'warnings': []}, 'browser-mock'
    if 'complete' in props:
        return {'complete': True, 'findings': []}, 'browser-mock'
    if 'equivalent' in props:
        return {'equivalent': True, 'errors': []}, 'browser-mock'
    if 'answer' in props:
        block = props['evidence_ids']['items']['enum'][0]
        return {'answer':'지급 시점과 서류 제공 조건을 서면으로 확인하고 상대방과 협의하세요.', 'evidence_ids':[block], 'source_ids':[], 'citations':[]}, 'browser-mock'
    fields = json.loads(prompt.split('\n', 1)[1])
    translated = {}
    for key, value in fields.items():
        text = value['text'] if isinstance(value, dict) else value
        if ('into Korean.' in prompt or '韩语 (Korean)' in prompt):
            # Deterministic test interpretation; integrity tokens are preserved.
            text = '상대방에게 서류 제공일을 요청했지만 답변을 받지 못했습니다. ' + ' '.join(re.findall(r'⟪G\d{4}⟫', text)) if text else ''
        tokens = ' '.join(re.findall(r'⟪G\d{4}⟫', text))
        translated[key] = ('请先书面确认文件提供日期和付款时间，并与对方协商。 ' + tokens if 'Simplified Chinese' in prompt else 'Confirme por escrito la entrega de documentos y la fecha de pago con la otra parte. ' + tokens if 'Spanish' in prompt else text)
    return translated, 'browser-mock'


def auto_model(schema, prompt, **kwargs):
    return json.loads(prompt[prompt.index('{"T'):]), 'browser-mock'


def agent_call(payload, purpose=None):
    """Scripted Responses API for the agent: record the wage, draft the request, then answer with a question."""
    items = payload['input']
    message = next(json.loads(i['content'].split('\n', 1)[1])['message'] for i in reversed(items)
                   if isinstance(i, dict) and i.get('role') == 'user' and i['content'].startswith('USER MESSAGE'))
    if payload['tool_choice'] != 'none' and not any(isinstance(i, dict) and i.get('type') == 'function_call_output' for i in items):
        calls = [('draft_contract_request', {})]
        if '9000' in message:
            calls.insert(0, ('record_fact', {'key': 'hourly_wage', 'value': '9000원', 'user_quote': '시급 9000원'}))
        return {'status': 'completed', 'output': [{'type': 'function_call', 'name': n, 'arguments': json.dumps(a, ensure_ascii=False), 'call_id': f'c{i}'}
                                                  for i, (n, a) in enumerate(calls)]}, 'browser-mock'
    answer = {'answer': '서면 근로계약서를 요청할 수 있는지 확인이 필요합니다. 요청서를 준비했습니다.', 'answer_ko': '서면 근로계약서를 요청할 수 있는지 확인이 필요합니다. 요청서를 준비했습니다.',
              'evidence_block_ids': [], 'citations': [], 'next_action': 'draft_request',
              'ask': {'question': '일주일에 15시간 이상 일하나요?', 'question_ko': '일주일에 15시간 이상 일하나요?', 'options': ['예', '아니오']}}
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer, ensure_ascii=False)}]}]}, 'browser-mock'


if __name__ == '__main__':
    # --agent: the agent is enabled with a scripted model on port 8023; otherwise local mode on 8021.
    agent = '--agent' in sys.argv
    os.environ['GWOLLION_CLAUSE_MODEL'] = 'off'  # Browser tests do not depend on a locally trained model.
    patches = [patch('backend.app.SAMPLES_DIR', ROOT/'tests/fixtures/samples'),
               patch('backend.corpus.Corpus.search', return_value=[]),
               patch('backend.openai_client.settings', return_value=('browser-test-only', 'browser-mock')),
               patch('backend.openai_client.generate', side_effect=AssertionError('No paid model calls')),
               patch('backend.auto_translation.use_openai', return_value=False),
               patch('backend.translation.generate', side_effect=AssertionError('No paid translations')),
               patch('backend.auto_translation.generate', side_effect=auto_model),
               patch('backend.extraction.generate', side_effect=model),
               patch('backend.review.generate', side_effect=model),
               patch('backend.chat.generate', side_effect=model),
               patch('backend.chat_translation.generate', side_effect=model),
               patch('backend.chat.generate_stream', side_effect=model),
               patch('backend.reading.recognize', return_value=(ROOT/'tests/fixtures/samples/sale-risk.txt').read_text()),
               patch('backend.agent.runner.openai_client.call', side_effect=agent_call if agent else AssertionError('No paid agent calls'))]
    if agent:
        patches += [patch('backend.app.ai_provider', return_value='openai'), patch('backend.app.require_key')]
    with tempfile.TemporaryDirectory(prefix='gwollion-browser-') as folder, ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        uvicorn.run(create_app(Path(folder)/'browser.sqlite3'), host='127.0.0.1', port=8023 if agent else 8021, log_level='warning')
