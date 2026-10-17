"""Explicit, local-only manual replacement. Never downloads or writes profile data."""
from __future__ import annotations
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

from desktop.install_manifest import FORMAT, NORMAL_FORMAT, decode, release_id, validate_paths, owned_chain
from .install_pilot import paths, inventory, sha256, _pilot_marker, _assert_home
from . import replace_pilot as old

ACTIVE = 'pilot-replacement.json'  # Also understood by the retained legacy executable.
LOCK = 'manual-replacement.lock'


def pack(v):
    return (json.dumps(v, sort_keys=True, separators=(',', ':'))+'\n').encode()


def manifest_bytes(v):
    raw=pack(v)
    if len(raw)>8192:
        raise ValueError('Manifest exceeds retained legacy executable 8192-byte compatibility limit')
    return raw


def read(path,limit=262144):
    old._regular_owned(path,maximum=limit)
    return json.loads(path.read_bytes())


def exclusive(path, raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    old._fsync_dir(path.parent)


@contextmanager
def gate(home):
    p=paths(home); owned_chain(p['opt'],home)
    fd=os.open(p['opt']/LOCK,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        if (os.fstat(fd).st_uid!=os.getuid() or os.fstat(fd).st_mode & 0o077
                or not stat.S_ISREG(os.fstat(fd).st_mode)):
            raise ValueError('Installation lock is not private and owned')
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e: raise ValueError('Installation launch/replacement lock is held') from e
        yield
    finally: os.close(fd)


def payload_inventory(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Payload root must be a plain directory')
    for p in (root,*root.rglob('*')):
        st=p.lstat()
        if st.st_uid!=os.getuid() or (not p.is_symlink() and st.st_mode & 0o022):
            raise ValueError('Payload contains foreign-owned or externally writable entries')
    return inventory(root)


def verify(home, *, allow_active=False):
    _assert_home(home);p=paths(home)
    old._regular_owned(p['manifest'],maximum=8192)
    raw=p['manifest'].read_bytes()
    m=json.loads(raw); releases,active,guard=validate_paths(m,home)
    if not allow_active and ((p['opt']/ACTIVE).exists() or (p['opt']/ACTIVE).is_symlink()):
        raise ValueError('Replacement needs reconciliation')
    expected={'launcher','entry','marker',*(f'icon_{s}' for s in (16,24,32,48,64))}
    if set(m.get('file_sha256',{}))!=expected: raise ValueError('Incomplete owned file inventory')
    for k,digest in m['file_sha256'].items():
        owned_chain(p[k],home);old._regular_owned(p[k])
        if sha256(p[k])!=digest: raise ValueError(f'Owned file changed: {k}')
    if read(p['marker'],512)!=_pilot_marker(p['data'],m['install_id']):
        raise ValueError('Installed profile marker differs')
    for name,digest in releases.items():
        leaf=p['opt']/'versions'/name/'DLMS-Desktop'
        if payload_inventory(leaf)!=digest: raise ValueError(f'Retained payload differs: {name}')
    if m.get('normal_integration'):
        front = normal_launcher_path(home)
        owned_chain(front,home);old._regular_owned(front)
        if (sha256(front)!=m['normal_integration']['launcher_sha256']
                or front.read_bytes()!=normal_launcher_bytes(home)):
            raise ValueError('Normal launcher changed')
    return m,raw


def normal_launcher_path(home):
    return home/'.local/bin/dlms-desktop'


def normal_launcher_bytes(home):
    import shlex
    return ('#!/bin/sh\n# DLMS Desktop; preserve graphical session environment.\nexec '
            +shlex.quote(str(paths(home)['launcher']))+'\n').encode()


def normal_entry_bytes(home):
    p=paths(home)
    if any(ord(x)<32 or ord(x)==127 for x in str(home)):
        raise ValueError('Control characters in installation home are unsupported')
    # Desktop Exec quoting differs from shell quoting. Escape its four reserved
    # characters and double percent; no field codes or arbitrary commands.
    command=str(normal_launcher_path(home)).replace('%','%%')
    for char in ('\\','"','`','$'):
        command=command.replace(char,'\\'+char)
    return ('[Desktop Entry]\nType=Application\nName=DLMS Desktop\n'
            'Comment=Private Fedora desktop candidate\nExec="'+command+'"\n'
            f"Icon={p['icon_64']}\nTerminal=false\nCategories=Education;\nStartupNotify=true\n").encode()


def integration_record(home):
    return {'format':1,'desktop_name':'DLMS Desktop',
            'launcher_sha256':hashlib.sha256(normal_launcher_bytes(home)).hexdigest()}


def launcher(home,guard):
    release_id(guard);p=paths(home)
    exe=p['opt']/'versions'/guard/'DLMS-Desktop/DLMS-Desktop'
    import shlex
    return ("#!/bin/sh\n# Reviewed manual release guard; preserve graphical XDG_RUNTIME_DIR.\n"
            f"exec {shlex.quote(str(exe))} --pilot-launch --profile pilot01 --installed-pilot-root {shlex.quote(str(p['data']))}\n").encode()


COMPATIBILITY = {'format':1,'target':'fedora44-x86_64','schema':12,
                 'recovery_contract':'desktop-20261013','descriptor_boundary':2,'management_protocol':1}


def compatible_payload(payload):
    if (read(payload/'_internal/desktop_assets/install-compatibility.json',1024)!=COMPATIBILITY
            or read(payload/'_internal/desktop_assets/install-format.json',1024)!={'manifest_formats':[3,4],'guard_protocol':1}):
        raise ValueError('Payload compatibility is unknown; no schema/recovery changes are automatic')
    return True


def operation(value):
    if not isinstance(value,str) or not old.re.fullmatch('[0-9a-f]{32}',value):
        raise ValueError('Malformed operation identity')
    return value


def stage_path(home,op): return paths(home)['opt']/f'manual-stage-{operation(op)}.json'


def _sync_tree(root):
    for p in root.rglob('*'):
        if p.is_file() and not p.is_symlink():
            with p.open('rb') as f: os.fsync(f.fileno())
    for p in sorted((p for p in root.rglob('*') if p.is_dir() and not p.is_symlink()),reverse=True):
        old._fsync_dir(p)
    old._fsync_dir(root)


def stage(home, release, archive, archive_digest, payload, payload_digest, *, fail_at=None):
    release_id(release)
    with gate(home):
        m,raw=verify(home)
        if m.get('version')!=2: raise ValueError('Reusable replacement requires reviewed legacy v2 or format 3')
        releases,_,_=decode(m,home)
        if release in releases: raise ValueError('Release identity already retained; use a distinct identity')
        old._regular_owned(archive)
        if (not old._SHA.fullmatch(archive_digest) or not old._SHA.fullmatch(payload_digest)
                or sha256(archive)!=archive_digest or payload_inventory(payload)!=payload_digest):
            raise ValueError('Reviewed artifact hash differs')
        owned_chain(payload/'DLMS-Desktop', payload)
        capability=payload/'_internal/desktop_assets/install-format.json'
        owned_chain(capability,payload)
        if read(capability,1024) not in ({'manifest_formats':[3],'guard_protocol':1},{'manifest_formats':[3,4],'guard_protocol':1}):
            raise ValueError('Replacement lacks reviewed manifest/guard capability')
        if m.get('manifest_format')==NORMAL_FORMAT or m.get('normal_integration'):
            compatible_payload(payload)
        p=paths(home);op=uuid.uuid4().hex
        target=p['opt']/'versions'/release
        temp=target.with_name(f'.stage-{op}')
        if target.exists() or target.is_symlink(): raise FileExistsError('Release destination collision')
        # Durable intent precedes copying. Incomplete stages remain visible and never activate.
        record=dict(kind='dlms-manual-stage',format=1,operation_id=op,install_id=m['install_id'],
                    release=release,archive_sha256=archive_digest,inventory=payload_digest,
                    baseline_sha256=hashlib.sha256(raw).hexdigest(),phase='intent')
        sp=stage_path(home,op);exclusive(sp,pack(record))
        if fail_at=='intent': raise RuntimeError('Synthetic stage interruption: intent')
        temp.mkdir(mode=0o700)  # Exclusive ownership; never reuse an unrelated staging parent.
        old._fsync_dir(temp.parent)
        st=temp.stat();record.update(phase='copying',container_identity=[st.st_dev,st.st_ino])
        old._atomic_bytes(sp,pack(record))
        shutil.copytree(payload,temp/'DLMS-Desktop',symlinks=True)
        if payload_inventory(temp/'DLMS-Desktop')!=payload_digest: raise ValueError('Staged copy differs')
        _stage_container(temp,home,record)
        _sync_tree(temp)
        if fail_at=='copy': raise RuntimeError('Synthetic stage interruption: copy')
        if target.exists() or target.is_symlink(): raise FileExistsError('Release destination appeared')
        # Cooperating stage callers hold installation flock; no arbitrary competing writers supported.
        _rename_noreplace(temp,target);old._fsync_dir(target.parent)
        if fail_at=='rename': raise RuntimeError('Synthetic stage interruption: rename')
        record['phase']='staged';old._atomic_bytes(sp,pack(record))
        return record


def _rename_noreplace(source,target):
    # Fedora/Linux primitive; no close/check/replace window and no new dependency.
    import ctypes
    libc=ctypes.CDLL(None,use_errno=True)
    fn=libc.renameat2
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    fn.restype=ctypes.c_int
    if fn(-100,os.fsencode(source),-100,os.fsencode(target),1):
        number=ctypes.get_errno()
        raise OSError(number,os.strerror(number),str(target))


def _stage_container(path,home,record):
    owned_chain(path,home)
    st=path.stat()
    if (record.get('container_identity')!=[st.st_dev,st.st_ino]
            or sorted(x.name for x in path.iterdir())!=['DLMS-Desktop']):
        raise ValueError('Stage directory identity or contents differ; evidence retained')


def reconcile_stage(home,op):
    with gate(home):
        current,raw=verify(home);p=paths(home);sp=stage_path(home,op);record=read(sp)
        if (record.get('kind')!='dlms-manual-stage' or record.get('format')!=1
                or record.get('operation_id')!=op or record.get('install_id')!=current['install_id']
                or record.get('phase') not in ('copying','staged')
                or record.get('baseline_sha256')!=hashlib.sha256(raw).hexdigest()):
            raise ValueError('Stage baseline or identity differs; evidence retained')
        target=p['opt']/'versions'/release_id(record.get('release'))
        temp=target.with_name(f'.stage-{operation(op)}')
        if (target.exists() or target.is_symlink()) and (temp.exists() or temp.is_symlink()):
            raise ValueError('Ambiguous stage collision; evidence retained')
        candidate=target if target.exists() or target.is_symlink() else temp
        _stage_container(candidate,home,record)
        if payload_inventory(candidate/'DLMS-Desktop')!=record.get('inventory'):
            raise ValueError('Incomplete or changed stage; evidence retained; never activate')
        _sync_tree(candidate)
        if candidate==temp:
            _rename_noreplace(temp,target);old._fsync_dir(target.parent)
        record['phase']='staged';old._atomic_bytes(sp,pack(record));return record


def _new_manifest(current,home,releases,active,guard,previous,data,archive):
    new=dict(current,manifest_format=current.get('manifest_format',FORMAT),releases=releases,active_release=active,
             guard_release=guard,previous_release=previous,phase='complete',
             current_target=f'versions/{active}',payload_inventory_sha256=releases[active],
             activation_data_sha256=data,archive_sha256=archive)
    new.pop('replacement_operation_id',None)
    new['file_sha256']={**current['file_sha256'],'launcher':hashlib.sha256(launcher(home,guard)).hexdigest()}
    decode(new,home);manifest_bytes(new)
    return new


def _resolved(home,receipt):
    p=paths(home)['opt'];target=p/f'manual-resolved-{operation(receipt["operation_id"])}.json'
    if target.exists() or target.is_symlink(): raise FileExistsError('Resolved receipt collision')
    _rename_noreplace(p/ACTIVE,target);old._fsync_dir(p)


def _pointer(home,target):
    name=target.removeprefix('versions/')
    if target!=f'versions/{release_id(name)}': raise ValueError('Invalid pointer target')
    path=paths(home)['current'];tmp=path.with_name(f'.pointer-{uuid.uuid4().hex}')
    os.symlink(target,tmp);os.replace(tmp,path);old._fsync_dir(path.parent)


def transition(home, *, stage_operation=None, rollback=False, promote=False, expected_data=None, fail_at=None, checkpoint=None):
    with gate(home),old._exclusive_window(home):
        old._ensure_no_pending_data(home)
        current,raw=verify(home); releases,active,guard=decode(current,home);p=paths(home)
        data=old._data_fingerprint(home)
        if expected_data is not None and data!=expected_data:
            raise ValueError('Confirmed data identity changed before activation; review a fresh preview')
        if rollback:
            if current.get('manifest_format') not in (FORMAT,NORMAL_FORMAT) or data!=current.get('activation_data_sha256'):
                raise ValueError('Data changed or no compatible activation; rollback needs review')
            target=release_id(current.get('previous_release'))
            if target not in releases or target==active: raise ValueError('No retained previous release')
            if current.get('normal_integration'):
                compatible_payload(p['opt']/'versions'/target/'DLMS-Desktop')
            archive=current['archive_sha256']
        else:
            record=read(stage_path(home,stage_operation))
            if (record.get('kind')!='dlms-manual-stage' or record.get('format')!=1
                    or record.get('phase')!='staged' or record.get('operation_id')!=stage_operation
                    or record.get('install_id')!=current['install_id']
                    or record.get('baseline_sha256')!=hashlib.sha256(raw).hexdigest()):
                raise ValueError('Stage receipt is stale, incomplete or belongs to another installation')
            target=release_id(record.get('release'))
            if target in releases: raise ValueError('Stage release already retained')
            leaf=p['opt']/'versions'/target/'DLMS-Desktop'
            _stage_container(leaf.parent,home,record)
            if payload_inventory(leaf)!=record.get('inventory'): raise ValueError('Staged payload changed')
            releases[target]=record['inventory'];guard=target;archive=record['archive_sha256']
        new=_new_manifest(current,home,releases,target,guard,active,data,archive)
        branding=None
        if promote:
            if rollback or current.get('normal_integration'):
                raise ValueError('Promotion requires an unconverted installation')
            front=normal_launcher_path(home)
            if front.exists() or front.is_symlink():raise FileExistsError('Normal launcher collision')
            compatible_payload(p['opt']/'versions'/target/'DLMS-Desktop')
            branding=dict(old_entry=base64.b64encode(p['entry'].read_bytes()).decode(),
                          new_entry=base64.b64encode(normal_entry_bytes(home)).decode(),
                          new_front=base64.b64encode(normal_launcher_bytes(home)).decode())
            new['normal_integration']=integration_record(home)
            new['file_sha256']['entry']=hashlib.sha256(normal_entry_bytes(home)).hexdigest()
        new_raw=manifest_bytes(new);new_launcher=launcher(home,guard);old_launcher=p['launcher'].read_bytes()
        op=uuid.uuid4().hex
        receipt=dict(kind='dlms-manual-replacement',format=1,operation_id=op,install_id=current['install_id'],
                     old_manifest=base64.b64encode(raw).decode(),new_manifest=base64.b64encode(new_raw).decode(),
                     old_launcher=base64.b64encode(old_launcher).decode(),new_launcher=base64.b64encode(new_launcher).decode(),
                     data_sha256=data,stage_operation=stage_operation,rollback=rollback,
                     owner_pid=os.getpid(),
                     lock_evidence=[base64.b64encode(x.read_bytes()).decode() for x in old._lock_paths(home)[:2]])
        if branding:receipt['branding']=branding
        updating=dict(current,phase='updating',replacement_operation_id=op)
        updating_raw=manifest_bytes(updating)  # Refuse oversize before any active receipt/mutation.
        exclusive(p['opt']/ACTIVE,pack(receipt))
        def boundary(name):
            if checkpoint: checkpoint(name)
            if fail_at==name: raise RuntimeError(f'Synthetic interruption: {name}')
        boundary('receipt')
        old._atomic_bytes(p['manifest'],updating_raw);boundary('updating')
        if old._exact_processes(home): raise ValueError('Pilot process appeared; reconcile before retry')
        old._atomic_bytes(p['launcher'],new_launcher,0o755);boundary('launcher')
        _pointer(home,new['current_target']);boundary('pointer')
        if branding:
            exclusive(normal_launcher_path(home),normal_launcher_bytes(home))
            normal_launcher_path(home).chmod(0o755);old._fsync_dir(normal_launcher_path(home).parent)
            boundary('normal-launcher')
            old._atomic_bytes(p['entry'],normal_entry_bytes(home),0o644);boundary('entry')
        old._atomic_bytes(p['manifest'],new_raw);boundary('commit')
        verify(home,allow_active=True);_resolved(home,receipt)
        return new


def reconcile(home):
    with gate(home),old._exclusive_window(home):
        p=paths(home);r=read(p['opt']/ACTIVE)
        if r.get('kind')!='dlms-manual-replacement' or r.get('format')!=1:
            raise ValueError('Unknown active receipt; use its reviewed reconciler')
        operation(r.get('operation_id'))
        oldraw=base64.b64decode(r['old_manifest'],validate=True)
        newraw=base64.b64decode(r['new_manifest'],validate=True)
        before,after=json.loads(oldraw),json.loads(newraw)
        oldreleases,oldactive,oldguard=decode(before,home)
        releases,active,guard=decode(after,home)
        if (before['install_id']!=r['install_id'] or after['install_id']!=r['install_id']
                or any(releases.get(k)!=v for k,v in oldreleases.items())
                or after.get('previous_release')!=oldactive or active==oldactive
                or after.get('activation_data_sha256')!=r['data_sha256']):
            raise ValueError('Receipt lineage differs')
        if r.get('rollback') is True:
            if (releases!=oldreleases or guard!=oldguard
                    or active!=before.get('previous_release')
                    or r.get('stage_operation') is not None
                    or before.get('activation_data_sha256')!=r['data_sha256']):
                raise ValueError('Rollback receipt lineage differs')
        elif r.get('rollback') is False:
            staged=read(stage_path(home,r.get('stage_operation')))
            _stage_container(p['opt']/'versions'/active,home,staged)
            if (staged.get('kind')!='dlms-manual-stage' or staged.get('format')!=1
                    or staged.get('phase')!='staged'
                    or staged.get('operation_id')!=r.get('stage_operation')
                    or staged.get('install_id')!=r['install_id']
                    or staged.get('baseline_sha256')!=hashlib.sha256(oldraw).hexdigest()
                    or staged.get('release')!=active or active in oldreleases or guard!=active
                    or staged.get('archive_sha256')!=after.get('archive_sha256')
                    or releases!={**oldreleases,active:staged.get('inventory')}):
                raise ValueError('Activation receipt and stage lineage differ')
        else:
            raise ValueError('Unknown receipt operation type')
        if old._data_fingerprint(home)!=r['data_sha256']:
            raise ValueError('Data changed during interruption; state unresolved')
        oldlaunch=base64.b64decode(r['old_launcher'],validate=True)
        newlaunch=base64.b64decode(r['new_launcher'],validate=True)
        if (hashlib.sha256(oldlaunch).hexdigest()!=before['file_sha256']['launcher']
                or newlaunch!=launcher(home,guard)
                or hashlib.sha256(newlaunch).hexdigest()!=after['file_sha256']['launcher']):
            raise ValueError('Receipt launcher differs')
        branding=r.get('branding')
        if branding:
            if (set(branding)!={'old_entry','new_entry','new_front'} or before.get('normal_integration')
                    or after.get('normal_integration')!=integration_record(home) or r.get('rollback')):
                raise ValueError('Promotion receipt identity differs')
            oldentry=base64.b64decode(branding['old_entry'],validate=True)
            newentry=base64.b64decode(branding['new_entry'],validate=True)
            newfront=base64.b64decode(branding['new_front'],validate=True)
            if (hashlib.sha256(oldentry).hexdigest()!=before['file_sha256']['entry']
                    or newentry!=normal_entry_bytes(home) or newfront!=normal_launcher_bytes(home)
                    or after['file_sha256']['entry']!=hashlib.sha256(newentry).hexdigest()):
                raise ValueError('Promotion bytes differ')
            front=normal_launcher_path(home)
            if front.exists() or front.is_symlink():
                old._regular_owned(front)
                if front.read_bytes()!=newfront:raise ValueError('Normal launcher collision during recovery')
            old._regular_owned(p['entry'])
            if p['entry'].read_bytes() not in (oldentry,newentry):raise ValueError('Entry changed during promotion')
        elif after.get('normal_integration')!=before.get('normal_integration'):
            raise ValueError('Unexpected integration change')
        for k,digest in before['file_sha256'].items():
            owned_chain(p[k],home)
            if k!='launcher' and not (branding and k=='entry') and (sha256(p[k])!=digest or after['file_sha256'].get(k)!=digest):
                raise ValueError('Untouched installation file changed')
        for name,digest in releases.items():
            leaf=p['opt']/'versions'/name/'DLMS-Desktop';owned_chain(leaf,home)
            if payload_inventory(leaf)!=digest: raise ValueError('Receipt payload differs')
        old._regular_owned(p['manifest'],maximum=8192);actual=p['manifest'].read_bytes()
        updating=pack(dict(before,phase='updating',replacement_operation_id=r['operation_id']))
        if actual not in (oldraw,newraw,updating): raise ValueError('Unknown manifest state; unresolved')
        if not p['current'].is_symlink(): raise ValueError('Unknown pointer state')
        pointer=os.readlink(p['current'])
        if pointer not in (before['current_target'],after['current_target']): raise ValueError('Unknown pointer target')
        if p['launcher'].read_bytes() not in (oldlaunch,newlaunch): raise ValueError('Unknown launcher state')
        if actual==newraw:
            if pointer!=after['current_target'] or p['launcher'].read_bytes()!=newlaunch:
                raise ValueError('Committed installation is inconsistent')
            verify(home,allow_active=True);outcome='committed'
        else:
            if branding:
                old._atomic_bytes(p['entry'],oldentry,0o644)
                front=normal_launcher_path(home)
                if front.exists():front.unlink();old._fsync_dir(front.parent)
            _pointer(home,before['current_target']);old._atomic_bytes(p['launcher'],oldlaunch,0o755)
            old._atomic_bytes(p['manifest'],oldraw);verify(home,allow_active=True);outcome='rolled_back'
        _resolved(home,r);return outcome


def retire_transition_locks(home):
    """Explicit manual step after a dead replacer; preserve exact Qt lock evidence.

    Never retires application owner descriptors or guesses a stale lock by age.
    The active receipt remains blocking until full reconciliation completes.
    """
    with gate(home):
        p=paths(home);r=read(p['opt']/ACTIVE);op=operation(r.get('operation_id'))
        if r.get('kind')!='dlms-manual-replacement' or r.get('format')!=1:
            raise ValueError('Not a recorded manual replacement')
        pid=r.get('owner_pid')
        if type(pid) is not int or pid<=0 or Path(f'/proc/{pid}').exists():
            raise ValueError('Replacement PID exists/reused or unknown; lock evidence retained')
        before_raw=base64.b64decode(r['old_manifest'],validate=True)
        after_raw=base64.b64decode(r['new_manifest'],validate=True)
        before,after=json.loads(before_raw),json.loads(after_raw)
        decode(before,home);decode(after,home)
        if before['install_id']!=r['install_id'] or after['install_id']!=r['install_id']:
            raise ValueError('Replacement install identity differs')
        old._regular_owned(p['manifest'],maximum=8192)
        if p['manifest'].read_bytes() not in (before_raw,after_raw,pack(dict(before,phase='updating',replacement_operation_id=op))):
            raise ValueError('Unrecognized manifest; lock evidence retained')
        if (not p['current'].is_symlink() or os.readlink(p['current']) not in
                (before['current_target'],after['current_target'])):
            raise ValueError('Unrecognized pointer; lock evidence retained')
        if old._exact_processes(home) or any(x.exists() or x.is_symlink() for x in old._owner_paths(home)):
            raise ValueError('Application process/owner evidence remains; refuse retirement')
        owned_chain(p['data'],home);owned_chain(p['marker'],home)
        if p['data'].stat().st_mode & 0o077 or read(p['marker'],512)!=_pilot_marker(p['data'],r['install_id']):
            raise ValueError('Private data marker differs; refuse lock retirement')
        for lock in old._lock_paths(home):
            owned_chain(lock.parent,home)
            if lock.exists() or lock.is_symlink():owned_chain(lock,home)
        locks=old._lock_paths(home)[:2];encoded=r.get('lock_evidence')
        if not isinstance(encoded,list) or len(encoded)!=2:
            raise ValueError('No exact recorded replacement locks')
        originals=[base64.b64decode(x,validate=True) for x in encoded]
        evidence=p['opt']/f'manual-lock-evidence-{op}'
        if evidence.exists():
            owned_chain(evidence,home)
        else:
            evidence.mkdir(mode=0o700);old._fsync_dir(evidence.parent)
        for i,(lock,raw) in enumerate(zip(locks,originals)):
            if raw.splitlines()[:1]!=[str(pid).encode()]:
                raise ValueError('Recorded Qt lock PID differs')
            saved=evidence/f'{i}.lock'
            if saved.exists() or saved.is_symlink():
                old._regular_owned(saved)
                if saved.read_bytes()!=raw:raise ValueError('Retained lock evidence differs')
            if lock.exists() or lock.is_symlink():
                old._regular_owned(lock,maximum=4096)
                if lock.read_bytes()!=raw:raise ValueError('Qt lock changed; refuse retirement')
            elif not saved.exists():
                raise ValueError('Qt lock missing without retained evidence')
        writer=old._lock_paths(home)[2];old._regular_owned(writer)
        fd=os.open(writer,os.O_RDWR|os.O_NOFOLLOW)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as e:raise ValueError('Backend writer still active') from e
            if Path(f'/proc/{pid}').exists() or old._exact_processes(home):
                raise ValueError('Process identity became ambiguous')
            for i,(lock,raw) in enumerate(zip(locks,originals)):
                saved=evidence/f'{i}.lock'
                if not saved.exists():exclusive(saved,raw)
            for lock,raw in zip(locks,originals):
                if lock.exists():
                    if lock.read_bytes()!=raw:raise ValueError('Qt lock changed during retirement')
                    lock.unlink();old._fsync_dir(lock.parent)
        finally:os.close(fd)
        return {'evidence':str(evidence),'active_receipt_retained':True}


def removal_plan(home):
    m,_=verify(home);releases,_,_=decode(m,home);p=paths(home)
    # Planning only: keep prior payloads/receipts as explicit retained evidence.
    return dict(manifest_format=m.get('manifest_format',m['version']),
                removable_entry_points=[str(p[k]) for k in ('entry','launcher','current',*(f'icon_{s}' for s in (16,24,32,48,64)))],
                retained_versions={k:dict(path=str(p['opt']/'versions'/k),sha256=v) for k,v in releases.items()},
                retained_evidence=[str(x) for x in sorted(p['opt'].glob('*.json'))],
                data_preserved=str(p['data']),execution='No expanded-install removal authorized; plan only')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('verify','stage','reconcile-stage','activate','rollback','reconcile','retire-transition-locks','removal-plan'))
    p.add_argument('--home',required=True,type=Path);p.add_argument('--release')
    p.add_argument('--archive',type=Path);p.add_argument('--archive-sha256')
    p.add_argument('--payload',type=Path);p.add_argument('--payload-inventory-sha256');p.add_argument('--operation')
    a=p.parse_args()
    if a.action=='verify': result=verify(a.home)[0]
    elif a.action=='stage':
        if not all((a.release,a.archive,a.archive_sha256,a.payload,a.payload_inventory_sha256)): p.error('stage needs release/archive/payload and both hashes')
        result=stage(a.home,a.release,a.archive,a.archive_sha256,a.payload,a.payload_inventory_sha256)
    elif a.action=='reconcile-stage':
        result=reconcile_stage(a.home,a.operation)
    elif a.action=='activate':
        if not a.operation: p.error('activate requires exact --operation from stage receipt')
        result=transition(a.home,stage_operation=a.operation)
    elif a.action=='rollback': result=transition(a.home,rollback=True)
    elif a.action=='reconcile': result={'outcome':reconcile(a.home)}
    elif a.action=='retire-transition-locks': result=retire_transition_locks(a.home)
    else: result=removal_plan(a.home)
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
