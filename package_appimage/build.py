"""Assemble a fresh AppDir using the reviewed frozen minimal dependency graph."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
from package_fedora.minimal_bundle import verify_payload
from desktop.appimage_runtime import NAMESPACE


def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser()
    for arg in ['payload','appdir','output','tool','runtime','inputs']:
        p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--instrumented',action='store_true')
    a=p.parse_args()
    for x in ['appdir','output']:
        target=getattr(a,x).absolute()
        if target.exists() or target.is_symlink():raise FileExistsError('Never overwrite an AppImage/AppDir')
    pins=json.loads(a.inputs.read_text())
    for k in ['tool','runtime']:
        if digest(getattr(a,k))!=pins[k]['sha256']:raise ValueError('AppImage tooling bytes differ from pinned inputs')
    verify_payload(a.payload)
    platform_manifest = a.payload / '_internal/desktop_assets/host-platform.json'
    if platform_manifest.exists() or platform_manifest.is_symlink():
        from package_linux.host_platform import verify_payload as verify_platform
        verify_platform(a.payload)
    a.appdir.mkdir(mode=0o700)
    target=a.appdir/'usr/lib/dlms-desktop';target.parent.mkdir(parents=True)
    shutil.copytree(a.payload,target,symlinks=True)
    if a.instrumented:
        (target/'DLMS-Desktop-Instrumented').rename(target/'DLMS-Desktop')
    # No host integration/installer entry point. Bundled manager code is unchanged
    # existing runtime evidence, but standalone AppRun only accepts --profile.
    installer=target/'Install-DLMS-Desktop'
    if installer.exists():installer.unlink()
    root=Path(__file__).resolve().parent
    shutil.copyfile(root/'AppRun',a.appdir/'AppRun');(a.appdir/'AppRun').chmod(0o755)
    if a.instrumented:
        p=a.appdir/'AppRun';p.write_text(p.read_text().replace('--appimage-launch "$@"', '"$@"'))
    shutil.copyfile(root/'io.github.drakahari.DLMSDesktop.AppImageTest.desktop',
                    a.appdir/'io.github.drakahari.DLMSDesktop.AppImageTest.desktop')
    icon=target/'_internal/desktop_assets/dlms-icon-master.png'
    shutil.copyfile(icon,a.appdir/'io.github.drakahari.DLMSDesktop.AppImageTest.png')
    (a.appdir/'.DirIcon').symlink_to('io.github.drakahari.DLMSDesktop.AppImageTest.png')
    build=json.loads((target/'_internal/desktop_assets/build-info.json').read_text())
    info={'format':1,'namespace':NAMESPACE,'release':build['release'],
          'executable_sha256':digest(target/'DLMS-Desktop'),
          'runtime_sha256':pins['runtime']['sha256'],'runtime_bytes':pins['runtime']['bytes']}
    (target/'_internal/desktop_assets/appimage-info.json').write_text(json.dumps(info,indent=2)+'\n')
    shutil.copyfile(root/'inputs.json',a.appdir/'APPIMAGE-BUILD-INPUTS.json')
    for filename in ['runtime-LICENSE','tool-LICENSE']:
        text=a.inputs.parent/filename
        if text.is_file():shutil.copyfile(text,a.appdir/filename)

    # Pinned runtime: no implicit latest download, no update metadata or signing.
    env=dict(os.environ,ARCH='x86_64',VERSION=build['release'],APPIMAGE_EXTRACT_AND_RUN='1')
    subprocess.run([str(a.tool.absolute()),'--runtime-file',str(a.runtime.absolute()),
                    '--no-appstream','--comp','zstd','--mksquashfs-opt','-processors','--mksquashfs-opt','2',str(a.appdir.absolute()),str(a.output.absolute())],env=env,check=True)
    a.output.chmod(0o755)
    print(json.dumps({'file':str(a.output),'sha256':digest(a.output),'bytes':a.output.stat().st_size,
                      'build':build,'tool_pins':pins},indent=2))


if __name__=='__main__':main()
