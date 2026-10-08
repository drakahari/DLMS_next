"""Transactional earned credentials, explicit credits and curated manual AI text."""
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
import json
import re
import uuid
import warnings
from urllib.parse import urlsplit

from PIL import Image, ImageOps
from pypdf import PdfReader
from dlms.prompts import DEFAULT_CERTIFICATION_PROMPT, DEFAULT_PORTFOLIO_PROMPT
from dlms.services import certification_tracking as tracking

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
ID = re.compile(r'[0-9a-f]{32}')
TABLES = ('certifications','certification_cycles','certification_training','certification_allocations')


class Conflict(ValueError):
    pass


def identifier(value):
    if not isinstance(value,str) or not ID.fullmatch(value):
        raise ValueError('The record identifier is invalid.')
    return value


def text(value, label, maximum=1000, required=False):
    if not isinstance(value,str) or len(value)>maximum or '\x00' in value:
        raise ValueError(f'{label} is invalid or too long (limit {maximum} characters).')
    value=value.strip()
    if required and not value: raise ValueError(f'{label} is required.')
    return value


def day(value, label, required=False):
    value=text(value,label,10,required)
    if not value: return ''
    try:
        if date.fromisoformat(value).isoformat()!=value: raise ValueError()
    except ValueError as exc: raise ValueError(f'{label} must be a calendar date (YYYY-MM-DD).') from exc
    return value


def amount(value, label):
    try:
        raw=str(value)
        if len(raw)>100:raise ValueError()
        number=Decimal(raw)
        if not number.is_finite() or number<0 or number>100000 or number.as_tuple().exponent < -2: raise ValueError()
        return int(number) if number == number.to_integral() else float(number)
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError(f'{label} must be a nonnegative number with at most two decimal places.') from exc


def policy_url(value):
    value=text(value,'Official policy link',2000)
    p=urlsplit(value)
    if value and (p.scheme not in ('https','http') or not p.hostname or p.username or p.password or any(c.isspace() for c in value)):
        raise ValueError('Use a complete http:// or https:// policy link without credentials.')
    return value


def attachment_ref(value):
    return identifier(value) if value else ''


def normalize(kind, data):
    if not isinstance(data,dict): raise ValueError('Record fields are required.')
    if kind=='certification':
        if data.get('non_expiring','no') not in ('yes','no'):raise ValueError('Choose an expiration type.')
        result=dict(name=text(data.get('name',''),'Certification name',200,True),issuer=text(data.get('issuer',''),'Issuer',200,True),
                    earned=day(data.get('earned',''),'Earned date'),notes=text(data.get('notes',''),'Notes',5000),
                    badge=attachment_ref(data.get('badge','')), non_expiring=text(data.get('non_expiring','no'),'Expiration type',3))
        for key in ('version','standing'):
            if key in data:result[key]=text(data[key],key.title(),200)
        if result.get('standing','current') not in ('current','superseded'):raise ValueError('Choose current or superseded.')
        if 'relationships' in data:result['relationships']=normalize_relationships(data['relationships'])
        return result
    if kind=='cycle':
        result=dict(start=day(data.get('start',''),'Period start'),expiration=day(data.get('expiration',''),'Expiration date'),
                    renewal=day(data.get('renewal',''),'Renewal date'),renewed=day(data.get('renewed',''),'Renewal recorded date'),
                    required=amount(data.get('required') or 0,'Required credit'),unit=text(data.get('unit') or 'credits','Credit unit',60,True),
                    requirements=text(data.get('requirements',''),'Requirements / notes',5000),policy=policy_url(data.get('policy','')),
                    certificate=attachment_ref(data.get('certificate','')))
        if result['start'] and any(result[k] and result[k]<result['start'] for k in ('expiration','renewal')):
            raise ValueError('Expiration and renewal due dates cannot precede the period start. Correct the dates in Additional details.')
        if 'tracking' in data:result['tracking']=tracking.normalize(data['tracking'],text,day,amount)
        if 'renewal_source' in data:
            source=data['renewal_source']
            if not isinstance(source,dict):raise ValueError('Invalid renewal source.')
            result['renewal_source']={k:text(source.get(k,''),k,2000) for k in ('name','issuer','trigger','rule','recorded')}
        return result
    if kind=='training':
        result=dict(name=text(data.get('name',''),'Activity / course',200,True),provider=text(data.get('provider',''),'Provider',200),
                    completed=day(data.get('completed',''),'Completion date',True),hours=amount(data.get('hours',0),'Recorded hours'),
                    notes=text(data.get('notes',''),'Training notes',5000),certificate=attachment_ref(data.get('certificate','')))
        if 'course_url' in data:result['course_url']=policy_url(data['course_url'])
        if 'topics' in data:result['topics']=text(data['topics'],'Public course description / topics',3000)
        return result
    if kind=='allocation':
        result=dict(hours=amount(data.get('hours',0),'Hours associated with this cycle'),submitted=amount(data.get('submitted',0),'Submitted credit'),
                    accepted=amount(data.get('accepted',0),'Accepted credit'),notes=text(data.get('notes',''),'Allocation notes',2000))
        for key in ('proposed',):
            if key in data:result[key]=amount(data[key] or 0,'Proposed credit')
        for key in ('rationale','category'):
            if key in data:result[key]=text(data[key],key.title(),2000 if key=='rationale' else 100)
        if 'source' in data:result['source']=policy_url(data['source'])
        if 'reporting_date' in data:result['reporting_date']=day(data['reporting_date'],'Reporting date')
        if 'reviewed' in data:
            if data['reviewed'] not in ('yes','no'):raise ValueError('Choose whether you reviewed the match.')
            result['reviewed']=data['reviewed']
        if result['accepted']>result['submitted']: raise ValueError('Accepted credit cannot exceed submitted credit.')
        return result
    raise ValueError('Unknown certification record type.')


