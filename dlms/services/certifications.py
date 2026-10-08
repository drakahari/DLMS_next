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
from dlms.prompts import DEFAULT_CERTIFICATION_PROMPT

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
        return dict(name=text(data.get('name',''),'Certification name',200,True),issuer=text(data.get('issuer',''),'Issuer',200,True),
                    earned=day(data.get('earned',''),'Earned date',True),notes=text(data.get('notes',''),'Notes',5000),
                    badge=attachment_ref(data.get('badge','')), non_expiring=text(data.get('non_expiring','no'),'Expiration type',3))
    if kind=='cycle':
        result=dict(start=day(data.get('start',''),'Cycle start',True),expiration=day(data.get('expiration',''),'Expiration date'),
                    renewal=day(data.get('renewal',''),'Renewal date'),renewed=day(data.get('renewed',''),'Renewal recorded date'),
                    required=amount(data.get('required',0),'Required credit'),unit=text(data.get('unit','credits'),'Credit unit',60,True),
                    requirements=text(data.get('requirements',''),'Requirements / notes',5000),policy=policy_url(data.get('policy','')),
                    certificate=attachment_ref(data.get('certificate','')))
        if any(result[k] and result[k]<result['start'] for k in ('expiration','renewal','renewed')):
            raise ValueError('Cycle dates cannot precede the cycle start.')
        return result
    if kind=='training':
        return dict(name=text(data.get('name',''),'Activity / course',200,True),provider=text(data.get('provider',''),'Provider',200),
                    completed=day(data.get('completed',''),'Completion date',True),hours=amount(data.get('hours',0),'Recorded hours'),
                    notes=text(data.get('notes',''),'Training notes',5000),certificate=attachment_ref(data.get('certificate','')))
    if kind=='allocation':
        result=dict(hours=amount(data.get('hours',0),'Hours associated with this cycle'),submitted=amount(data.get('submitted',0),'Submitted credit'),
                    accepted=amount(data.get('accepted',0),'Accepted credit'),notes=text(data.get('notes',''),'Allocation notes',2000))
        if result['accepted']>result['submitted']: raise ValueError('Accepted credit cannot exceed submitted credit.')
        return result
    raise ValueError('Unknown certification record type.')


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
    cycles.sort(key=lambda r:(r['data']['start'],r['id']),reverse=True)
    activities={r['id']:r for r in records(cur,'certification_training')}
    allocations=records(cur,'certification_allocations')
    for cycle in cycles:
        cycle['allocations']=[{**a,'training':activities[a['training_id']]} for a in allocations if a['cycle_id']==cycle['id']]
        cycle['totals']={key:round(sum(a['data'][key] for a in cycle['allocations']),2) for key in ('hours','submitted','accepted')}
    return dict(certification=cert,cycles=cycles)


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
            for key,(mime,content) in prepared.items():
                if key not in ({'badge'} if action=='certification' else {'certificate'} if action in ('cycle','training') else set()):raise ValueError('This record does not support that upload.')
                ref=uuid.uuid4().hex
                cur.execute('INSERT INTO certification_attachments VALUES(?,?,?,?)',(ref,mime,sha256(content).hexdigest(),content));data[key]=ref
            normalized=normalize(action,data)
            for key in ('badge','certificate'):
                ref=normalized.get(key)
                if ref:
                    attachment=cur.execute('SELECT mime FROM certification_attachments WHERE id=?',(ref,)).fetchone()
                    if not attachment:raise ValueError('The selected attachment is missing.')
                    if key=='badge' and not attachment['mime'].startswith('image/'):raise ValueError('A badge must be a raster image.')
            parent_fields={}
            if action=='cycle':
                cert_id=existing['certification_id'] if existing else payload.get('certification_id')
                if existing and payload.get('certification_id') not in (None,cert_id):raise Conflict('The cycle belongs to a different certification. Reopen its record.')
                cert=get(cur,'certifications',cert_id)
                if cert['data'].get('non_expiring')=='yes' and normalized['expiration']:raise ValueError('A non-expiring credential cannot have an expiration date.')
                if normalized['start']<cert['data']['earned']:raise ValueError('The cycle cannot start before the certification was earned.')
                if not existing and cur.execute('SELECT 1 FROM certification_cycles WHERE certification_id=? AND json_extract(data_json,\'$.start\')>=?',(cert_id,normalized['start'])).fetchone():
                    raise ValueError('A new renewal cycle must start after the prior cycles; edit the existing cycle for corrections.')
                parent_fields={'certification_id':cert_id}
            if action=='allocation':
                cycle_id=existing['cycle_id'] if existing else payload.get('cycle_id');training_id=existing['training_id'] if existing else payload.get('training_id')
                if existing and (payload.get('cycle_id') not in (None,cycle_id) or payload.get('training_id') not in (None,training_id)):
                    raise Conflict('The allocation belongs to a different cycle or activity. Reopen its record.')
                cycle=get(cur,'certification_cycles',cycle_id)
                if payload.get('certification_id') not in (None,cycle['certification_id']):raise Conflict('The allocation belongs to a different certification. Reopen its record.')
                training=get(cur,'certification_training',training_id)
                if normalized['hours']>training['data']['hours']:raise ValueError('Associated hours cannot exceed the activity’s recorded hours.')
                parent_fields={'cycle_id':cycle_id,'training_id':training_id}
                if cur.execute('SELECT 1 FROM certification_allocations WHERE cycle_id=? AND training_id=? AND id!=?',(cycle_id,training_id,record_id)).fetchone():
                    raise Conflict('This activity already has an allocation in this cycle. Edit it instead of counting it twice.')
            if existing and action=='cycle' and json.loads(existing['data_json'])['unit']!=normalized['unit'] and cur.execute('SELECT 1 FROM certification_allocations WHERE cycle_id=?',(record_id,)).fetchone():
                raise ValueError('This cycle already has allocations. Keep its credit unit; use a new cycle for a different unit.')
            if existing and action=='certification':
                for prior in records(cur,'certification_cycles'):
                    if prior['certification_id']==record_id and (prior['data']['start']<normalized['earned'] or (normalized['non_expiring']=='yes' and prior['data']['expiration'])):
                        raise ValueError('Earned date or non-expiring status conflicts with a recorded renewal cycle. Correct that cycle first.')
            if existing:
                cur.execute(f'UPDATE {table} SET data_json=? WHERE id=?',(json.dumps(normalized),record_id))
            else:
                values={'id':record_id,'data_json':json.dumps(normalized),**parent_fields}
                cur.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",tuple(values.values()))
            if action=='certification' and not existing:
                cycle_id=uuid.uuid4().hex
                first=normalize('cycle',dict(start=normalized['earned']))
                cur.execute('INSERT INTO certification_cycles VALUES(?,?,?)',(cycle_id,record_id,json.dumps(first)))
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
    for table,columns in COLUMNS.items():
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
        if (cycle['data']['start']<parent['data']['earned']
                or (parent['data']['non_expiring']=='yes' and cycle['data']['expiration'])):
            raise ValueError('Certification backup has conflicting earned or expiration dates.')
    allocations=set()
    for allocation in loaded['certification_allocations']:
        pair=(identifier(allocation['cycle_id']),identifier(allocation['training_id']))
        if pair[0] not in cycles or pair[1] not in training:
            raise ValueError('Certification backup has an allocation without its cycle or training activity.')
        if pair in allocations:raise ValueError('Certification backup counts an activity twice in one cycle.')
        allocations.add(pair)
    for table in ('certification_cycles','certification_allocations'):
        if conn.execute(f'PRAGMA foreign_key_check({table})').fetchone():raise ValueError('Certification backup has broken record relationships.')
