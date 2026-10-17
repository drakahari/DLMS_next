import xml.etree.ElementTree as ET
from package_windows.ocr_manifest import utf8_manifest,ASM,UTF8

def test_utf8_retains_existing_privileges_and_compatibility():
    original=b'''<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
      <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
      <requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo>
      <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      </windowsSettings></application></assembly>'''
    result=ET.fromstring(utf8_manifest(original))
    assert result.find('.//{'+ASM+'}requestedExecutionLevel').attrib=={'level':'asInvoker','uiAccess':'false'}
    assert result.find('.//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}longPathAware').text=='true'
    assert result.find('.//{'+UTF8+'}activeCodePage').text=='UTF-8'
    assert ET.tostring(ET.fromstring(utf8_manifest(utf8_manifest(original))))==ET.tostring(result)
