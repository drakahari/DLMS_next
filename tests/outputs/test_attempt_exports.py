"""Attempt export selection is scoped to the requested saved attempt."""
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from flask import Flask
from dlms.routes.anki import export_anki_genanki


def invoke(selection, *, omitted=False):
    rows=[dict(attempt_question_number=n,question_text=f'Question {n}',choices_text='A. Right\nB. Wrong',correct_text='A. Right',quiz_id=7,quiz_title='Synthetic') for n in (1,2)]
    export=Mock(return_value='private.apkg')
    deps=NS(load_attempt_missed_rows=Mock(return_value=rows),attempt_history_context=lambda:({}, {}, {}),
        make_safe_anki_deck_name=lambda a,b:a,make_safe_anki_download_name=lambda a,b:a+'.apkg',
        export_quiz_to_apkg=export,send_temp_anki_package=lambda a,b:{'path':a})
    data={'attempt_id':'selected-attempt'}
    if not omitted:data['attempt_question_numbers']=selection
    with Flask(__name__).test_request_context(json=data):result=export_anki_genanki(deps)
    deps.load_attempt_missed_rows.assert_called_once_with('selected-attempt')
    return result,export


def test_only_selected_missed_question_is_exported():
    result,export=invoke([2]);assert result=={'path':'private.apkg'}
    assert [r['front'] for r in export.call_args.args[1]]==['Question 2\n\nA. Right\nB. Wrong']


def test_duplicate_selection_does_not_duplicate_notes_and_order_is_source_order():
    _,export=invoke([2,1,2]);assert [r['front'].split('\n')[0] for r in export.call_args.args[1]]==['Question 1','Question 2']


@pytest.mark.parametrize('selection',[[],[True],[0],[-1],['2'],'2',[99],[1,99],None])
def test_invalid_or_stale_selection_cannot_expand_export(selection):
    result,export=invoke(selection);assert result[1] in (400,409);export.assert_not_called()


def test_existing_attempt_only_client_keeps_all_missed_export():
    _,export=invoke(None,omitted=True);assert len(export.call_args.args[1])==2
