"""Additive Study mistakes source for the existing Mixed Quiz Builder."""
import sqlite3
import uuid
from flask import Blueprint, jsonify, render_template, request
from dlms.services import study_mistakes as mistakes, learning


def create_study_mistake_blueprint(*, get_db, options, publish, registry_lock, app_version, portal_title):
    bp = Blueprint('study_mistakes', __name__)

    @bp.get('/quiz-composer/study-mistakes')
    def index():
        conn = get_db()
        try:
            selected = mistakes.scope(request.args.getlist('folders'), [int(v) for v in request.args.getlist('quizzes')])
            opts = options()
            cur = conn.cursor()
            current = mistakes.pool(cur, selected, opts)
            report = mistakes.pass_report(cur, selected, current)
            page = max(1, min(int(request.args.get('page', '1')), 1000))
            start = (page - 1) * mistakes.PREVIEW_SIZE
            unavailable_page = max(1, min(int(request.args.get('unavailable_page', '1')), 1000))
            unavailable_start = (unavailable_page - 1) * mistakes.PREVIEW_SIZE
            def page_url(key, number):
                from urllib.parse import urlencode
                query = request.args.to_dict(flat=False)
                query[key] = [str(number)]
                return '/quiz-composer/study-mistakes?' + urlencode(query, doseq=True)
            return render_template('quiz/mixed-builder.html', app_version=app_version(), portal_title=portal_title(),
                                   study_mistakes=dict(scope=selected, options=mistakes.source_options(cur, opts['registry']), pool=current,
                                       pass_report=report, generation=mistakes.state(cur), request_id=uuid.uuid4().hex,
                                       preview=current['eligible'][start:start + mistakes.PREVIEW_SIZE], page=page,
                                       has_more=start + mistakes.PREVIEW_SIZE < len(current['eligible']),
                                       unavailable_preview=current['unavailable'][unavailable_start:unavailable_start + mistakes.PREVIEW_SIZE],
                                       unavailable_page=unavailable_page, unavailable_more=unavailable_start + mistakes.PREVIEW_SIZE < len(current['unavailable']),
                                       page_url=page_url), catalog=[])
        finally:
            conn.close()

    @bp.post('/api/quiz-composer/study-mistakes/pass')
    def start():
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {'scope', 'generation', 'fingerprint', 'expected_pass'}:
            raise ValueError('Reload and confirm the Study mistakes selection.')
        conn = get_db()
        try:
            with registry_lock:
                pid = mistakes.start_pass(conn, mistakes.scope(**data['scope']), options(), generation=data['generation'],
                                         fingerprint=data['fingerprint'], expected_pass=data['expected_pass'])
            return jsonify(pass_id=pid)
        finally:
            conn.close()

    @bp.post('/api/quiz-composer/study-mistakes/create')
    def create():
        data = request.get_json()
        conn = get_db()
        try:
            with registry_lock:
                opts = options()
                previous, ids = mistakes.reserve(conn, data, opts)
                if previous:
                    url = mistakes.destination(previous, opts)
                    if previous['state'] == 'published' and url:
                        return jsonify(url=url, title=data['title'], replayed=True)
                    raise mistakes.Conflict('This request is pending or its saved quiz is unavailable. Keep this request and retry after DLMS recovery; it will not create another quiz.')
                payload = [learning._question_payload_from_db(conn.cursor(), qid) for qid in ids]
                for number, question in enumerate(payload, 1):
                    question['number'] = number
                def rolled_back():
                    recovery = get_db()
                    try:
                        mistakes.release(recovery, data['request_id'])
                    finally:
                        recovery.close()
                # Immutable reservation and source revisions are checked inside
                # the publisher's quiz-row transaction before its commit.
                _, html = publish(data['title'], payload, filename_prefix='mixed_quiz', generation_kind='mixed_quiz',
                                  exam_minutes=90, snapshot_existing_assets=True, preserve_asset_sources=True,
                                  publication_record=mistakes.publication_callback(data, opts), publication_rollback=rolled_back)
                mistakes.finalize(conn, data['request_id'])
                return jsonify(url='/quizzes/' + html, title=data['title'], replayed=False)
        finally:
            conn.close()

    @bp.errorhandler(ValueError)
    @bp.errorhandler(TypeError)
    def invalid(exc):
        code = 409 if isinstance(exc, mistakes.Conflict) else 400
        message = str(exc) if isinstance(exc, ValueError) else 'Choose a valid Study mistakes selection.'
        if request.method == 'GET':
            return render_template('quiz/mixed-builder.html', app_version=app_version(), portal_title=portal_title(),
                                   catalog=[], error=message), code
        can_change = False
        data = request.get_json(silent=True)
        if isinstance(data, dict) and isinstance(data.get('request_id'), str):
            conn = get_db()
            try:
                row = conn.execute('SELECT state,generation FROM study_mistake_actions WHERE request_id=?', (data['request_id'],)).fetchone()
                can_change = (row is None or row['state'] in {'retryable','published'} or data.get('generation') != mistakes.state(conn.cursor()))
            finally:
                conn.close()
        return jsonify(error=message, can_change_request=can_change), code

    @bp.errorhandler(sqlite3.Error)
    @bp.errorhandler(OSError)
    def unavailable(_exc):
        return jsonify(error='Storage or publication is unavailable. Retry this same request. If interrupted, restart only your DLMS instance to allow recovery; nothing will be silently replaced.'), 503

    return bp