def normalize_relationships(values):
    if not isinstance(values,list) or len(values)>100:raise ValueError('Use up to 100 explicit renewal relationships.')
    result=[];seen=set()
    for item in values:
        if not isinstance(item,dict):raise ValueError('Invalid renewal relationship.')
        pair=(identifier(item.get('target')),item.get('trigger'))
        if pair[1] not in ('earning','renewing'):raise ValueError('Choose earning or renewing as the trigger.')
        if pair in seen:raise ValueError('This directional relationship already exists for that trigger.')
        seen.add(pair)
        result.append(dict(target=pair[0],trigger=pair[1],rule=policy_url(item.get('rule','')),
            checked=day(item.get('checked',''),'Relationship date checked'),conditions=text(item.get('conditions',''),'Relationship conditions',2000)))
    return result


def validate_attachment(content, *, badge=False):
    if not content or len(content)>MAX_ATTACHMENT_BYTES: raise ValueError('Uploads must contain 1 byte to 10 MiB.')
    if content.startswith(b'%PDF-'):
        if badge: raise ValueError('Badges must be PNG, JPEG or WebP images.')
        try:
            reader=PdfReader(BytesIO(content),strict=True)
            if reader.is_encrypted: raise ValueError('Encrypted PDFs are unsupported; upload an unencrypted copy.')
            if not 1<=len(reader.pages)<=1000: raise ValueError('PDFs must contain 1–1,000 pages.')
            # Never render PDFs inline. Reject executable or embedded-file features.
            seen=set(); nodes=[reader.trailer]; count=0
            while nodes:
                node=nodes.pop()
                if hasattr(node,'get_object'): node=node.get_object()
                if id(node) in seen: continue
                seen.add(id(node));count+=1
                if count>100000: raise ValueError('PDF structure is too complex.')
                if isinstance(node,dict):
                    if any(k in node for k in ('/JavaScript','/JS','/OpenAction','/AA','/EmbeddedFiles','/RichMedia','/Launch','/XFA')):
                        raise ValueError('PDFs with scripts, embedded files or automatic actions are unsupported.')
                    if node.get('/S') in ('/Launch','/JavaScript','/Rendition'):
                        raise ValueError('PDF automatic/executable actions are unsupported.')
                    nodes.extend(node.values())
                elif isinstance(node,(list,tuple)):nodes.extend(node)
            return 'application/pdf'
        except Exception as exc:
            raise ValueError('Upload a valid, unencrypted PDF without active content.') from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp'}.get(image.format)
                if not mime or image.width*image.height>MAX_IMAGE_PIXELS or getattr(image,'n_frames',1)!=1: raise ValueError()
                image.verify()
        # Re-encode to remove appended/polyglot payloads and metadata.
        with Image.open(BytesIO(content)) as image:
            out=BytesIO(); ImageOps.exif_transpose(image).convert('RGBA').save(out,format='PNG')
            mime='image/png'
            clean=out.getvalue()
            if len(clean)>MAX_ATTACHMENT_BYTES: raise ValueError()
        return mime,clean
    except Exception as exc: raise ValueError('Upload a single PNG, JPEG or WebP image (up to 16 million pixels), or a PDF.') from exc


