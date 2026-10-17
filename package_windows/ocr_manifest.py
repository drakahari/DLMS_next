"""Opt only the bundled Tesseract process into Windows UTF-8 path handling.

The pinned vendor input remains untouched. Existing manifest settings (including
privileges) are retained; the output and both manifest digests are recorded.
"""
from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET

ASM='urn:schemas-microsoft-com:asm.v3'
UTF8='http://schemas.microsoft.com/SMI/2019/WindowsSettings'

def utf8_manifest(original):
    root=ET.fromstring(original)
    root.insert(0,ET.Comment(' DLMS Desktop modified this application manifest: activeCodePage=UTF-8 only. '))
    application=root.find('{'+ASM+'}application')
    if application is None:application=ET.SubElement(root,'{'+ASM+'}application')
    settings=application.find('{'+ASM+'}windowsSettings')
    if settings is None:settings=ET.SubElement(application,'{'+ASM+'}windowsSettings')
    codepage=settings.find('{'+UTF8+'}activeCodePage')
    if codepage is None:codepage=ET.SubElement(settings,'{'+UTF8+'}activeCodePage')
    codepage.text='UTF-8'
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)

def adapt(executable: Path):
    from PyInstaller.utils.win32 import winresource,winmanifest
    # Read resource maps directly: the pinned PyInstaller reader returns a
    # (language, bytes) tuple for a non-neutral language resource.
    manifests=winresource.get_resources(str(executable),[24])[24][1]
    if len(set(manifests.values()))!=1:raise ValueError('Ambiguous Tesseract manifests')
    original=next(iter(manifests.values()))
    result={'vendor_executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'vendor_manifest_sha256':hashlib.sha256(original).hexdigest()}
    updated=utf8_manifest(original)
    winmanifest.write_manifest_to_executable(str(executable),updated)
    actual=winresource.get_resources(str(executable),[24])[24][1]
    if any(x!=updated for x in actual.values()):raise ValueError('Tesseract manifest adaptation failed')
    result.update(prepared_executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                  prepared_manifest_sha256=hashlib.sha256(updated).hexdigest(),
                  change='Per-process activeCodePage=UTF-8; existing manifest settings retained')
    return result
