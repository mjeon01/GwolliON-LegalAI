"""Isolated synthetic browser server: OpenAI, local OCR and local models are all mocked."""
import json
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


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='gwollion-browser-') as folder, \
         patch('backend.app.SAMPLES_DIR', ROOT/'tests/fixtures/samples'), \
         patch('backend.openai_client.settings', return_value=('browser-test-only', 'browser-mock')), \
         patch('backend.openai_client.generate', side_effect=model), \
         patch('backend.translation.generate', side_effect=model), \
         patch('backend.auto_translation.generate', side_effect=auto_model), \
         patch('backend.chat.generate', side_effect=model), \
         patch('backend.chat_translation.generate', side_effect=model), \
         patch('backend.chat.generate_stream', side_effect=model), \
         patch('backend.reading.recognize', return_value=(ROOT/'tests/fixtures/samples/sale-risk.txt').read_text()):
        uvicorn.run(create_app(Path(folder)/'browser.sqlite3'), host='127.0.0.1', port=8021, log_level='warning')
