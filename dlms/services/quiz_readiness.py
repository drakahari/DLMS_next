"""Content readiness is independent of safe, lossless portable preservation."""

import json
import re

ANSWER_ENCODING = 'choice-labels-v1'


def question_issues(question):
    reasons = []
    qtype = question.get('type') or 'choice'
    if not str(question.get('question') or '').strip() and not question.get('image_url'):
        reasons.append('Question text is empty.')
    if qtype == 'hotspot':
        if not question.get('_legacy_hotspot') and (not question.get('image_url') or not question.get('target')):
            reasons.append('The hotspot image or target is missing.')
        return reasons
    if qtype == 'matching':
        from .content_packs import _matching_record_validation_errors
        reasons.extend(_matching_record_validation_errors(question.get('pairs'), context='Matching question', left_key='left', right_key='right', record_name='pair'))
        return reasons
    if qtype != 'choice':
        return reasons + ['This question type is not supported for graded use.']
    choices = question.get('choices') or []
    if not 1 <= len(choices) <= 26:
        reasons.append('A choice question needs between 1 and 26 choices.')
    labels = [c.get('label') for c in choices]
    if len(set(labels)) != len(labels):
        reasons.append('Choice labels are repeated; answers cannot distinguish those choices.')
    if any(not isinstance(label, str) or not re.fullmatch('[A-Z]', label) for label in labels):
        reasons.append('Choice labels must be single uppercase letters; gaps are allowed.')
    if any(not str(c.get('text') or '').strip() for c in choices):
        reasons.append('A choice has empty answer text.')
    if not any(c.get('is_correct') for c in choices):
        reasons.append('No correct answer is marked.')
    return reasons


def quiz_readiness(cur, quiz_id):
    rows = cur.execute('SELECT id,question_number,question_text,question_type,media_json FROM questions WHERE quiz_id=? ORDER BY question_number,id', (quiz_id,)).fetchall()
    issues, actual_labels_required = [], False
    for position, row in enumerate(rows, 1):
        question = {'type': row['question_type'] or 'choice', 'question': row['question_text']}
        try:
            media = json.loads(row['media_json'] or '{}')
            if isinstance(media, dict):
                question.update(media)
        except (TypeError, ValueError):
            issues.append({'position': position, 'number': row['question_number'], 'reason': 'Question media metadata is invalid.'})
        # Legacy image-hotspot records use a one-choice DB surrogate. Geometry
        # and artifact validation remain enforced by their existing save paths.
        if str(row['question_text'] or '').endswith('[Image hotspot]'):
            question['type'] = 'hotspot'
            question['_legacy_hotspot'] = True
        if question['type'] == 'matching':
            question['pairs'] = [{'left': r[0], 'right': r[1]} for r in cur.execute('SELECT left_text,right_text FROM matching_pairs WHERE question_id=? ORDER BY pair_order,id', (row['id'],))]
        elif question['type'] == 'choice':
            question['choices'] = [dict(r) for r in cur.execute('SELECT label,text,is_correct FROM choices WHERE question_id=? ORDER BY choice_order,label,id', (row['id'],))]
            if any(type(c['is_correct']) is not int or c['is_correct'] not in (0, 1) for c in question['choices']):
                issues.append({'position': position, 'number': row['question_number'], 'reason': 'A stored correct-answer flag is invalid.'})
            labels = [c['label'] for c in question['choices']]
            actual_labels_required |= labels != [chr(65+i) for i in range(len(labels))]
        issues.extend({'position': position, 'number': row['question_number'], 'reason': reason} for reason in question_issues(question))
    if not rows:
        issues.append({'position': None, 'number': None, 'reason': 'The quiz has no questions.'})
    return {'ready': not issues, 'issues': issues, 'actual_labels_required': actual_labels_required}


def require_ready(cur, quiz_id, *, encoding=None, check_encoding=False):
    from .attempts import LearningPayloadError
    status = quiz_readiness(cur, quiz_id)
    if not status['ready']:
        first = status['issues'][0]
        location = f" Question {first['position']}:" if first['position'] else ''
        raise LearningPayloadError('This quiz needs review before graded Study or Exam.' + location + ' ' + first['reason'] + f' Review and edit it in Quiz Library (quiz ID {quiz_id}). Saved history and browser recovery are retained.')
    if check_encoding and status['actual_labels_required'] and encoding != ANSWER_ENCODING:
        raise LearningPayloadError('This quiz uses nonpositional choice labels. This older page or retained queue cannot safely encode its answers. Keep recovery data; use a current quiz page for new work. Historical answers were not changed.')
    return status
