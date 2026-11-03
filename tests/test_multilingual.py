"""New cloud paths are mocked; no API keys, documents or pictures leave these tests."""
import base64
from io import BytesIO
import json
import logging
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import fitz
import httpx
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from backend.app import create_app
from backend import openai_client
from backend.analysis import extract, evaluate
from backend.reading import read_documents, sanitized_image, image_url, ReadingError
from backend.review import openai_review
from backend.schemas import AnalyzeRequest, ReadingInfo
from backend.translation import translated_fields, content_hash
from backend.store import Store, StaleRevision

ROOT = Path(__file__).resolve().parents[1]


def picture(size=(80, 120), exif=False):
    image = Image.new('RGB', size, 'white')
    stream = BytesIO()
    metadata = Image.Exif()
    if exif:
        metadata[274] = 6
        metadata[315] = 'private metadata'
    image.save(stream, format='JPEG', exif=metadata)
    return stream.getvalue()


def fake_translation(schema, prompt, **kwargs):
    if 'equivalent' in schema['properties']:
        return {'equivalent': True, 'errors': []}, 'mock'
    supplied = json.loads(prompt.split('\n', 1)[1])
    return {k: '译文 ' + v['text'] for k, v in supplied.items()}, 'mock'


def result_fixture():
    request = AnalyzeRequest(text=(ROOT/'tests/fixtures/samples/sale-risk.txt').read_text(), contract_type='sale', context={'document_complete':True})
    blocks, terms, extraction = extract(request)
    return evaluate(request, blocks, terms, extraction, 'fixture', 1)


class ResponsesTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch('backend.openai_client.settings', return_value=('private-test-key', 'gpt-5.4-mini'))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.schema = {'type':'object','properties':{'ok':{'type':'boolean'}}}

    def response(self, payload):
        return httpx.Response(200, json={'status':'completed','usage':{'input_tokens':10,'output_tokens':4},'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(payload)}]}]})

    def test_stateless_strict_schema_and_safe_metrics(self):
        with patch('httpx.Client.post',return_value=self.response({'ok':True})) as post, self.assertLogs('backend.openai_client',logging.INFO) as logs:
            data, model = openai_client.generate(self.schema, 'private-document', images=['data:image/jpeg;base64,private-image'])
        payload = post.call_args.kwargs['json']
        self.assertIs(payload['store'], False)
        self.assertEqual(payload['model'],'gpt-5.4-mini')
        self.assertFalse(payload['text']['format']['schema']['additionalProperties'])
        self.assertEqual(payload['input'][0]['content'][1]['type'],'input_image')
        for secret in ('private-test-key','private-document','private-image'):
            self.assertNotIn(secret, '\n'.join(logs.output))

    def test_missing_key_and_provider_failures_are_explicit(self):
        with patch('backend.openai_client.settings',return_value=('', 'gpt-5.4-mini')):
            with self.assertRaises(openai_client.OpenAIError) as e: openai_client.generate(self.schema,'x')
            self.assertEqual(e.exception.code,'openai_not_configured')
        for status, code in [(401,'openai_auth'),(403,'openai_auth'),(429,'openai_rate_limit'),(500,'openai_unavailable')]:
            with self.subTest(status=status), patch('httpx.Client.post',return_value=httpx.Response(status,json={'secret':'not displayed'})):
                with self.assertRaises(openai_client.OpenAIError) as e: openai_client.generate(self.schema,'x')
                self.assertEqual(e.exception.code,code)
                self.assertNotIn('secret',str(e.exception))
        with patch('httpx.Client.post',side_effect=httpx.ReadTimeout('private')):
            with self.assertRaises(openai_client.OpenAIError) as e: openai_client.generate(self.schema,'x')
            self.assertEqual(e.exception.code,'openai_timeout')

    def test_invalid_incomplete_refused_outputs_are_not_success(self):
        responses = [self.response({'ok':'wrong'}), self.response({'extra':True}),
                     httpx.Response(200,json={'status':'incomplete'}),
                     httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'refusal','refusal':'x'}]}]}),
                     httpx.Response(200,text='not JSON')]
        for response in responses:
            with patch('httpx.Client.post',return_value=response), self.assertRaises(openai_client.OpenAIError):
                openai_client.generate(self.schema,'x')


