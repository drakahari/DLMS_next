"""Contracts for the separate video capture project; no production data access."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'


def load_tool(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location('demo_video_capture_test', TOOLS/'capture_demo_video_screenshots.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_manifest_story_contract(monkeypatch):
    tool = load_tool(monkeypatch)
    assert [f.id for f in tool.V2_FRAMES] == [f'{i:03}' for i in range(1,37)]
    assert [f.id for f in tool.V3_ADDITIONS] == ['013A', '013B', '028A', '028B']
    assert len({f.filename for f in tool.FRAMES}) == 43
    assert [f.id for f in tool.EXAM_ADDITIONS] == ['011A', '011B', '011C']
    assert all(f.essential for f in tool.EXAM_ADDITIONS)
    assert 300 <= sum(f.seconds for f in tool.V2_FRAMES) <= 420
    assert sum(f.seconds for f in tool.V3_ADDITIONS) == 44
    assert all(f.filename.startswith(f.id+'-') and f.filename.endswith('.png') for f in tool.FRAMES)
    assert all(f.fixture and f.state and f.ready for f in tool.FRAMES)
    assert (tool.WIDTH, tool.HEIGHT) == (1920,1080)
    assert tool.THEMES['Purple & Gold'] == 'purple-gold'
    assert tool.manual.THEME == 'light'
    assert (tool.manual.WIDTH,tool.manual.HEIGHT) == (1440,1000)


def test_list_is_side_effect_free_and_focused(monkeypatch,capsys):
    tool = load_tool(monkeypatch)
    monkeypatch.setattr(tool,'capture',lambda *a,**kw: (_ for _ in ()).throw(AssertionError('capture started')))
    assert tool.main(['--list','--only','1,003,13a,014,028b','--theme','Purple & Gold']) == 0
    assert [f['id'] for f in json.loads(capsys.readouterr().out)] == ['001','003','013A','014','028B']


def test_reject_invalid_id_and_manual_output(monkeypatch):
    import pytest
    tool = load_tool(monkeypatch)
    for args in (['--only','999'],['--only','001','--output',str(ROOT/'docs/user-manual/images')]):
        with pytest.raises(SystemExit) as error:
            tool.main(args)
        assert error.value.code == 2


def test_original_questions_and_evidence_contract(monkeypatch):
    load_tool(monkeypatch)
    import demo_video_fixture as fixture
    assert len(fixture.SOURCES) == 4
    for source in fixture.SOURCES:
        for question in fixture.questions(source):
            assert question['correct'] == ['A']
            assert [c['label'] for c in question['choices'] if c['is_correct']] == ['A']
            assert question['explanation'] and question['concepts']
    assert fixture.SOURCES[0][5] == [1]*6
    assert fixture.SOURCES[1][5] == [0, 1, 1, 1, 0, 0]  # Decline survives demonstrated Study saves.
    assert fixture.SOURCES[2][5][-3:] == [1]*3
    assert fixture.SOURCES[3][5] == []


def test_direct_server_rejects_unowned_root(monkeypatch,tmp_path):
    tool = load_tool(monkeypatch)
    monkeypatch.setenv('QUIZAPP_DATA_DIR',str(tmp_path))
    import pytest
    with pytest.raises(RuntimeError,match='capture-owned'):
        tool.serve()


def test_plan_and_storyboard_cover_every_frame(monkeypatch):
    tool = load_tool(monkeypatch)
    plan = (ROOT/'docs/demo-video/SCREENSHOT_PLAN.md').read_text()
    storyboard = (ROOT/'docs/demo-video/STORYBOARD.md').read_text()
    for f in tool.FRAMES:
        assert f.filename in plan
        assert f'| {f.id} |' in storyboard


def test_proof_dimensions_and_theme(monkeypatch):
    tool = load_tool(monkeypatch)
    proof = ROOT/'docs/demo-video/proof'
    records = json.loads((proof/'capture-001-003-014.json').read_text())
    assert records['theme'] == 'purple-gold'
    assert records['viewport'] == {'width':1920,'height':1080,'device_scale':1}
    assert len(list(proof.glob('*.png'))) == 3
    for f in records['captures']:
        assert tool.manual._png_dimensions(proof/f['filename']) == (1920,1080)


def test_manual_server_start_failure_cleans_own_process(monkeypatch,tmp_path):
    tool = load_tool(monkeypatch)
    class Process:
        pass
    process = Process()
    stopped = []
    monkeypatch.setattr(tool.manual,'_free_port',lambda:12345)
    monkeypatch.setattr(tool.manual.subprocess,'Popen',lambda *a,**kw:process)
    def fail(*args):
        raise RuntimeError('server failed')
    monkeypatch.setattr(tool.manual,'_wait_http',fail)
    def stop(p,**kwargs):
        stopped.append((p,kwargs))
        p._dlms_log_handle.close()
    monkeypatch.setattr(tool.manual,'_stop_process',stop)
    import pytest
    with pytest.raises(RuntimeError,match='server failed'):
        tool.manual._start_server(tmp_path,tmp_path/'data',lan=False,reuse=False)
    assert stopped == [(process,{'interrupt':True})]


def test_final_video_manifest_matches_canonical_images(monkeypatch):
    import hashlib
    from PIL import Image
    tool = load_tool(monkeypatch)
    project = ROOT/'docs/demo-video'
    manifest = json.loads((project/'video-manifest.json').read_text())
    assert [r['id'] for r in manifest] == list(range(1,37))
    assert len(list((project/'captures').glob('*.png'))) == 40
    assert [r['id'] for r in manifest if r['optional']] == [17,20,33,35]
    assert sum(r['duration_estimate'] for r in manifest) == 402
    for frame, record in zip(tool.V2_FRAMES,manifest):
        path = project/record['image']
        assert path.name == frame.filename
        assert record['state'] == frame.state
        assert record['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert record['theme'] == 'purple-gold'
        assert record['narration_objective'] and record['focus']
        source = json.loads((project/record['capture_metadata']).read_text())
        assert any(r['id'] == frame.id and r['status'] == 'captured' for r in source['captures'])
        with Image.open(path) as image:
            assert image.size == (1920,1080)
            # Secondary visual-theme guard: the outside canvas is dark purple,
            # including on the dimmed mastery-dialog frame, never Light.
            red, green, blue = image.convert('RGB').getpixel((0,540))
            assert blue > red > green


def test_final_contact_sheets_cover_complete_sequence():
    from PIL import Image
    project = ROOT/'docs/demo-video'
    sheets = sorted(project.glob('contact-sheet-*.png'))
    assert [p.name for p in sheets] == [f'contact-sheet-{i:02}.png' for i in range(1,7)]
    for path in sheets:
        with Image.open(path) as image:
            assert image.size == (1968,1824)


def test_v3_additions_handoff(monkeypatch):
    import hashlib
    from PIL import Image
    tool = load_tool(monkeypatch)
    project = ROOT/'docs/demo-video'
    payload = json.loads((project/'v3-additions-manifest.json').read_text())
    assert payload['v2_runtime_seconds'] == 403.6
    assert payload['v2_editorial_target_seconds'] == 390
    assert payload['v3_editorial_target_seconds'] == 425
    assert payload['new_scene_target_seconds'] == 44
    assert payload['redistributed_existing_target_seconds'] == -9
    assert payload['net_editorial_target_change_seconds'] == 35
    assert payload['estimated_v3_runtime_seconds'] == 438.6
    assert payload['actual_spoken_audio_seconds'] == 390.3
    assert payload['actual_v3_runtime_seconds'] == 439.666667
    assert payload['production_voice'] == 'af_heart'
    assert payload['production_speed'] == 1.0
    assert [row['id'] for row in payload['scenes']] == [f.id for f in tool.V3_ADDITIONS]
    for frame, row in zip(tool.V3_ADDITIONS, payload['scenes']):
        path = project/row['image']
        assert path.name == frame.filename
        assert row['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert row['theme'] == 'purple-gold'
        assert row['essential'] is True
        assert row['narration_objective'] and row['proposed_after']
        with Image.open(path) as image:
            assert image.size == (1920,1080)
            red, green, blue = image.convert('RGB').getpixel((0,540))
            assert blue > red > green
    with Image.open(project/'v3-additions-contact-sheet.png') as image:
        assert image.size == (1968,1224)
