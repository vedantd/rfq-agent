"""Root entrypoint so `uvicorn app:app` keeps working after the folder reorg."""
from api.app import app

__all__ = ["app"]
        lines, gateway_details = extract_live(body.text)
    except (GatewayConfigurationError, GatewayResponseError) as exc:
        raise gateway_error(exc) from exc
    parser_mode = 'nicrron_live'
    if not lines:
        raise HTTPException(422,'No recognizable material lines found; revise the RFQ text.')
    catalog=store.load_catalog(tid)
    lines=[engine.analyze_line(line,catalog) for line in lines]
    rfq={'id':rid,'tenant_id':tid,'buyer_id':body.buyer_id,'buyer_email':body.buyer_email,
         'source_type':body.source_type,'source_text':body.text,'parser_mode':parser_mode,
         'gateway':gateway_details,
         'lines':lines,'events':[event('rfq.received','RFQ ingested'),event('rfq.analyzed',f'{len(lines)} lines processed using {parser_mode}')],
         'created_at':now(),'idempotency_key':idem}
    store.save_rfq(rfq)
    return engine.summarize(rfq)


def require_rfq(tid,rid):
    rfq=store.get_rfq(tid,rid)
    if not rfq: raise HTTPException(404,'RFQ not found')
    return rfq

def require_line(rfq,lid):
    for ln in rfq['lines']:
        if ln['id']==lid: return ln
    raise HTTPException(404,'Line not found')

@app.get('/',response_class=HTMLResponse,include_in_schema=False)
def index():
    return (Path(__file__).parent / 'static' / 'index.html').read_text(encoding='utf-8')

@app.get('/health',tags=['Gateway'])
def health():
    return {'status':'ok','service':'rudco-quotepilot-live', 'gateway': config(),
            'note':'Configured does not mean connected; POST /v1/gateway/test performs a real call.'}

@app.post('/v1/gateway/test',tags=['Gateway'])
def test_gateway(_tid: str=Depends(tenant)):
    try:
        return test_connection()
    except (GatewayConfigurationError, GatewayResponseError) as exc:
        raise gateway_error(exc) from exc