class PhotoTests(unittest.TestCase):
    def test_orientation_rotation_and_metadata_are_sanitized(self):
        image = sanitized_image(picture(exif=True),90)
        self.assertEqual(image.size,(80,120))
        with Image.open(BytesIO(base64.b64decode(image_url(image).split(',')[1]))) as decoded:
            self.assertFalse(decoded.getexif())
            self.assertNotIn('private',str(decoded.info))

    @patch('backend.openai_client.require_key',return_value=('mock','model'))
    def test_page_order_warnings_and_failure_are_not_hidden(self, _):
        with patch('backend.reading.vision_page',side_effect=[{'text':'첫째 계약 조항: 임차인은 모든 수리비를 부담한다.','legible':True,'warnings':[]},openai_client.OpenAIError('openai_timeout','재시도'),{'text':'마지막 계약 조항: 임대인은 보증금을 반환한다.','legible':False,'warnings':['흐림']} ]):
            result=read_documents([(picture(),'.jpg')]*3,'openai',[90,0,270])
        self.assertEqual([p['page'] for p in result['reading']['pages']],[1,2,3])
        self.assertEqual([p['status'] for p in result['reading']['pages']],['ok','failed','needs_review'])
        self.assertEqual(result['text'].split('\f')[1],'')
        self.assertEqual(len(result['page_previews']),3)
        with self.assertRaises(ValidationError): AnalyzeRequest(text=result['text'],reading=result['reading'])
        for page in result['reading']['pages']:
            page.update(confirmed=True,status='ok')
        result['reading']['pages'][1]['text']='수동으로 대조하여 확인한 두 번째 페이지 원문입니다.'
        text='\f'.join(p['text'] for p in result['reading']['pages'])
        self.assertEqual(len(AnalyzeRequest(text=text,reading=result['reading']).reading.pages),3)
        with self.assertRaises(ValidationError): AnalyzeRequest(text=text+'changed',reading=result['reading'])

    def test_limits_are_validated_before_cloud_call(self):
        bad=[([(picture(),'.jpg')]*6,[]),([(b'x'*(5*1024*1024+1),'.jpg')],[]),([(picture(),'.heic')],[]),([(b'invalid','.png')],[]),([(picture(),'.jpg')],[45]),([(b'text','.txt'),(picture(),'.jpg')],[])]
        with patch('backend.reading.vision_page') as call:
            for files, rotations in bad:
                with self.assertRaises(ReadingError): read_documents(files,'openai',rotations)
            call.assert_not_called()
        with fitz.open() as document:
            for _ in range(6): document.new_page()
            raw=document.tobytes()
        with patch('backend.reading.vision_page') as call, self.assertRaises(ReadingError):
            read_documents([(raw,'.pdf')],'openai')
        call.assert_not_called()

    def test_text_pdf_needs_no_key_and_keeps_all_pages(self):
        with patch('backend.openai_client.require_key',side_effect=AssertionError('must be local')):
            result=read_documents([((ROOT/'tests/fixtures/samples/pdf/sale-basic.pdf').read_bytes(),'.pdf')],'openai')
        self.assertEqual(result['reading']['methods'],['pdf_text'])
        self.assertFalse(result['reading']['ocr_used'])


