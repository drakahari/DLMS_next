"""Phase 2 safety, source format and additive playlist contracts."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_phase2_seed_rejects_normal_data_root(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import documentation_video_phase2 as phase2
    with pytest.raises(RuntimeError, match='disposable'):
        phase2.seed(SimpleNamespace(APP_DATA_DIR=str(tmp_path)))
    assert list(tmp_path.iterdir()) == []


def test_fictional_law_packet_has_real_recognized_sections(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import documentation_video_phase2 as phase2
    from dlms.parsing.law_packet import parse_law_packet_sections
    sections = parse_law_packet_sections(phase2.LAW_PACKET)
    assert {s['key'] for s in sections} == {
        'sources_used', 'case_brief', 'socratic_review', 'socratic_answer_key',
        'irac_drill', 'rule_flashcards'}
    assert all(s['content'] for s in sections)


def test_phase2_selection_and_protected_definitions(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import build_documentation_videos as batch
    index, videos, catalog = batch.load_series()
    state = json.loads((batch.SERIES / 'editorial-status.json').read_text())
    assert [v['id'] for v in videos[6:]] == state['phase2_candidates']
    chosen = batch.select(videos, 'image-and-hotspot-authoring,reset-and-maintenance')
    assert [v['id'] for v in chosen] == ['reset-and-maintenance', 'image-and-hotspot-authoring']
    for video in videos[6:]:
        assert len(batch.select(videos, video['id'])) == 1
        assert len([s for s in video['scenes'] if s.get('chapter')]) >= 3
        assert all(s['audio_filename'] == s['id'] + '.wav' for s in video['scenes'])
    for name, expected in state['approved_definition_sha256'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    assert set(state['required_topic_coverage']) == {str(i) for i in range(1, 10)}
    assert all(identifier in state['phase2_candidates'] for identifier in state['required_topic_coverage'].values())
