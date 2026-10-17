"""Bounded manual installation/removal. No downloading, data adoption or sudo."""
from __future__ import annotations
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tarfile
import uuid

from desktop.install_manifest import NORMAL_FORMAT, APP_ID, owned_chain, release_id, decode
from desktop.management_state import state_root
from . import manual_replace as m
from . import install_pilot as i

MAX_ARCHIVE=1024*1024*1024
MAX_EXPANDED=2*1024*1024*1024
MAX_MEMBERS=20000
MAX_INTENT=8*1024*1024


def digest_json(value):return hashlib.sha256(m.pack(value)).hexdigest()


def _parent(path,home):
    i._assert_parent_chain(path,home)
    i._mkdir_parent(path,home)


@contextmanager
def management_gate(home,*,unresolved=False):
    i._assert_home(home)
    root=state_root(home);_parent(root,home)
    root.mkdir(mode=0o700,exist_ok=True);owned_chain(root,home)
    if root.stat().st_mode&0o077:raise ValueError('Management state is not private')
    fd=os.open(root/'management.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('Unsafe management lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if not unresolved and ((root/'active.json').exists() or (root/'active.json').is_symlink()):raise ValueError('Management outcome unresolved; run Reconcile')
        yield root
    finally:os.close(fd)


def _outside_payload(home):
    opt=i.paths(home)['opt']
    running=Path(getattr(sys,'_MEIPASS',sys.executable)).resolve()
    if running.is_relative_to(opt):
        raise ValueError('Use Install/Manage from an extracted candidate outside the installed versions; close DLMS first')


def _plain_source(path):
    if not path.is_absolute():raise ValueError('Choose an absolute local artifact path')
    for part in (path,*path.parents):
        if part.is_symlink():raise ValueError('Artifact symlinks are not supported')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    st=os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or not 0<st.st_size<=MAX_ARCHIVE:
        os.close(fd);raise ValueError('Artifact must be an owned bounded regular file')
    return fd


def prepare_archive(home,source,expected):
    if not i.re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('Supply the expected SHA-256 from a trusted source')
    with management_gate(home) as root:
        op=uuid.uuid4().hex;work=root/'artifacts'/op;_parent(work,home);work.mkdir(mode=0o700)
        archive=work/'candidate.tar.zst';fd=_plain_source(source);h=hashlib.sha256();total=0
        try:
            with os.fdopen(fd,'rb') as src, archive.open('xb') as dst:
                archive.chmod(0o600)
                while chunk:=src.read(1024*1024):
                    total+=len(chunk)
                    if total>MAX_ARCHIVE:raise ValueError('Artifact exceeds size limit')
                    h.update(chunk);dst.write(chunk)
                dst.flush();os.fsync(dst.fileno())
        except BaseException:
            # Retain bounded failed bytes for diagnosis; no destination mutation.
            raise
        if h.hexdigest()!=expected:raise ValueError('Artifact checksum differs; input preserved, installation unchanged')
        extraction=work/'extracted';extraction.mkdir(mode=0o700)
        with tarfile.open(archive,'r:zst') as tar:
            members=[];expanded=0
            for member in tar:
                expanded+=member.size
                if len(members)>=MAX_MEMBERS or expanded>MAX_EXPANDED:raise ValueError('Artifact archive limits exceeded')
                members.append(member)
            names=set()
            for member in members:
                name=PurePosixPath(member.name)
                if (name.is_absolute() or '..' in name.parts or str(name) in names
                        or name.parts[0] not in ('DLMS-Desktop','candidate.json')):raise ValueError('Unsafe or duplicate artifact member')
                names.add(str(name))
                if member.mode&0o6000 or not (member.isdir() or member.isfile() or member.issym()):raise ValueError('Unsupported archive member type')
                if member.issym():
                    target=PurePosixPath(member.linkname)
                    if target.is_absolute() or '..' in target.parts:raise ValueError('Unsafe archive link')
            tar.extractall(extraction,filter='data')
        payload=extraction/'DLMS-Desktop';candidate=m.read(extraction/'candidate.json',32768)
        if (set(candidate)!={'format','release','target','payload_inventory','compatibility','build'}
                or candidate['format']!=1 or candidate['target']!='fedora44-x86_64'
                or candidate['compatibility']!=m.COMPATIBILITY):raise ValueError('Unknown artifact metadata/compatibility')
        release_id(candidate['release']);m.compatible_payload(payload)
        if candidate['payload_inventory']!=m.payload_inventory(payload):raise ValueError('Extracted artifact differs from its inventory')
        if m.read(payload/'_internal/desktop_assets/build-info.json',32768)!=candidate['build']:raise ValueError('Build metadata differs')
        if i.sha256(archive)!=expected:raise ValueError('Private staged archive changed')
        prepared={'home':str(home),'work':str(work),'archive':str(archive),'archive_sha256':expected,'payload':str(payload),'candidate':candidate}
        m.exclusive(work/'prepared.json',m.pack(prepared))
        return prepared


def validate_prepared(home,value):
    work=Path(value['work']);root=state_root(home)/'artifacts'
    if value.get('home')!=str(home) or work.parent!=root:raise ValueError('Prepared artifact belongs to another home')
    m.operation(work.name);owned_chain(work,home)
    if m.read(work/'prepared.json')!=value:raise ValueError('Artifact receipt changed')
    if value['archive']!=str(work/'candidate.tar.zst') or value['payload']!=str(work/'extracted/DLMS-Desktop'):raise ValueError('Artifact paths differ')
    if i.sha256(Path(value['archive']))!=value['archive_sha256']:raise ValueError('Private artifact changed')
    payload=Path(value['payload']);m.compatible_payload(payload)
    if m.payload_inventory(payload)!=value['candidate']['payload_inventory']:raise ValueError('Prepared payload changed')
    return payload


def _lock_roots(data):
    for rel in ('shell','shell/pilot01','profiles','profiles/pilot01'):
        (data/rel).mkdir(mode=0o700,exist_ok=True)
    writer=data/'profiles/pilot01/backend-writer.lock'
    if not writer.exists():m.exclusive(writer,b'')
    else:m.old._regular_owned(writer)


def _removal_receipt(home,op):
    m.operation(op);root=state_root(home)/'operations'/op
    result=m.read(root/'result.json');intent=m.read(root/'intent.json',MAX_INTENT)
    if (result.get('outcome')!='removed' or result.get('operation_id')!=op
            or intent.get('kind')!='uninstall' or intent.get('home')!=str(home)):
        raise ValueError('Not a committed owned removal receipt')
    p=i.paths(home)
    if m.payload_inventory(root/'removed-opt')!=intent['opt_inventory']:raise ValueError('Removed installation evidence changed')
    if m.read(p['marker'],512)!=i._pilot_marker(p['data'],intent['install_id']):raise ValueError('Retained root identity differs')
    if m.old._data_fingerprint(home)!=intent['data_sha256']:raise ValueError('Retained data changed; reinstall needs review, not reset')
    return intent


def install_plan(home,prepared,*,reinstall=None):
    i._assert_home(home);_outside_payload(home);payload=validate_prepared(home,prepared);p=i.paths(home)
    retained=_removal_receipt(home,reinstall) if reinstall else None
    for key in ('opt','launcher','entry','icon_16','icon_24','icon_32','icon_48','icon_64'):
        i._assert_parent_chain(p[key],home)
        if p[key].exists() or p[key].is_symlink():raise FileExistsError(f'Existing target; no overwrite: {p[key]}. Use explicit pilot transition if applicable.')
    front=m.normal_launcher_path(home);i._assert_parent_chain(front,home)
    if front.exists() or front.is_symlink():raise FileExistsError(f'Launcher collision: {front}')
    if not retained and (p['data'].exists() or p['data'].is_symlink()):raise FileExistsError('Existing data root is not adopted automatically')
    value={'kind':'reinstall' if retained else 'install','home':str(home),'release':prepared['candidate']['release'],
           'archive_sha256':prepared['archive_sha256'],'payload_inventory':prepared['candidate']['payload_inventory'],
           'prepared':prepared,'retained_operation':reinstall,'data_preserved':str(p['data']),
           'profile':'pilot01','normal_launcher':str(front),'owned_paths':{k:str(v) for k,v in p.items()},
           'retained_fingerprint':retained['data_sha256'] if retained else None}
    return dict(value,confirmation=digest_json(value))


def update_plan(home,prepared,*,promote=False):
    _outside_payload(home);validate_prepared(home,prepared);current,raw=m.verify(home)
    if promote and current.get('normal_integration'):raise ValueError('Installation already has normal integration')
    if not promote and not current.get('normal_integration'):raise ValueError('Use explicit pilot transition first')
    if promote and (m.normal_launcher_path(home).exists() or m.normal_launcher_path(home).is_symlink()):raise FileExistsError('Normal launcher collision')
    value={'kind':'transition-pilot' if promote else 'update','home':str(home),'release':prepared['candidate']['release'],
           'baseline_sha256':hashlib.sha256(raw).hexdigest(),'prepared':prepared,'data_preserved':str(i.paths(home)['data'])}
    return dict(value,confirmation=digest_json(value))


def apply_update(home,plan,confirmation,*,fail_at=None):
    with management_gate(home):
        actual=update_plan(home,plan['prepared'],promote=plan['kind']=='transition-pilot')
        if actual!=plan or confirmation!=plan['confirmation']:raise ValueError('Update confirmation is stale or belongs to another artifact/destination')
        # Refuse before staging if live/accepted work exists; stage and activation
        # still independently acquire the reviewed gates and recheck everything.
        with m.gate(home),m.old._exclusive_window(home):m.old._ensure_no_pending_data(home)
        payload=validate_prepared(home,plan['prepared']);c=plan['prepared']['candidate']
        stage=m.stage(home,c['release'],Path(plan['prepared']['archive']),plan['prepared']['archive_sha256'],payload,c['payload_inventory'])
        return m.transition(home,stage_operation=stage['operation_id'],promote=plan['kind']=='transition-pilot',fail_at=fail_at)


def resume_plan(home,op):
    _outside_payload(home)
    current,raw=m.verify(home)
    record=m.read(m.stage_path(home,op))
    if (record.get('operation_id')!=op or record.get('install_id')!=current['install_id']
            or record.get('phase')!='staged' or record.get('baseline_sha256')!=m.hashlib.sha256(raw).hexdigest()):
        raise ValueError('Stage is stale or incomplete; reconcile its exact operation first')
    target=i.paths(home)['opt']/'versions'/release_id(record.get('release'))/'DLMS-Desktop'
    m._stage_container(target.parent,home,record);m.compatible_payload(target)
    if m.payload_inventory(target)!=record.get('inventory'):raise ValueError('Retained stage changed')
    value={'kind':'resume','home':str(home),'stage_operation':op,'stage':record,
           'manifest_sha256':m.hashlib.sha256(raw).hexdigest(),'data_sha256':m.old._data_fingerprint(home),
           'promote':not bool(current.get('normal_integration')),'data_preserved':str(i.paths(home)['data'])}
    return dict(value,confirmation=digest_json(value))


def apply_resume(home,plan,confirmation):
    with management_gate(home):
        actual=resume_plan(home,plan['stage_operation'])
        if actual!=plan or confirmation!=plan['confirmation']:raise ValueError('Resume confirmation stale')
        return m.transition(home,stage_operation=plan['stage_operation'],promote=plan['promote'],expected_data=plan['data_sha256'])


def _begin(home,kind,intent,work):
    op=work.name;root=state_root(home)
    intent=dict(intent,kind=kind,operation_id=op,home=str(home),uid=os.getuid())
    raw=m.pack(intent)
    if len(raw)>MAX_INTENT:raise ValueError('Management intent exceeds bound; no publication')
    m.exclusive(work/'intent.json',raw)
    m.exclusive(root/'active.json',m.pack({'operation_id':op,'home':str(home),'uid':os.getuid(),'intent_sha256':digest_json(intent)}))
    return intent


def _work(home):
    root=state_root(home)/'operations'/uuid.uuid4().hex;_parent(root,home);root.mkdir(mode=0o700);return root


def _finish(home,intent,work,outcome):
    result=work/'result.json';value={'operation_id':intent['operation_id'],'outcome':outcome,'data_sha256':m.old._data_fingerprint(home)}
    if not result.exists():m.exclusive(result,m.pack(value))
    elif m.read(result)!=value:raise ValueError('Management result changed; evidence retained')
    active=state_root(home)/'active.json'
    expected={'operation_id':intent['operation_id'],'home':str(home),'uid':os.getuid(),'intent_sha256':digest_json(intent)}
    if m.read(active)!=expected:raise ValueError('Management marker differs')
    active.unlink();m.old._fsync_dir(active.parent)
    return value


def _checkpoint(name,fail_at):
    if name==fail_at:raise RuntimeError('Synthetic management interruption: '+name)


@contextmanager
def retained_data_guard(home,retained):
    if retained:
        _removal_receipt(home,retained)
        alternate=state_root(home)/'operations'/retained/'removed-opt/versions'
        with m.old._exclusive_window(home,alternate_versions=alternate):
            m.old._ensure_no_pending_data(home)
            yield
    else:yield


def apply_install(home,plan,confirmation,*,fail_at=None):
    with management_gate(home),retained_data_guard(home,plan.get('retained_operation')):
        actual=install_plan(home,plan['prepared'],reinstall=plan['retained_operation'])
        if actual!=plan or confirmation!=plan['confirmation']:raise ValueError('Install confirmation is stale')
        p=i.paths(home);payload=validate_prepared(home,plan['prepared']);work=_work(home)
        iid=(_removal_receipt(home,plan['retained_operation'])['install_id'] if plan['retained_operation'] else uuid.uuid4().hex)
        opt=work/'new-opt';opt.mkdir(mode=0o700);versions=opt/'versions';versions.mkdir(mode=0o700)
        release=plan['release'];container=versions/release;container.mkdir(mode=0o700)
        shutil.copytree(payload,container/'DLMS-Desktop',symlinks=True)
        if m.payload_inventory(container/'DLMS-Desktop')!=plan['payload_inventory']:raise ValueError('Install copy changed')
        files=work/'files';files.mkdir(mode=0o700)
        marker=i._pilot_marker(p['data'],iid)
        sources={}
        for size in i.SIZES:
            sources[f'icon_{size}']=payload/f'_internal/desktop_assets/icons/hicolor/{size}x{size}/apps/{APP_ID}.png'
        for key,source in sources.items():m.exclusive(files/key,source.read_bytes());(files/key).chmod(0o644)
        for key,raw,mode in (('launcher',m.launcher(home,release),0o755),('entry',m.normal_entry_bytes(home),0o644),('normal_launcher',m.normal_launcher_bytes(home),0o755)):
            m.exclusive(files/key,raw);(files/key).chmod(mode)
        hashes={k:i.sha256(files/k) for k in ('launcher','entry',*(f'icon_{x}' for x in i.SIZES))}
        if plan['retained_operation']:hashes['marker']=i.sha256(p['marker'])
        else:
            data=work/'new-data';data.mkdir(mode=0o700);m.exclusive(data/i.MARKER_NAME,m.pack(marker));_lock_roots(data)
            hashes['marker']=i.sha256(data/i.MARKER_NAME)
        manifest={'version':2,'manifest_format':NORMAL_FORMAT,'installation_kind':'normal','phase':'complete','install_id':iid,'home':str(home),
            'archive_sha256':plan['archive_sha256'],'payload_inventory_sha256':plan['payload_inventory'],
            'owned_paths':{k:str(v) for k,v in p.items()},'releases':{release:plan['payload_inventory']},
            'active_release':release,'guard_release':release,'previous_release':None,'current_target':'versions/'+release,
            'file_sha256':hashes,'normal_integration':m.integration_record(home)}
        decode(manifest,home);m.exclusive(opt/'pilot-install.json',m.manifest_bytes(manifest));m.exclusive(opt/m.LOCK,b'')
        os.symlink('versions/'+release,opt/'current');m._sync_tree(opt);m._sync_tree(files)
        if not plan['retained_operation']:m._sync_tree(work/'new-data')
        moves={'opt':i.inventory(opt),**{k:i.sha256(files/k) for k in ('launcher','entry','normal_launcher',*(f'icon_{x}' for x in i.SIZES))}}
        if not plan['retained_operation']:moves['data']=i.inventory(work/'new-data')
        intent=_begin(home,'install',{'plan':plan,'install_id':iid,'moves':moves,'work_identity':[work.stat().st_dev,work.stat().st_ino]},work)
        _checkpoint('intent',fail_at)
        return _continue_install(home,intent,work,fail_at)


def _move(home,source,target,digest,*,tree):
    i._assert_parent_chain(target,home);_parent(target,home)
    def verify(path):
        owned_chain(path,home)
        if tree:
            if m.payload_inventory(path)!=digest:raise ValueError('Management tree changed')
        else:
            m.old._regular_owned(path)
            if i.sha256(path)!=digest:raise ValueError('Management file changed')
    have_source=source.exists() or source.is_symlink();have_target=target.exists() or target.is_symlink()
    if have_source==have_target:raise ValueError('Ambiguous move state; no overwrite')
    if have_target:verify(target);return
    verify(source);m._rename_noreplace(source,target);m.old._fsync_dir(source.parent);m.old._fsync_dir(target.parent)


def _continue_install(home,intent,work,fail_at=None):
    p=i.paths(home);moves=intent['moves']
    if 'data' in moves:_move(home,work/'new-data',p['data'],moves['data'],tree=True)
    else:_removal_receipt(home,intent['plan']['retained_operation'])
    _checkpoint('data',fail_at)
    _move(home,work/'new-opt',p['opt'],moves['opt'],tree=True);_checkpoint('opt',fail_at)
    for key in ('launcher','normal_launcher',*(f'icon_{x}' for x in i.SIZES),'entry'):
        target=m.normal_launcher_path(home) if key=='normal_launcher' else p[key]
        _move(home,work/'files'/key,target,moves[key],tree=False);_checkpoint(key,fail_at)
    m.verify(home);_checkpoint('commit',fail_at)
    return _finish(home,intent,work,'installed')


def _known_opt(home):
    p=i.paths(home)
    for leaf in p['opt'].iterdir():
        if leaf.name in ('current','versions','pilot-install.json',m.LOCK):continue
        if not leaf.name.endswith('.json') or leaf.is_symlink():raise ValueError('Unexplained installation file; no uninstall')
        record=m.read(leaf)
        if record.get('install_id')!=m.read(p['manifest'])['install_id']:raise ValueError('Unowned installation evidence')
        if leaf.name not in ('pilot-stage.json',) and not any(leaf.name.startswith(x) for x in ('manual-stage-','manual-resolved-','pilot-replacement-resolved-')):
            raise ValueError('Unknown installation evidence scope')
    manifest=m.read(p['manifest']);releases=decode(manifest,home)[0]
    if {x.name for x in (p['opt']/'versions').iterdir()}!=set(releases):raise ValueError('Unrecorded or incomplete version prevents uninstall')
    m.payload_inventory(p['opt'])


def uninstall_plan(home):
    _outside_payload(home);manifest,raw=m.verify(home);_known_opt(home);p=i.paths(home)
    files={k:{'path':str(p[k]),'sha256':v} for k,v in manifest['file_sha256'].items() if k!='marker'}
    if manifest.get('normal_integration'):files['normal_launcher']={'path':str(m.normal_launcher_path(home)),'sha256':manifest['normal_integration']['launcher_sha256']}
    # Inventory contains every retained payload, pointer and receipt. Data is
    # deliberately outside this tree and can never become a removal target.
    entries=[]
    for leaf in sorted(p['opt'].rglob('*')):
        if leaf.is_symlink():entries.append({'path':str(leaf),'kind':'link','target':os.readlink(leaf)})
        elif leaf.is_file():entries.append({'path':str(leaf),'kind':'file','bytes':leaf.stat().st_size,'sha256':i.sha256(leaf)})
    value={'kind':'uninstall','home':str(home),'install_id':manifest['install_id'],'manifest_sha256':hashlib.sha256(raw).hexdigest(),
           'opt_inventory':i.inventory(p['opt']),'files':files,'data_preserved':str(p['data']),'data_sha256':m.old._data_fingerprint(home),
           'retained_releases':manifest.get('releases',manifest.get('version_inventories',{})),'exact_opt_files':entries,
           'quarantine_retention':'Application paths are removed. Payload bytes and prior evidence are retained privately for reviewed cleanup, not silently purged.'}
    return dict(value,confirmation=digest_json(value))


def apply_uninstall(home,plan,confirmation,*,fail_at=None):
    with management_gate(home),m.gate(home),m.old._exclusive_window(home):
        m.old._ensure_no_pending_data(home)
        actual=uninstall_plan(home)
        if actual!=plan or confirmation!=plan['confirmation']:raise ValueError('Uninstall preview changed')
        work=_work(home);(work/'removed-files').mkdir(mode=0o700)
        intent=_begin(home,'uninstall',dict(plan,work_identity=[work.stat().st_dev,work.stat().st_ino]),work)
        _checkpoint('intent',fail_at)
        return _continue_uninstall(home,intent,work,fail_at)


def _continue_uninstall(home,intent,work,fail_at=None):
    p=i.paths(home)
    if m.old._data_fingerprint(home)!=intent['data_sha256']:raise ValueError('Data changed during removal; preserve evidence')
    _move(home,p['opt'],work/'removed-opt',intent['opt_inventory'],tree=True);_checkpoint('opt',fail_at)
    for key,info in intent['files'].items():
        expected=m.normal_launcher_path(home) if key=='normal_launcher' else p[key]
        if info['path']!=str(expected):raise ValueError('Removal path is not derived from owned layout')
        _move(home,expected,work/'removed-files'/key,info['sha256'],tree=False);_checkpoint(key,fail_at)
    _checkpoint('commit',fail_at)
    # Retain exact prior inventories/receipts/launcher/icon bytes as evidence.
    # Purging code is separately guarded so a process interruption is resumable.
    evidence=work/'retained-install-evidence';evidence.mkdir(mode=0o700,exist_ok=True)
    opt=work/'removed-opt'
    for leaf in opt.glob('*.json'):
        destination=evidence/leaf.name
        if not destination.exists():m.exclusive(destination,leaf.read_bytes())
        elif destination.read_bytes()!=leaf.read_bytes():raise ValueError('Removal evidence differs')
    result=_finish(home,intent,work,'removed')
    # Keep quarantined payload bytes for a separate explicit code-cleanup step.
    # This is honest reversible uninstall, never implicit data purging.
    return dict(result,quarantine=str(work/'removed-opt'),code_retained_for_recovery=True)


def reconcile(home):
    _outside_payload(home)
    with management_gate(home,unresolved=True):
        root=state_root(home);active=m.read(root/'active.json',32768)
        if active.get('home')!=str(home) or active.get('uid')!=os.getuid():raise ValueError('Management marker identity differs')
        op=m.operation(active.get('operation_id'));work=root/'operations'/op;owned_chain(work,home)
        intent=m.read(work/'intent.json',MAX_INTENT)
        if (digest_json(intent)!=active.get('intent_sha256') or intent.get('home')!=str(home)
                or intent.get('operation_id')!=op or intent.get('uid')!=os.getuid()
                or intent.get('work_identity')!=[work.stat().st_dev,work.stat().st_ino]):raise ValueError('Management intent changed')
        if intent['kind']=='install':
            with retained_data_guard(home,intent['plan'].get('retained_operation')):
                return _continue_install(home,intent,work)
        if intent['kind']=='uninstall':
            # After opt was quarantined the shared install gate moved with it;
            # external management lock and active marker still exclude launch.
            if i.paths(home)['opt'].exists():
                with m.gate(home),m.old._exclusive_window(home):
                    m.old._ensure_no_pending_data(home);return _continue_uninstall(home,intent,work)
            if m.payload_inventory(work/'removed-opt')!=intent['opt_inventory']:raise ValueError('Removal quarantine differs')
            with m.old._exclusive_window(home,alternate_versions=work/'removed-opt/versions'):
                m.old._ensure_no_pending_data(home);return _continue_uninstall(home,intent,work)
        raise ValueError('Unknown management transaction')