@app.post('/v1/rfqs',status_code=201,tags=['RFQs'])
def ingest_rfq(body:RFQRequest,tid:str=Depends(tenant),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    return create_rfq(body,tid,idempotency_key)

@app.post('/v1/rfqs/upload',status_code=201,tags=['RFQs'])
async def ingest_upload(file:UploadFile=File(...),buyer_id:str=Form(...),buyer_email:str|None=Form(None),tid:str=Depends(tenant)):
    raw=await file.read(5_000_001)
    if len(raw)>5_000_000: raise HTTPException(413,'5MB limit for hackathon demo')
    filename=(file.filename or '').lower()
    try:
        if filename.endswith(('.txt','.eml')): text=raw.decode('utf-8')
        elif filename.endswith('.pdf'):
            import fitz
            doc=fitz.open(stream=raw,filetype='pdf')
            text='\n'.join(page.get_text() for page in doc)
        elif filename.endswith('.csv'):
            text='\n'.join(' '.join(row) for row in csv.reader(io.StringIO(raw.decode('utf-8'))))
        elif filename.endswith('.xlsx'):
            import openpyxl
            wb=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
            text='\n'.join(' '.join(str(v) for v in row if v is not None) for sheet in wb for row in sheet.values)
        else: raise HTTPException(415,'Supported formats: .txt .eml .pdf .csv .xlsx')
    except HTTPException: raise
    except Exception as ex: raise HTTPException(422,f'Could not parse uploaded file: {type(ex).__name__}')
    if not text.strip(): raise HTTPException(422,'No extractable text; scanned PDFs require OCR')
    source='pdf' if filename.endswith('.pdf') else 'csv' if filename.endswith('.csv') else 'xlsx' if filename.endswith('.xlsx') else 'email' if filename.endswith('.eml') else 'text'
    return create_rfq(RFQRequest(buyer_id=buyer_id,buyer_email=buyer_email,text=text,source_type=source),tid)

@app.get('/v1/rfqs/{rfq_id}',tags=['RFQs'])
def fetch_rfq(rfq_id:str,tid:str=Depends(tenant)):
    return engine.summarize(require_rfq(tid,rfq_id))

@app.post('/v1/rfqs/{rfq_id}/analyze',tags=['RFQs'])
def rerun_analysis(rfq_id:str,tid:str=Depends(tenant)):
    rfq=require_rfq(tid,rfq_id)
    rfq['lines']=[engine.analyze_line(x,store.load_catalog(tid)) for x in rfq['lines']]
    rfq['events'].append(event('rfq.reanalyzed','Catalog, pricing and compliance rechecked'))
    store.save_rfq(rfq)
    return engine.summarize(rfq)

@app.get('/v1/rfqs/{rfq_id}/clarifications',tags=['Clarifications'])
def pending_questions(rfq_id:str,tid:str=Depends(tenant)):
    rfq=require_rfq(tid,rfq_id)
    return {'rfq_id':rfq_id,'buyer_email':rfq.get('buyer_email'),
            'questions':[{'line_id':ln['id'],'source_text':ln['raw_text'],**q} for ln in rfq['lines'] for q in ln.get('clarifications',[])]}

@app.get('/v1/rfqs/{rfq_id}/clarifications/email-draft',tags=['Clarifications'])
def clarification_email(rfq_id:str,tid:str=Depends(tenant)):
    rfq=require_rfq(tid,rfq_id)
    questions=[f"- {ln['id']}: {q['question']}" for ln in rfq['lines'] for q in ln.get('clarifications',[])]
    return {'to':rfq.get('buyer_email'),'subject':f'Specification questions for {rfq_id}',
            'body':'Before we can finalize your quote, could you confirm:\n'+'\n'.join(questions) if questions else 'No clarifications needed.',
            'delivery_status':'draft_only_not_sent'}

@app.post('/v1/rfqs/{rfq_id}/clarifications/dispatch',tags=['Clarifications'])
def dispatch_clarifications(rfq_id:str,tid:str=Depends(tenant)):
    """Send a signed event to the tenant's configured integration webhook.
    The customer's platform can deliver the actual buyer email. Never pretend
    a draft was delivered, and never accept caller-supplied arbitrary URLs.
    """
    rfq=require_rfq(tid,rfq_id)
    questions=[{'line_id':ln['id'],'field':q['field'],'question':q['question']}
               for ln in rfq['lines'] for q in ln.get('clarifications',[])]
    if not questions: raise HTTPException(409,'There are no unresolved clarification questions')
    url=os.getenv('QUOTEPILOT_WEBHOOK_URL')
    secret=os.getenv('QUOTEPILOT_WEBHOOK_SECRET')
    if not (url and secret):
        raise HTTPException(412,'Configure QUOTEPILOT_WEBHOOK_URL and QUOTEPILOT_WEBHOOK_SECRET; questions are drafted but not dispatched')
    event_body={'id':f'evt_{uuid.uuid4().hex[:12]}','type':'rfq.clarification_required',
                'tenant_id':tid,'rfq_id':rfq_id,'buyer_email':rfq.get('buyer_email'),
                'questions':questions,'created_at':now()}
    payload=json.dumps(event_body,separators=(',',':')).encode()
    signature=hmac.new(secret.encode(),payload,hashlib.sha256).hexdigest()
    try:
        response=httpx.post(url,content=payload,headers={'Content-Type':'application/json',
                'X-QuotePilot-Signature':f'sha256={signature}'},timeout=4)
        response.raise_for_status()
    except httpx.HTTPError:
        rfq['events'].append(event('clarification.dispatch_failed','Webhook delivery failed; no delivery confirmation'))
        store.save_rfq(rfq)
        raise HTTPException(502,'Webhook delivery failed; retry after resolving connectivity')
    rfq['events'].append(event('clarification.dispatched',f'Integration webhook accepted {len(questions)} questions'))
    store.save_rfq(rfq)
    return {'webhook_status':'delivered_to_integration','buyer_email_status':'not_confirmed',
            'event_id':event_body['id'],'question_count':len(questions)}

@app.patch('/v1/rfqs/{rfq_id}/lines/{line_id}',tags=['Clarifications'])
def resolve_line(rfq_id:str,line_id:str,answers:ClarifyRequest,tid:str=Depends(tenant)):
    rfq=require_rfq(tid,rfq_id)
    old=require_line(rfq,line_id)
    updates=answers.model_dump(exclude_none=True)
    if not updates: raise HTTPException(422,'Supply at least one clarification field')
    new=dict(old)
    new.update(updates)
    if 'grade' in updates: new['grade']=new['grade'].upper()
    new['approval_status']='pending'
    analyzed=engine.analyze_line(new,store.load_catalog(tid))
    rfq['lines']=[analyzed if x['id']==line_id else x for x in rfq['lines']]
    rfq['events'].append(event('line.clarified',f'{line_id} revised fields: {sorted(updates)}'))
    store.save_rfq(rfq)
    return analyzed

@app.post('/v1/rfqs/{rfq_id}/lines/{line_id}/approve',tags=['Review & quotes'])
def approve_line(rfq_id:str,line_id:str,tid:str=Depends(tenant)):
    rfq=require_rfq(tid,rfq_id)
    ln=require_line(rfq,line_id)
    if ln['status'] not in ('ready_for_approval','approved'):
        raise HTTPException(409,{'message':'Line cannot be approved until every blocker is resolved','blockers':ln.get('blockers',[])})
    ln['status']='approved'; ln['approval_status']='approved'
    rfq['events'].append(event('line.approved',line_id))
    store.save_rfq(rfq)
    return ln

@app.get('/v1/catalog/items',tags=['Catalog'])
def list_catalog(tid:str=Depends(tenant)):
    return {'items':store.load_catalog(tid),'data_quality':'seeded demo unless replaced by tenant'}

@app.put('/v1/catalog/items/{sku}',tags=['Catalog'])
def put_catalog(sku:str,item:CatalogItem,tid:str=Depends(tenant)):
    if sku!=item.sku: raise HTTPException(422,'Path SKU and body SKU must match')
    store.upsert_catalog(tid,item.model_dump())
    return {'upserted':sku,'tenant_id':tid}

@app.get('/v1/catalog/search',tags=['Catalog'])
def search_catalog(material: str | None = None, grade: str | None = None, form: str | None = None, finish: str | None = None, tid: str = Depends(tenant)):
    """Search the database catalog by material, grade, form, and finish (case-insensitive)."""
    results = database.search_catalog(material=material, grade=grade, form=form, finish=finish)
    return {'results': results, 'count': len(results), 'filters': {'material': material, 'grade': grade, 'form': form, 'finish': finish}}

@app.get('/v1/catalog/benchmarks',tags=['Catalog'])
def get_benchmarks(tid: str = Depends(tenant)):
    """Retrieve all pricing benchmarks used for quote validation."""
    benchmarks = database.load_benchmarks()
    return {'benchmarks': list(benchmarks.values()), 'count': len(benchmarks)}

@app.get('/v1/catalog/compliance-rules',tags=['Catalog'])
def get_compliance_rules(tid: str = Depends(tenant)):
    """Retrieve all compliance rules used for procurement validation."""
    rules = database.load_compliance_rules()
    return {'rules': rules, 'count': len(rules), 'note': 'Use rule_id and trigger_in_rfq to determine applicability'}

@app.get('/v1/catalog/gauge-table',tags=['Catalog'])
def get_gauge_table(tid: str = Depends(tenant)):
    """Retrieve material-specific gauge-to-thickness conversion tables."""
    tables = database.load_gauge_tables()
    return {'gauge_tables': tables, 'materials': list(tables.get(list(tables.keys())[0], {}).keys()) if tables else [], 'note': 'Convert gauge notation to decimal thickness'}

@app.get('/v1/catalog/tube-gauge',tags=['Catalog'])
def get_tube_gauge(tid: str = Depends(tenant)):
    """Retrieve tube wall gauge-to-thickness conversion table (different from sheet gauge)."""
    tube_gauge = database.load_tube_gauge()
    return {'tube_gauge': tube_gauge, 'note': 'Tube wall gauge differs from sheet gauge; e.g., 16 ga tube wall = 0.065\", sheet = 0.0625\"'}

@app.get('/v1/catalog/synonyms',tags=['Catalog'])
def get_synonyms(tid: str = Depends(tenant)):
    """Retrieve term normalization mappings (e.g., 'SS' -> 'stainless steel')."""
    synonyms = database.load_synonyms()
    return {'synonyms': synonyms, 'count': len(synonyms), 'note': 'Applied during RFQ text normalization'}

@app.get('/v1/catalog/health',tags=['Catalog'])
def check_catalog_health(tid: str = Depends(tenant)):
    """Verify that all database tables are populated and accessible."""
    is_valid, message = database.verify_database()
    if not is_valid:
        raise HTTPException(503, {'status': 'degraded', 'error': message})
    return {'status': 'healthy', 'message': message}

@app.post('/v1/rfqs/{rfq_id}/quotes/draft',status_code=201,tags=['Review & quotes'])
def draft_quote(rfq_id:str,tid:str=Depends(tenant)):
    rfq=require_rfq(tid,rfq_id)
    unapproved=[ln['id'] for ln in rfq['lines'] if ln['status']!='approved']
    if unapproved: raise HTTPException(409,{'message':'Every line must be resolved and approved','line_ids':unapproved})
    qid=f'quo_{uuid.uuid4().hex[:12]}'
    demo=any(ln.get('pricing',{}).get('data_is_synthetic') for ln in rfq['lines'])
    q={'id':qid,'rfq_id':rfq_id,'tenant_id':tid,'buyer_id':rfq['buyer_id'],
       'buyer_email':rfq.get('buyer_email'), 'status':'demo_draft' if demo else 'ready_for_final_review',
       'ready_to_send':not demo,'currency':'USD','lines':[
          {'line_id':ln['id'],'sku':ln['match']['sku'],'description':ln['raw_text'],
           'quantity':ln['quantity'],'unit_price_usd':ln['pricing']['unit_price_usd'],
           'line_total_usd':ln['pricing']['line_total_usd'],'standard':ln['compliance']['supplier_standard'],
           'certifications':ln['required_certificates']} for ln in rfq['lines']],
       'grand_total_usd':engine.money(sum(ln['pricing']['line_total_usd'] for ln in rfq['lines'])),
       'warnings':['Uses synthetic demo supplier costs and market benchmark. Not for customer delivery.'] if demo else [],
       'created_at':now()}
    store.save_quote(q)
    rfq['events'].append(event('quote.drafted',qid))
    store.save_rfq(rfq)
    return q

@app.get('/v1/quotes/{quote_id}',tags=['Review & quotes'])
def fetch_quote(quote_id:str,tid:str=Depends(tenant)):
    result=store.get_quote(tid,quote_id)
    if not result: raise HTTPException(404,'Quote not found')
    return result
>>>>>>> Stashed changes
