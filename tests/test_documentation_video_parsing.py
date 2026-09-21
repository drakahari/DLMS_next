"""The tutorial example must stay executable by the real traditional parser."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_original_sample_matches_manual_and_parses_both_answer_types(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import documentation_video_parsing as capture
    from dlms.parsing.quiz_text import parse_questions
    source = capture.SAMPLE.read_text().strip()
    manual = (ROOT / 'docs/user-manual/04-creating-and-importing-content.md').read_text()
    assert source in manual
    cleaned = '\n'.join(line for line in source.splitlines() if 'practice copy' not in line.lower())
    questions = parse_questions(cleaned)
    assert len(questions) == 2
    assert [q['correct'] for q in questions] == [['A'], ['A', 'C']]
    assert [len(q['choices']) for q in questions] == [2, 3]


def test_parsing_capture_cannot_use_an_unowned_root(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import documentation_video_parsing as capture
    from types import SimpleNamespace
    with pytest.raises(RuntimeError, match='isolated capture root'):
        capture.prepare(None, SimpleNamespace(action='parsing-source'), {}, tmp_path)
    assert not list(tmp_path.iterdir())


def test_parsing_recipes_and_naming_are_additive(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'tools'))
    import capture_demo_video_screenshots as capture
    import build_documentation_videos as batch
    _, videos, catalog = batch.load_series()
    chosen = batch.select(videos, 'parsing-pasted-text')
    assert len(chosen) == 1
    assert [s['audio_filename'] for s in chosen[0]['scenes']] == [f'{n:03}.wav' for n in range(1, 11)]
    recipes = [f for f in capture.DOCUMENTATION_FRAMES if f.action.startswith('parsing-')]
    assert [str(f.id) for f in recipes] == [str(n) for n in range(301, 309)]
    assert all(f'series:{n}' in catalog for n in range(301, 309))
