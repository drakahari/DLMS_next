"""Preview notices must remain byte-bound and retain the historical build path."""
import json
from pathlib import Path

import pytest

from package_fedora.assemble_distribution import assemble, verify_materials


def inputs(tmp_path):
    source=tmp_path/'inputs';source.mkdir()
    for name,text in {'REDISTRIBUTION.md':'licenses', 'BUILD_AND_REPLACEMENT.md':'source and replacement instructions',
                      'SOURCE_MATERIALS.json':json.dumps({'archives':[{'file':'source.tar','sha256':'a'*64}],'unresolved':[]})}.items():
        (source/name).write_text(text)
    return source,[(p.name,p) for p in sorted(source.iterdir())]


def test_historical_materials_still_use_original_contract(tmp_path):
    source=tmp_path/'old-notice';source.write_text('historical text')
    out=tmp_path/'out';assemble(out,[('old-notice',source)])
    assert verify_materials(out)['format']==1


def test_preview_materials_and_recipient_instructions_are_byte_bound(tmp_path):
    source,groups=inputs(tmp_path);out=tmp_path/'out'
    assemble(out,groups,preview=True)
    assert verify_materials(out)['format']==2
    (out/'REDISTRIBUTION.md').write_text('substituted terms')
    with pytest.raises(ValueError,match='differ from manifest'):verify_materials(out)


def test_missing_build_instructions_refuse_preview(tmp_path):
    source,groups=inputs(tmp_path)
    groups=[row for row in groups if row[0]!='BUILD_AND_REPLACEMENT.md']
    with pytest.raises(ValueError,match='instructions are missing'):
        assemble(tmp_path/'out',groups,preview=True)


def test_unresolved_source_index_refuses_preview(tmp_path):
    source,groups=inputs(tmp_path)
    (source/'SOURCE_MATERIALS.json').write_text(json.dumps({'archives':[{'file':'source.tar'}],'unresolved':['missing source']}))
    with pytest.raises(ValueError,match='unresolved'):
        assemble(tmp_path/'out',groups,preview=True)


def test_invalid_release_refuses_before_freezing_or_creating_output(tmp_path,monkeypatch):
    from package_appimage import build_payload
    output=tmp_path/'never-created'
    monkeypatch.setattr('sys.argv',['build_payload','--output',str(output),
        '--ocr-bundle',str(tmp_path/'ocr'),'--notices',str(tmp_path/'notices'),
        '--distribution-kit',str(tmp_path/'materials'),'--release','linux-3.3.0-preview1'])
    with pytest.raises(ValueError,match='Invalid release identifier'):
        build_payload.main()
    assert not output.exists()