class GroundingAndTranslationTests(unittest.TestCase):
    def test_chunking_covers_long_document_and_exposes_failures(self):
        blocks=[{'block_id':f'B{i:04}','page':i//4+1,'text':'조항 원문입니다. '*100} for i in range(30)]
        def reviewed(chunk,*args,**kwargs):
            if chunk[0]['block_id']=='B0000': raise openai_client.OpenAIError('openai_timeout','timeout')
            return {'findings':[],'rejected_candidates':0,'complete':True}
        with patch('backend.openai_client.require_key',return_value=('mock','model')), patch('backend.review._semantic_review',side_effect=reviewed):
            result=openai_review(blocks,'sale','buyer',{})
        self.assertFalse(result['complete'])
        self.assertEqual({i for v in result['ranges'] for i in v['block_ids']},{b['block_id'] for b in blocks})
        self.assertIn('failed',{v['status'] for v in result['ranges']})

    def test_integrity_preserves_amount_date_quote_and_roles(self):
        text='임대인은 2026-11-03에 보증금 1,000만원을 반환한다. “원문 인용 30일”'
        with patch('backend.translation.generate',side_effect=fake_translation):
            result=translated_fields({'a':text},'es')['a']
        for value in ['2026-11-03','1,000만원','“원문 인용 30일”','임대인 (arrendador)']:
            self.assertIn(value,result)
        def changed(schema,prompt,**kwargs):
            data,model=fake_translation(schema,prompt,**kwargs)
            if 'equivalent' not in data: data={k:v.replace('⟪G0001⟫','9000') for k,v in data.items()}
            return data,model
        with patch('backend.translation.generate',side_effect=changed),self.assertRaises(openai_client.OpenAIError):
            translated_fields({'a':text},'es')

    def test_long_translation_does_not_split_quotes_amounts_or_drop_tail(self):
        text = '계약 설명입니다. ' * 280 + '“' + '법령 인용 30일 ' * 400 + '”' + ' 매수인은 1억5000만원을 지급한다. 끝.'
        def echo(schema, prompt, **kwargs):
            if 'equivalent' in schema['properties']:
                return {'equivalent':True,'errors':[]}, 'mock'
            data=json.loads(prompt.split('\n',1)[1])
            return {k:v['text'] for k,v in data.items()}, 'mock'
        with patch('backend.translation.generate',side_effect=echo):
            result=translated_fields({'long':text},'es')['long']
        self.assertEqual(result,text.replace('매수인','매수인 (comprador)'))

    def test_role_meaning_mismatch_is_rejected(self):
        def flipped(schema,prompt,**kwargs):
            if 'equivalent' in schema['properties']: return {'equivalent':False,'errors':['payer reversed']},'mock'
            return fake_translation(schema,prompt,**kwargs)
        with patch('backend.translation.generate',side_effect=flipped),self.assertRaises(openai_client.OpenAIError):
            translated_fields({'a':'임대인이 보증금을 반환한다.'},'zh')

    def test_ten_samples_risk_types_and_original_binding(self):
        samples=json.loads((ROOT/'tests/fixtures/samples/manifest.json').read_text())
        self.assertEqual(len(samples),10)
        expected={'employment-basic':[], 'employment-missing':[], 'employment-conflict':[], 'employment-attention':['penalty','included_allowance'], 'lease-basic':[], 'lease-return':['deposit_return']}
        for sample in samples:
            with self.subTest(sample=sample['id']):
                q=AnalyzeRequest(text=(ROOT/'tests/fixtures/samples'/f"{sample['id']}.txt").read_text(),contract_type=sample['contract_type'],context=sample['context'])
                b,terms,x=extract(q);r=evaluate(q,b,terms,x,'fixture',1)
                self.assertEqual({f['issue_type'] for f in r['review']['findings']},set(sample['expected'].get('finding_types',expected.get(sample['id'],[]))))
                index={b['block_id']:b for b in r['blocks']}
                for f in r['review']['findings']:
                    for e in f['evidence']: self.assertEqual(index[e['block_id']]['text'][e['start']:e['end']],e['quote'])
                self.assertEqual(set(sample['translations']),{'zh','es'})


class ExtendedAPITests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.client=TestClient(create_app(Path(self.folder.name)/'test.sqlite3')); self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        response=self.client.post('/api/analyses',json={'text':(ROOT/'tests/fixtures/samples/sale-risk.txt').read_text(),'contract_type':'sale'})
        self.id=response.json()['analysis_id']
        for _ in range(100):
            self.result=self.client.get(f'/api/analyses/{self.id}').json()
            if self.result['status'] not in {'queued','running'}: break
            time.sleep(.02)
        self.base=f'/api/analyses/{self.id}'

    def test_key_missing_preserves_existing_history_and_returns_code(self):
        before=self.client.get('/api/analyses').json()
        with patch('backend.openai_client.settings',return_value=('', 'gpt-5.4-mini')):
            response=self.client.post('/api/analyses',json={'text':'계약서 원문은 보존되어야 합니다. 계약기간과 지급 조건을 확인합니다.','engine':'openai'})
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json()['code'],'openai_not_configured')
        self.assertEqual(self.client.get('/api/analyses').json(),before)

    def test_translation_cache_is_scoped_by_revision_language_and_text(self):
        with patch('backend.app.translate_document',side_effect=lambda text,lang: {'text':lang+text,'original_text':text}) as translate:
            for text,lang in [('원문1','zh'),('원문1','zh'),('원문2','zh'),('원문1','es')]:
                self.assertEqual(self.client.post(self.base+'/document-translations',json={'analysis_revision':1,'language':lang,'text':text}).status_code,200)
            self.assertEqual(translate.call_count,3)
            self.client.post(self.base+'/answers',json={'analysis_revision':1,'context':{'document_complete':True}})
            self.assertEqual(self.client.post(self.base+'/document-translations',json={'analysis_revision':1,'language':'zh','text':'원문1'}).status_code,409)
            self.client.post(self.base+'/document-translations',json={'analysis_revision':2,'language':'zh','text':'원문1'})
            self.assertEqual(translate.call_count,4)

    def test_chat_keeps_original_interpretation_and_revision(self):
        answer={'text':'Respuesta','text_ko':'한국어 답변','evidence':[],'source_ids':[],'method':'openai'}
        with patch('backend.app.multilingual_answer',return_value=(answer,'누가 대금을 지급하나요?')):
            response=self.client.post(self.base+'/chat',json={'analysis_revision':1,'question':'¿Quién paga?','language':'es','engine':'openai'})
        self.assertEqual(response.status_code,200)
        turn=self.client.get(self.base+'/chat?analysis_revision=1').json()['turns'][0]
        self.assertEqual(turn['question'],'¿Quién paga?')
        self.assertEqual(turn['question_ko'],'누가 대금을 지급하나요?')
        with patch('backend.app.multilingual_answer',side_effect=openai_client.OpenAIError('translation_meaning','retry',422)):
            failed=self.client.post(self.base+'/chat',json={'analysis_revision':1,'question':'再解释一下','language':'zh','engine':'openai'})
        self.assertEqual(failed.status_code,422)
        self.assertEqual(len(self.client.get(self.base+'/chat?analysis_revision=1').json()['turns']),1)

    def test_foreign_incident_needs_confirmed_korean_and_edited_text_is_translatable(self):
        body={'analysis_revision':1,'kind':'lawyer_request','language':'es','incident':{'summary':'매도인에게 서류 제공일을 요청했지만 아직 답변을 받지 못했습니다.'},'incident_original':{'summary':'No he recibido respuesta.'}}
        self.assertEqual(self.client.post(self.base+'/drafts',json=body).status_code,422)
        response=self.client.post(self.base+'/drafts',json={**body,'incident_confirmed':True})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['incident_original'],{**{k:'' for k in ('writer','counterparty','date','place','loss','evidence','desired_outcome')},'summary':'No he recibido respuesta.'})
        self.assertIn(body['incident']['summary'],response.json()['draft_text'])

    def test_late_translation_cannot_restore_deleted_analysis(self):
        def deleted(text,lang):
            self.client.delete(self.base)
            return {'text':'late'}
        with patch('backend.app.translate_document',side_effect=deleted):
            response=self.client.post(self.base+'/document-translations',json={'analysis_revision':1,'language':'es','text':'문서'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get(self.base).status_code,404)


if __name__ == '__main__': unittest.main()
