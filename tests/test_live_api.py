import json
import pytest
from fastapi.testclient import TestClient
from app import app
from ai import gateway

SAMPLE = 'Need 304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24. Also alum sheet .063 5052 4x10 qty 15.'
H = {'X-API-Key':'rudco-demo-key'}

FAKE_GATEWAY_JSON = json.dumps({
    'lines': [
      {'raw_text': '304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24',
       'material':'stainless_steel', 'form':'sheet','grade':'304','quantity':24,
       'evidence':{'grade':'304','quantity':'24','material':'SS','form':'sheet'}},
      {'raw_text': 'alum sheet .063 5052 4x10 qty 15',
       'material':'aluminum','form':'sheet','grade':'5052','quantity':15,
       'evidence':{'grade':'5052','quantity':'15','material':'alum','form':'sheet'}}
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
    def remote_fake(messages,*,max_tokens=2200, model=None, timeout_seconds=None):
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
    # Both lines resolve to real SKUs from the 99-item RudCo catalog.
    assert a['match']['sku']=='SS304-4-16G-4896-US'
    assert a['pricing']['unit_price_usd']>0
    assert b['match']['sku']=='AL5052-SH-063-48120-US'
    assert b['pricing']['unit_price_usd']>0
    rid=data['rfq_id']
    # Quote cannot be drafted until a human approves every resolved line.
    assert client.post(f'/v1/rfqs/{rid}/quotes/draft',headers=H).status_code==409
    for lid in ('line_001','line_002'):
        assert client.post(f'/v1/rfqs/{rid}/lines/{lid}/approve',headers=H).status_code==200
    quote=client.post(f'/v1/rfqs/{rid}/quotes/draft',headers=H)
    assert quote.status_code==201,quote.text
    body=quote.json()
    expected_total=round(sum(l['line_total_usd'] for l in body['lines']),2)
    assert body['grand_total_usd']==expected_total
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


FAKE_IMAGE_GATEWAY_JSON = json.dumps({
    'source_text': SAMPLE,
    'lines': json.loads(FAKE_GATEWAY_JSON)['lines'],
})


def test_image_upload_single_multimodal_extract(client, monkeypatch):
    calls = []

    def remote_fake(messages, *, max_tokens=2200, model=None, timeout_seconds=None):
        calls.append({'messages': messages, 'model': model, 'max_tokens': max_tokens,
                      'timeout_seconds': timeout_seconds})
        user = messages[-1]['content']
        assert isinstance(user, list)
        assert any(part.get('type') == 'image_url' for part in user)
        assert model == 'openai/gpt-4o-mini'
        assert timeout_seconds == 25
        return FAKE_IMAGE_GATEWAY_JSON, 'openai/gpt-4o-mini', 1800

    monkeypatch.setenv('NICRRON_VISION_MODEL', 'openai/gpt-4o-mini')
    monkeypatch.setenv('NICRRON_VISION_TIMEOUT_SECONDS', '25')
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
    assert data['lines'][0]['match'] and data['lines'][0]['match']['sku']
    assert data['gateway']['vision_model'] == 'openai/gpt-4o-mini'
    assert data['gateway']['latency_ms'] == 1800
    assert data['gateway']['source'] == 'image_multimodal'
    assert len(calls) == 1


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


# Two RFQ lines that resolve cleanly against the RudCo catalog; raw_text must be
# an exact substring of the uploaded document for source-grounded extraction.
UPLOAD_FAKE_JSON = json.dumps({
    'lines': [
        {'raw_text': '304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24',
         'material': 'stainless_steel', 'form': 'sheet', 'grade': '304', 'quantity': 24,
         'evidence': {'grade': '304', 'quantity': '24', 'material': 'SS', 'form': 'sheet'}},
        {'raw_text': 'alum sheet .063 5052 4x10 qty 15',
         'material': 'aluminum', 'form': 'sheet', 'grade': '5052', 'quantity': 15,
         'evidence': {'grade': '5052', 'quantity': '15', 'material': 'alum', 'form': 'sheet'}},
    ]
})

EML_BYTES = (
    b'From: Dana Whitfield <dana@bowerymillwork.example>\r\n'
    b'To: quotes@gowanusmetal.example\r\n'
    b'Subject: RFQ - hotel lobby pkg\r\n'
    b'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
    b'Hi team, please price:\r\n'
    b'- 304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24\r\n'
    b'- alum sheet .063 5052 4x10 qty 15\r\n'
    b'Mill certs required on all stainless.\r\n'
)

CSV_BYTES = (
    b'description\r\n'
    b'"304 SS sheet 16ga 4x8, #4 finish w/ PVC, qty 24"\r\n'
    b'"alum sheet .063 5052 4x10 qty 15"\r\n'
)


def test_eml_upload_queries_agent_and_matches_catalog(client, monkeypatch):
    calls = []

    def remote_fake(messages, *, max_tokens=2200, model=None):
        calls.append(messages[-1]['content'])
        return UPLOAD_FAKE_JSON, 'nicrron/auto', 123

    monkeypatch.setattr(gateway, '_completion', remote_fake)
    r = client.post(
        '/v1/rfqs/upload',
        headers=H,
        data={'buyer_id': 'ACME', 'buyer_email': 'dana@example.com'},
        files={'file': ('rfq.eml', EML_BYTES, 'message/rfc822')},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data['parser_mode'] == 'nicrron_live'
    assert data['line_count'] == 2
    # The agent was queried once with the parsed file text as the user message.
    assert len(calls) == 1
    assert '304 SS sheet 16ga 4x8' in calls[0]
    skus = {ln['match']['sku'] for ln in data['lines']}
    assert skus == {'SS304-4-16G-4896-US', 'AL5052-SH-063-48120-US'}


def test_csv_upload_queries_agent(client, monkeypatch):
    monkeypatch.setattr(gateway, '_completion',
                        lambda messages, *, max_tokens=2200, model=None: (UPLOAD_FAKE_JSON, 'nicrron/auto', 99))
    r = client.post(
        '/v1/rfqs/upload',
        headers=H,
        data={'buyer_id': 'ACME'},
        files={'file': ('rfq.csv', CSV_BYTES, 'text/csv')},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data['line_count'] == 2


def test_upload_missing_api_key_rejected(client):
    r = client.post(
        '/v1/rfqs/upload',
        data={'buyer_id': 'ACME'},
        files={'file': ('rfq.eml', EML_BYTES, 'message/rfc822')},
    )
    assert r.status_code == 401

