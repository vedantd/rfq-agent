import json
import pytest
from fastapi.testclient import TestClient
from app import app
from ai import gateway

SAMPLE = 'Need 20 sheets 304 SS 16ga 4x8, mill certs required. Also 10 sheets stainless 1/8 inch.'
H = {'X-API-Key':'rudco-demo-key'}

FAKE_GATEWAY_JSON = json.dumps({
    'lines': [
      {'raw_text': '20 sheets 304 SS 16ga 4x8, mill certs required',
       'material':'stainless_steel', 'form':'sheet','grade':'304','quantity':20,
       'evidence':{'grade':'304','quantity':'20','material':'SS','form':'sheets'}},
      {'raw_text': '10 sheets stainless 1/8 inch',
       'material':'stainless_steel','form':'sheet','grade':None,'quantity':10,
       'evidence':{'quantity':'10','material':'stainless','form':'sheets'}}
    ]
})

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RFQ_DB_PATH',str(tmp_path / 'test.sqlite3'))
    monkeypatch.setenv('NICRRON_API_KEY', 'sk-test-not-used-for-network')
    with TestClient(app) as c:
        yield c


def test_missing_key_does_not_fake_success(client, monkeypatch):
    monkeypatch.delenv('NICRRON_API_KEY')
    r=client.post('/v1/rfqs', headers=H, json={'buyer_id':'B','text':SAMPLE})
    assert r.status_code==503
    assert 'NICRRON_API_KEY' in r.json()['detail']
    r=client.post('/v1/gateway/test',headers=H)
    assert r.status_code==503


def test_live_extraction_quote_flow(client, monkeypatch):
    calls=[]
    def remote_fake(messages,*,max_tokens=2200):
        # Only in tests: production always uses _completion to POST to Nicrron.
        calls.append(messages)
        return FAKE_GATEWAY_JSON,'nicrron/auto',321
    monkeypatch.setattr(gateway,'_completion',remote_fake)
    r=client.post('/v1/rfqs',headers=H,json={'buyer_id':'ACME','text':SAMPLE})
    assert r.status_code==201, r.text
    data=r.json()
    assert data['parser_mode']=='nicrron_live'
    assert data['gateway']['model']=='nicrron/auto'
    assert len(calls)==1
    assert data['line_count']==2
    a,b=data['lines']
    assert a['match']['sku']=='SS-304-16GA-4896'
    assert a['pricing']['unit_price_usd']==245.0
    assert b['status']=='needs_clarification'
    assert b['pricing'] is None
    rid=data['rfq_id']
    assert client.post(f'/v1/rfqs/{rid}/quotes/draft',headers=H).status_code==409
    assert client.post(f'/v1/rfqs/{rid}/lines/line_002/approve',headers=H).status_code==409
    x=client.patch(f'/v1/rfqs/{rid}/lines/line_002',headers=H,json={'grade':'316','width_in':48,'length_in':96})
    assert x.status_code==200, x.text
    assert x.json()['status']=='ready_for_approval'
    assert x.json()['match']['sku']=='SS-316-125-4896'
    for id in ('line_001','line_002'):
        assert client.post(f'/v1/rfqs/{rid}/lines/{id}/approve',headers=H).status_code==200
    quote=client.post(f'/v1/rfqs/{rid}/quotes/draft',headers=H)
    assert quote.status_code==201,quote.text
    assert quote.json()['ready_to_send'] is False
    assert quote.json()['grand_total_usd']==9922.50
    assert len(calls)==1, 'Clarifications use deterministic re-validation; no further model request is necessary'


def test_invalid_llm_output_returns_502_not_fake_rules(client,monkeypatch):
    monkeypatch.setattr(gateway,'_completion', lambda *a,**k: ('nonsense','nicrron/auto',11))
    response=client.post('/v1/rfqs', headers=H, json={'buyer_id':'B','text':SAMPLE})
    assert response.status_code==502
    assert 'valid JSON' in response.json()['detail']


def test_real_http_path_receives_model_baseurl_and_auth(monkeypatch):
    records={}
    class FakeHttpResponse:
        status_code=200
        def json(self): return {'choices':[{'message':{'content':'OK'}}], 'model':'nicrron/auto'}
    class FakeHttpClient:
        def __init__(self,**kwargs): records['client_kwargs']=kwargs
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def post(self,url,**kwargs):
            records['url']=url
            records['headers']=kwargs['headers']
            records['payload']=kwargs['json']
            return FakeHttpResponse()
    monkeypatch.setenv('NICRRON_API_KEY','abc')
    monkeypatch.setenv('NICRRON_MODEL','nicrron/auto')
    monkeypatch.setattr(gateway.httpx,'Client',FakeHttpClient)
    out=gateway.test_connection()
    assert out['connected'] is True
    assert records['headers']['Authorization']=='Bearer abc'
    assert records['url']=='https://api.nicrron.ai/v1/chat/completions'
    assert records['payload']['model']=='nicrron/auto'
    assert records['payload']['messages'][0]['role']=='system'


def test_frontend_is_single_file(client):
    r=client.get('/')
    assert r.status_code==200
    assert '<html' in r.text
    assert 'Process with real AI gateway' in r.text
    assert '/v1/rfqs' in r.text
    assert '.png' in r.text


# Minimal valid 1×1 PNG (magic bytes only matter for sniffing; vision is stubbed).
TINY_PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082'
)


def test_image_upload_uses_vision_then_extraction(client, monkeypatch):
    calls = []

    def remote_fake(messages, *, max_tokens=2200, model=None):
        calls.append({'messages': messages, 'model': model, 'max_tokens': max_tokens})
        user = messages[-1]['content']
        if isinstance(user, list):
            assert any(part.get('type') == 'image_url' for part in user)
            assert model == 'anthropic/claude-haiku-4-5' or model is None or 'haiku' in (model or '')
            return SAMPLE, 'anthropic/claude-haiku-4-5', 111
        return FAKE_GATEWAY_JSON, 'nicrron/auto', 222

    monkeypatch.setenv('NICRRON_VISION_MODEL', 'anthropic/claude-haiku-4-5')
    monkeypatch.setattr(gateway, '_completion', remote_fake)
    r = client.post(
        '/v1/rfqs/upload',
        headers=H,
        data={'buyer_id': 'ACME'},
        files={'file': ('sample-rfq.png', TINY_PNG, 'image/png')},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data['parser_mode'] == 'nicrron_live'
    assert data['line_count'] == 2
    assert data['lines'][0]['match']['sku'] == 'SS-304-16GA-4896'
    assert data['gateway']['vision_model'] == 'anthropic/claude-haiku-4-5'
    assert data['gateway']['vision_latency_ms'] == 111
    assert data['gateway']['extract_latency_ms'] == 222
    assert data['gateway']['latency_ms'] == 333
    assert data['gateway']['source'] == 'image_transcript'
    assert len(calls) == 2
    assert isinstance(calls[0]['messages'][-1]['content'], list)
    assert isinstance(calls[1]['messages'][-1]['content'], str)


def test_non_image_extension_still_rejected(client):
    r = client.post(
        '/v1/rfqs/upload',
        headers=H,
        data={'buyer_id': 'ACME'},
        files={'file': ('notes.docx', b'not-an-image', 'application/octet-stream')},
    )
    assert r.status_code == 415
    assert '.png' in r.json()['detail']


def test_image_extension_with_bad_bytes_rejected(client):
    r = client.post(
        '/v1/rfqs/upload',
        headers=H,
        data={'buyer_id': 'ACME'},
        files={'file': ('fake.png', b'not-really-png', 'image/png')},
    )
    assert r.status_code == 415