def state(cur):
    row=cur.execute('SELECT generation,revision FROM certification_state WHERE id=1').fetchone()
    return dict(row)


def records(cur,table):
    if table not in TABLES: raise ValueError('Unknown records.')
    rows=[]
    for row in cur.execute(f'SELECT * FROM {table} ORDER BY id').fetchall():
        result=dict(row);result['data']=json.loads(result.pop('data_json'));rows.append(result)
    return rows


def collection(cur):
    result=records(cur,'certifications')
    latest={}
    for period in records(cur,'certification_cycles'):
        if period['certification_id'] not in latest or period.get('period_order',0)>latest[period['certification_id']].get('period_order',0):latest[period['certification_id']]=period
    for row in result:row['status']=tracking.status(row,latest.get(row['id']))
    return sorted(result,key=lambda r:(r['data']['earned'],r['id']),reverse=True)


def get(cur,table,record_id):
    identifier(record_id)
    if table not in TABLES:raise ValueError('Unknown records.')
    row=cur.execute(f'SELECT * FROM {table} WHERE id=?',(record_id,)).fetchone()
    if not row: raise ValueError('This record is unavailable. Return to My Certifications.')
    result=dict(row);result['data']=json.loads(result.pop('data_json'));return result


def detail(cur,record_id):
    cert=get(cur,'certifications',record_id)
    cycles=[r for r in records(cur,'certification_cycles') if r['certification_id']==record_id]
    cycles.sort(key=lambda r:r['period_order'],reverse=True)
    activities={r['id']:r for r in records(cur,'certification_training')}
    allocations=records(cur,'certification_allocations')
    for cycle in cycles:
        cycle['allocations']=[{**a,'training':activities[a['training_id']]} for a in allocations if a['cycle_id']==cycle['id']]
        cycle['totals']={key:round(sum(a['data'][key] for a in cycle['allocations']),2) for key in ('hours','submitted','accepted')}
        cycle['progress']=tracking.progress(cycle)
    cert['status']=tracking.status(cert,cycles[0] if cycles else None)
    return dict(certification=cert,cycles=cycles)



def validate_period(cur, cert_id, cert_data, proposed, existing=None, *, new_renewal=False):
    periods=[r for r in records(cur,'certification_cycles') if r['certification_id']==cert_id]
    order=existing['period_order'] if existing else max((r['period_order'] for r in periods),default=0)+1
    for label in ('start','expiration','renewal','renewed'):
        if proposed[label] and proposed[label]<cert_data['earned']:
            raise ValueError(f"The period's {label} date precedes the originally earned date. Correct the earned date or this period's details.")
    if new_renewal and not proposed['expiration']:
        raise ValueError('Record renewal needs the renewed expiration date. To correct current details, use Edit certification.')
    current_order=max((r['period_order'] for r in periods),default=order)
    if order>=current_order and cert_data['non_expiring']=='yes' and proposed['expiration']:
        raise ValueError('Does not expire conflicts with the current expiration date. Clear that date or choose an expiring credential.')
    for prior in periods:
        if existing and prior['id']==existing['id']:continue
        for key in ('start','expiration'):
            other=prior['data'][key];value=proposed[key]
            if other and value and ((prior['period_order']<order and other>=value) or (prior['period_order']>order and other<=value)):
                raise ValueError(f"This {key} date conflicts with period {prior['period_order']} ({other}). Use Correct historical details for that period, or correct this date; no history was changed.")
    if existing and proposed['unit']!=existing['data']['unit'] and cur.execute('SELECT 1 FROM certification_allocations WHERE cycle_id=?',(existing['id'],)).fetchone():
        raise ValueError('This period already has allocations. Keep its credit unit; use a new renewal period for a different unit.')
    return order


