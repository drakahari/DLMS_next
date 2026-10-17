"""Frozen native/CLI installation manager, never a web-to-native bridge."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from . import installation as inst
from . import manual_replace as m
from .install_pilot import paths


def locations(home):
    p=paths(home)
    return {'name':'DLMS Desktop','application_id':'io.github.drakahari.DLMSDesktop',
            'payloads':str(p['opt']/'versions'),'pointer':str(p['current']),'manifest':str(p['manifest']),
            'launcher':str(m.normal_launcher_path(home)),'guarded_compatibility_launcher':str(p['launcher']),
            'desktop_entry':str(p['entry']),'icons':{str(x):str(p[f'icon_{x}']) for x in (16,24,32,48,64)},
            'persistent_data':str(p['data']),'profile':'pilot01','management_state':str(inst.state_root(home)),
            'explanation':'Compatibility names are intentional; no existing data is renamed, moved, scanned or imported. No sudo.'}


def save_plan(home,plan):
    with inst.management_gate(home) as root:
        leaf=root/'plans'/f'{uuid.uuid4().hex}.json';inst._parent(leaf,home);m.exclusive(leaf,m.pack(plan));return leaf


def apply_plan(home,plan,confirmation):
    if plan['home']!=str(home):raise ValueError('Plan belongs to another home')
    if plan['kind'] in ('install','reinstall'):return inst.apply_install(home,plan,confirmation)
    if plan['kind'] in ('update','transition-pilot'):return inst.apply_update(home,plan,confirmation)
    if plan['kind']=='uninstall':return inst.apply_uninstall(home,plan,confirmation)
    if plan['kind']=='resume':return inst.apply_resume(home,plan,confirmation)
    raise ValueError('Unknown management scope')


def main(argv=None):
    parser=argparse.ArgumentParser(description='DLMS Desktop manual per-user installation manager')
    parser.add_argument('action',nargs='?',choices=('gui','preview','prepare','install','reinstall','transition-pilot','update','resume','apply','uninstall','reconcile','reconcile-stage','rollback','retire-recorded-locks','prepare-variant'))
    parser.add_argument('--home',type=Path,default=Path.home())
    parser.add_argument('--artifact',type=Path);parser.add_argument('--sha256');parser.add_argument('--plan',type=Path)
    parser.add_argument('--base-payload',type=Path);parser.add_argument('--modified-payload',type=Path)
    parser.add_argument('--variant-output',type=Path);parser.add_argument('--release');parser.add_argument('--base-inventory')
    parser.add_argument('--confirm');parser.add_argument('--operation');args=parser.parse_args(argv)
    home=args.home.absolute()
    if args.action in (None,'gui'):
        from .manage_gui import run
        return run(home)
    if args.action=='prepare-variant':
        if not all((args.base_payload,args.modified_payload,args.variant_output,args.release,args.base_inventory)):
            parser.error('prepare-variant requires separate base/modified payloads, output, distinct release and reviewed base inventory')
        from .user_variant import prepare_variant
        result=prepare_variant(home,args.base_payload,args.modified_payload,args.variant_output,args.release,args.base_inventory)
    elif args.action=='preview':result=locations(home)
    elif args.action=='apply':
        if not args.plan or not args.confirm:parser.error('apply needs --plan and exact --confirm digest')
        result=apply_plan(home,m.read(args.plan,8*1024*1024),args.confirm)
    elif args.action in ('reconcile','reconcile-stage','rollback','retire-recorded-locks'):
        inst._outside_payload(home)
        if args.action=='reconcile':
            result=(inst.reconcile(home) if (inst.state_root(home)/'active.json').exists()
                    else m.reconcile(home))
        elif args.action=='reconcile-stage':result=m.reconcile_stage(home,args.operation)
        elif args.action=='retire-recorded-locks':
            if args.confirm!='RETIRE RECORDED DEAD REPLACER LOCKS':raise ValueError('Exact explicit confirmation required; application locks are never retired')
            result=m.retire_transition_locks(home)
        else:
            current,raw=m.verify(home)
            proposal={'manifest_sha256':m.hashlib.sha256(raw).hexdigest(),'data_sha256':m.old._data_fingerprint(home),'previous_release':current.get('previous_release')}
            token=inst.digest_json(proposal)
            if args.confirm is None:result=dict(proposal,confirmation=token,note='Rollback never restores data; incompatible or later data changes refuse')
            else:
                if args.confirm!=token:raise ValueError('Rollback confirmation stale')
                result=m.transition(home,rollback=True)
    elif args.action=='uninstall':
        plan=inst.uninstall_plan(home);leaf=save_plan(home,plan);result={'plan':plan,'plan_file':str(leaf)}
    elif args.action=='resume':
        plan=inst.resume_plan(home,args.operation);leaf=save_plan(home,plan);result={'plan':plan,'plan_file':str(leaf)}
    else:
        if not args.artifact or not args.sha256:parser.error('Select --artifact and expected --sha256 from a trusted source')
        prepared=inst.prepare_archive(home,args.artifact.absolute(),args.sha256)
        if args.action=='prepare':result=prepared
        else:
            if args.action in ('install','reinstall'):
                plan=inst.install_plan(home,prepared,reinstall=args.operation if args.action=='reinstall' else None)
            else:plan=inst.update_plan(home,prepared,promote=args.action=='transition-pilot')
            leaf=save_plan(home,plan);result={'plan':plan,'plan_file':str(leaf)}
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError) as exc:
        print('DLMS Desktop management refused: '+str(exc),file=sys.stderr);raise SystemExit(2)