def apply(conn, payload, uploads=None):
    """Global optimistic revision + durable action identity protects retries/tabs/restore."""
    if not isinstance(payload,dict):raise ValueError('A certification request is required.')
    request_id=identifier(payload.get('request_id')); generation=identifier(payload.get('generation'))
    uploads=uploads or {}
    if set(uploads)-{'badge','certificate'}:raise ValueError('Unknown upload field.')
    prepared={}
    for key,content in uploads.items():
        result=validate_attachment(content,badge=key=='badge')
        mime,clean=result if isinstance(result,tuple) else (result,content)
        prepared[key]=(mime,clean)
    digest=sha256(json.dumps({'request':payload,'uploads':{k:sha256(v[1]).hexdigest() for k,v in prepared.items()}},sort_keys=True).encode()).hexdigest()
    conn.execute('BEGIN IMMEDIATE')
    try:
        cur=conn.cursor(); current=state(cur)
        if generation!=current['generation']:raise Conflict('This form predates a restore. Reopen the record; no change was applied.')
        old=cur.execute('SELECT * FROM certification_actions WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['input_hash']!=digest:raise Conflict('This request was already used for different changes. Reopen the record.')
            conn.rollback();return json.loads(old['result_json'])
        if type(payload.get('revision')) is not int or payload['revision']!=current['revision']:
            raise Conflict('Certifications changed in another tab. Reopen the record and compare before saving; your changes were not applied.')
        total=cur.execute('SELECT COALESCE(SUM(length(content)),0) FROM certification_attachments').fetchone()[0]
        if total+sum(len(v[1]) for v in prepared.values())>256*1024*1024:raise ValueError('Managed certification evidence exceeds the supported 256 MiB limit; keep a verified external copy before removing unused evidence.')
        action=payload.get('action'); data=payload.get('data',{}); record_id=payload.get('id') or uuid.uuid4().hex
        identifier(record_id)
        if action in ('certification','cycle','training','allocation'):
            table={'certification':'certifications','cycle':'certification_cycles','training':'certification_training','allocation':'certification_allocations'}[action]
            existing=cur.execute(f'SELECT * FROM {table} WHERE id=?',(record_id,)).fetchone()
            if payload.get('id') and not existing:raise Conflict('This record was removed. No replacement was created.')
            if not isinstance(data,dict):raise ValueError('Record fields are required.')
            data=dict(data)
            if existing:
                previous=json.loads(existing['data_json'])
                for key in ('version','standing','relationships','tracking','renewal_source','course_url','topics','proposed','rationale','category','source','reporting_date','reviewed'):
                    if key in previous:data.setdefault(key,previous[key])
            for key,(mime,content) in prepared.items():
                if key not in ({'badge','certificate'} if action=='certification' else {'certificate'} if action in ('cycle','training') else set()):raise ValueError('This record does not support that upload.')
                ref=uuid.uuid4().hex
                cur.execute('INSERT INTO certification_attachments VALUES(?,?,?,?)',(ref,mime,sha256(content).hexdigest(),content));data[key]=ref
            if payload.get('use_badge_certificate'):
                if action!='certification' or not existing or 'certificate' in prepared:raise ValueError('Choose either an existing display image or a replacement certificate upload.')
                source=json.loads(existing['data_json']).get('badge')
                if not source:raise ValueError('The existing display image is unavailable; upload a verified certificate instead.')
                data['certificate']=source
            if action=='certification' and 'relationships' in data:
                if data['relationships']!=(json.loads(existing['data_json']).get('relationships',[]) if existing else []):raise ValueError('Use the explicit renewal relationships form.')
            normalized=normalize(action,data)
            period_data=normalize('cycle',data) if action=='certification' and (not existing or payload.get('edit_current')) else None
            if action=='certification' and 'certificate' in prepared and period_data is None:raise ValueError('Open Edit certification to change the current certificate.')
            for key in ('badge','certificate'):
                ref=(period_data if period_data is not None and key=='certificate' else normalized).get(key)
                if ref:
                    attachment=cur.execute('SELECT mime FROM certification_attachments WHERE id=?',(ref,)).fetchone()
                    if not attachment:raise ValueError('The selected attachment is missing.')
                    if key=='badge' and not attachment['mime'].startswith('image/'):raise ValueError('A badge must be a raster image.')
            parent_fields={}
            if action=='cycle':
                cert_id=existing['certification_id'] if existing else payload.get('certification_id')
                if existing and payload.get('certification_id') not in (None,cert_id):raise Conflict('The cycle belongs to a different certification. Reopen its record.')
                cert=get(cur,'certifications',cert_id)
                existing_period=get(cur,'certification_cycles',record_id) if existing else None
                if payload.get('renewal_from'):
                    if existing:raise ValueError('A linked renewal must be a new confirmed event.')
                    source=get(cur,'certifications',payload['renewal_from'])
                    relation=next((r for r in source['data'].get('relationships',[]) if r['target']==cert_id and r['trigger']==payload.get('renewal_trigger')),None)
                    if not relation:raise Conflict('The renewal relationship changed or is unavailable. Reopen it before recording renewal.')
                    if payload.get('confirm_relationship') is not True:raise ValueError('Confirm that the issuer renewed the selected credential.')
                    normalized['renewal_source']=dict(name=source['data']['name'],issuer=source['data']['issuer'],trigger=relation['trigger'],rule=relation['rule'],recorded=normalized['renewed'])
                order=validate_period(cur,cert_id,cert['data'],normalized,existing_period,new_renewal=not existing)
                parent_fields={'certification_id':cert_id,'period_order':order}
            if action=='allocation':
                cycle_id=existing['cycle_id'] if existing else payload.get('cycle_id');training_id=existing['training_id'] if existing else payload.get('training_id')
                if existing and (payload.get('cycle_id') not in (None,cycle_id) or payload.get('training_id') not in (None,training_id)):
                    raise Conflict('The allocation belongs to a different cycle or activity. Reopen its record.')
                cycle=get(cur,'certification_cycles',cycle_id)
                if payload.get('certification_id') not in (None,cycle['certification_id']):raise Conflict('The allocation belongs to a different certification. Reopen its record.')
                training=get(cur,'certification_training',training_id)
                if normalized['hours']>training['data']['hours']:raise ValueError('Associated hours cannot exceed the activity’s recorded hours.')
                rules=cycle['data'].get('tracking',{})
                reporting=normalized.get('reporting_date') or training['data']['completed']
                if normalized.get('reporting_date') and reporting!=training['data']['completed'] and not normalized.get('rationale'):
                    raise ValueError('Explain the policy basis for a reporting date different from completion.')
                if normalized['submitted'] or normalized['accepted']:
                    if (rules.get('reporting_start') and reporting<rules['reporting_start']) or (rules.get('reporting_end') and reporting>rules['reporting_end']):
                        raise ValueError('The reporting date is outside this period. Correct the intended period or document a permitted reporting-date exception; no credit was saved.')
                parent_fields={'cycle_id':cycle_id,'training_id':training_id}
                if cur.execute('SELECT 1 FROM certification_allocations WHERE cycle_id=? AND training_id=? AND id!=?',(cycle_id,training_id,record_id)).fetchone():
                    raise Conflict('This activity already has an allocation in this cycle. Edit it instead of counting it twice.')
            current_period=None
            if action=='certification':
                periods=detail(cur,record_id)['cycles'] if existing else []
                current_period=periods[0] if periods else None
                if existing and payload.get('edit_current') and (payload.get('cycle_id')!=(current_period['id'] if current_period else None)):
                    raise Conflict('The current period changed. Reopen Edit certification; no changes were applied.')
                for prior in periods:
                    effective=period_data if current_period and prior['id']==current_period['id'] and period_data is not None else prior['data']
                    if any(effective[k] and effective[k]<normalized['earned'] for k in ('start','expiration','renewal','renewed')):
                        raise ValueError(f"Originally earned date conflicts with period {prior['period_order']}. Correct that period's historical details first; no history was changed.")
                if period_data is not None:
                    if current_period:
                        for key in ('tracking','renewal_source'):
                            if key not in period_data and key in current_period['data']:period_data[key]=current_period['data'][key]
                    validate_period(cur,record_id,normalized,period_data,current_period)
                elif current_period and normalized['non_expiring']=='yes' and current_period['data']['expiration']:
                    raise ValueError('Clear the current expiration date in Edit certification before choosing Does not expire.')
            if existing:
                cur.execute(f'UPDATE {table} SET data_json=? WHERE id=?',(json.dumps(normalized),record_id))
            else:
                values={'id':record_id,'data_json':json.dumps(normalized),**parent_fields}
                cur.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",tuple(values.values()))
            if action=='certification' and period_data is not None:
                if current_period:
                    cur.execute('UPDATE certification_cycles SET data_json=? WHERE id=?',(json.dumps(period_data),current_period['id']))
                else:
                    cur.execute('INSERT INTO certification_cycles(id,certification_id,data_json,period_order) VALUES(?,?,?,1)',(uuid.uuid4().hex,record_id,json.dumps(period_data)))
        elif action=='relationship':
            source=get(cur,'certifications',record_id)
            target=identifier(data.get('target'))
            if target==record_id:raise ValueError('A relationship must point to a different credential.')
            relations=source['data'].get('relationships',[])
            pair=(target,data.get('trigger'))
            remaining=[r for r in relations if (r['target'],r['trigger'])!=pair]
            if not payload.get('remove_relationship'):
                get(cur,'certifications',target)
                remaining+=normalize_relationships([data])
            elif payload.get('confirm') is not True:raise ValueError('Confirm removal of this relationship.')
            updated={**source['data'],'relationships':normalize_relationships(remaining)}
            cur.execute('UPDATE certifications SET data_json=? WHERE id=?',(json.dumps(updated),record_id))
        elif action=='delete':
            if payload.get('confirm') is not True:raise ValueError('Confirm removal before deleting a record.')
            table=payload.get('table');get(cur,table,record_id)
            cur.execute(f'DELETE FROM {table} WHERE id=?',(record_id,))
        else: raise ValueError('Unknown certification action.')
        # Drop only files no remaining record references; shared training stays.
        references=set()
        for table in TABLES:
            for row in records(cur,table):
                references.update(row['data'][key] for key in ('badge','certificate') if row['data'].get(key))
        for row in cur.execute('SELECT id FROM certification_attachments').fetchall():
            if row['id'] not in references:cur.execute('DELETE FROM certification_attachments WHERE id=?',(row['id'],))
        cur.execute('UPDATE certification_state SET revision=revision+1 WHERE id=1')
        result=dict(ok=True,id=record_id,**state(cur))
        cur.execute('INSERT INTO certification_actions VALUES(?,?,?,?)',(request_id,generation,digest,json.dumps(result)))
        conn.commit();return result
    except Exception:
        conn.rollback();raise


def curated_prompt(cur,cert_id,cycle_id,selection,question,template=None,include_certification=False,include_cycle=False):
    cert=get(cur,'certifications',cert_id);cycle=get(cur,'certification_cycles',cycle_id)
    if cycle['certification_id']!=cert_id:raise ValueError('Choose a renewal cycle belonging to this certification.')
    if not isinstance(selection,list) or len(selection)>200 or len(set(selection))!=len(selection):raise ValueError('Select up to 200 unique activities.')
    context={}
    if include_certification:
        context['certification']={k:cert['data'][k] for k in ('name','issuer','earned')}
    if include_cycle:
        context['renewal']={k:cycle['data'][k] for k in ('start','expiration','renewal','required','unit','policy')}
        if not cycle['data'].get('tracking',{}).get('requirement_known',bool(cycle['data']['required'])):context['renewal']['required']='Unknown — verify with issuer'
    activities=[]
    for allocation_id in selection:
        row=get(cur,'certification_allocations',allocation_id)
        if row['cycle_id']!=cycle_id:raise ValueError('Select activities from this cycle only.')
        training=get(cur,'certification_training',row['training_id'])
        activities.append({**{k:training['data'][k] for k in ('name','provider','completed','hours')},**{k:row['data'][k] for k in ('submitted','accepted')}})
    if activities:context['selected_training']=activities
    context['question']=text(question,'Question for the AI',2000,True)
    # Notes and attachments are intentionally not eligible context fields.
    return (template or DEFAULT_CERTIFICATION_PROMPT).replace('{{certification_context}}',json.dumps(context,ensure_ascii=False,indent=2))


def validate_restored(conn):
    """Bounded semantic validation of certification data before staged restore applies."""
    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not set(TABLES).intersection(tables):return
    from dlms.persistence.certification_schema import COLUMNS,validate_state
    version=conn.execute('SELECT version FROM schema_meta WHERE id=1').fetchone()[0] if 'schema_meta' in tables else 7
    for table,columns in COLUMNS.items():
        if version<8:columns=columns-{'period_order'}
        if table not in tables or not columns <= {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            raise ValueError('Certification backup schema is incomplete.')
    validate_state(conn)
    conn.row_factory=__import__('sqlite3').Row;cur=conn.cursor()
    attachments=set()
    total=0
    for row in cur.execute('SELECT * FROM certification_attachments'):
        identifier(row['id']);total+=len(row['content'])
        if row['id'] in attachments:raise ValueError('Certification backup contains duplicate attachment identifiers.')
        if total>256*1024*1024:raise ValueError('Certification attachments exceed the 256 MiB restore validation limit.')
        if sha256(row['content']).hexdigest()!=row['sha256']:raise ValueError('Certification attachment checksum failed.')
        result=validate_attachment(row['content']);mime=result[0] if isinstance(result,tuple) else result
        if mime!=row['mime']:raise ValueError('Certification attachment format does not match its record.')
        attachments.add(row['id'])
    loaded={table:records(cur,table) for table in TABLES}
    for table,kind in zip(TABLES,('certification','cycle','training','allocation')):
        if len({row['id'] for row in loaded[table]})!=len(loaded[table]):
            raise ValueError('Certification backup contains duplicate record identifiers.')
        for row in loaded[table]:
            identifier(row['id']);normalized=normalize(kind,row['data'])
            if normalized!=row['data']:raise ValueError('Certification backup contains incompatible fields.')
            for key in ('badge','certificate'):
                ref=normalized.get(key)
                # Missing evidence is shown as unavailable; never create replacement content.
                if ref and ref in attachments and key=='badge':
                    if not cur.execute('SELECT mime FROM certification_attachments WHERE id=?',(ref,)).fetchone()[0].startswith('image/'):
                        raise ValueError('Certification badge must be a raster image.')
    # An imported database may omit constraints: validate relationships ourselves.
    certificates={row['id']:row for row in loaded['certifications']}
    cycles={row['id']:row for row in loaded['certification_cycles']}
    training={row['id']:row for row in loaded['certification_training']}
    for cycle in cycles.values():
        parent=certificates.get(identifier(cycle['certification_id']))
        if not parent:raise ValueError('Certification backup has a renewal cycle without its certification.')
        if any(cycle['data'][k] and cycle['data'][k]<parent['data']['earned'] for k in ('start','expiration','renewal','renewed')):
            raise ValueError('Certification backup has conflicting earned or expiration dates.')
    for parent in certificates.values():
        periods=[r for r in cycles.values() if r['certification_id']==parent['id']]
        if periods:
            latest=max(periods,key=lambda r:r.get('period_order',0) if version>=8 else (r['data']['start'],r['id']))
            if parent['data']['non_expiring']=='yes' and latest['data']['expiration']:
                raise ValueError('Certification backup has an expiration for its current non-expiring period.')
    allocations=set()
    for allocation in loaded['certification_allocations']:
        pair=(identifier(allocation['cycle_id']),identifier(allocation['training_id']))
        if pair[0] not in cycles or pair[1] not in training:
            raise ValueError('Certification backup has an allocation without its cycle or training activity.')
        if pair in allocations:raise ValueError('Certification backup counts an activity twice in one cycle.')
        allocations.add(pair)
    for table in ('certification_cycles','certification_allocations'):
        if conn.execute(f'PRAGMA foreign_key_check({table})').fetchone():raise ValueError('Certification backup has broken record relationships.')


def portfolio_prompt(cur, certification_ids, training_ids, question, template=None):
    for selection in (certification_ids,training_ids):
        if not isinstance(selection,list) or len(selection)>200 or len(set(selection))!=len(selection):
            raise ValueError('Select up to 200 unique saved items in each list.')
    if not certification_ids:raise ValueError('Select at least one earned credential, from any issuer.')
    credentials=[]
    for cid in certification_ids:
        value=detail(cur,cid);cert=value['certification']['data']
        item={k:cert[k] for k in ('name','issuer','earned')}
        item['version']=cert.get('version','')
        if value['cycles']:
            period=value['cycles'][0]['data']
            item['current_period']={k:period[k] for k in ('start','expiration','renewal','unit','policy')}
            rules=period.get('tracking',{})
            item['current_period']['required']=period['required'] if rules.get('requirement_known',bool(period['required'])) else 'Unknown — verify with issuer'
            item['current_period']['rules']={k:rules[k] for k in ('version','route','checked','verification','annual_kind','annual_amount','year_basis','year_anchor','reporting_start','reporting_end','categories','conditions_status') if k in rules}
        credentials.append(item)
    activities=[]
    for tid in training_ids:
        row=get(cur,'certification_training',tid)['data']
        activities.append({k:row[k] for k in ('name','provider','completed','hours','course_url','topics') if k in row})
    context=dict(credentials=credentials,training=activities,question=text(question,'Question',2000,True))
    return (template or DEFAULT_PORTFOLIO_PROMPT).replace('{{portfolio_context}}',json.dumps(context,ensure_ascii=False,indent=2))
