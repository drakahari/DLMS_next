"""Exam Plan pages and CSRF-protected, retry-safe actions."""
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Callable
from flask import Blueprint, jsonify, render_template, request, redirect, flash
from dlms.services import exam_plans as plans


@dataclass(frozen=True)
class ExamPlanDependencies:
    get_db: Callable
    options: Callable
    publish: Callable
    registry_lock: object


def create_exam_plan_blueprint(dependencies):
    get_db, options = dependencies.get_db, dependencies.options
    publish, registry_lock = dependencies.publish, dependencies.registry_lock
    bp = Blueprint('exam_plans', __name__)

    def report(cur, plan):
        return plans.summary(cur, plan, **options(cur))

    def context(cur, opts):
        saved = plans.state(cur)
        selected = plans.get(cur, saved['active_plan_id']) if saved['active_plan_id'] else None
        return dict(state=saved, selected_plan=selected, dashboard_token=plans.dashboard_selection(cur, saved=saved, selected=selected),
                    dashboard_panel_visible=opts.get('dashboard_panel_visible', True))

    def form_data():
        if request.is_json:
            return request.get_json()
        data = {key: request.form.get(key, '') for key in ('name', 'exam_date', 'calendar_timezone')}
        def number(key, cast):
            raw = request.form.get(key, '')
            try:
                return cast(raw)
            except ValueError:
                return raw
        data.update(weekdays=[int(v) if v.isdigit() else v for v in request.form.getlist('weekdays')], minutes=number('minutes', int),
                    folders=request.form.getlist('folders'), paused=request.form.get('paused') == 'on')
        for key in ('pace', 'pace_low', 'pace_high', 'reserve'):
            data[key] = number(key, float)
        return data

    @bp.route('/exam-plans')
    def index():
        conn = get_db()
        try:
            cur = conn.cursor()
            opts = options(cur)
            saved = plans.list_plans(cur)
            reports = {item['id']: plans.summary(cur, item, **opts) for item in saved if not item.get('error')}
            return render_template('learning/exam_plans.html', page='list', plans=saved, reports=reports, **context(cur, opts))
        finally:
            conn.close()

    @bp.route('/exam-plans/new', methods=['GET', 'POST'])
    @bp.route('/exam-plans/<plan_id>/edit', methods=['GET', 'POST'])
    def edit(plan_id=None):
        conn = get_db()
        try:
            cur = conn.cursor()
            plan = plans.get(cur, plan_id) if plan_id else None
            config = plan.get('config', {}) if plan else dict(plans.DEFAULTS)
            opts = options(cur)
            status, error = 200, None
            if request.method == 'POST':
                try:
                    if 'active' in request.form or 'visible' in request.form:
                        raise plans.PlanConflict('The dashboard controls changed. Reload this form before saving your selection.')
                    config = form_data()
                    revision = int(request.form.get('revision', '0'))
                    validated = plans.validate(config)
                    preview = plans.summary(cur, dict(config=validated, revision=revision, snapshot={}), **opts)
                    saved = plans.save(conn, validated, plan_id=plan_id, revision=revision, generation=request.form.get('generation'),
                                       active=request.form.get('use_dashboard') == 'on', expected_dashboard=request.form.get('dashboard_token'),
                                       known_folders=[f['key'] for f in opts['folders']], snapshot=preview['snapshot'])
                    return redirect('/exam-plans/' + saved)
                except (ValueError, sqlite3.Error, OSError) as exc:
                    conn.rollback()
                    if isinstance(exc, ValueError):
                        status, error = (409 if isinstance(exc, plans.PlanConflict) else 400), str(exc)
                    else:
                        status, error = 503, 'The plan could not be saved. Your previous saved choices are retained. Retry this form.'
            return render_template('learning/exam_plans.html', page='form', plan=plan, config=config, folders=opts['folders'],
                                   choose_dashboard=request.form.get('use_dashboard') == 'on' if request.method=='POST' else False,
                                   error=error, **context(cur, opts)), status
        finally:
            conn.close()

    @bp.route('/exam-plans/<plan_id>')
    def detail(plan_id):
        conn = get_db()
        try:
            plan = plans.get(conn.cursor(), plan_id)
            result = None if plan.get('error') else report(conn.cursor(), plan)
            changes_page = plans.change_page(result, plan, page=request.args.get('changes_page', 1, type=int), quiz=request.args.get('change_quiz', type=int), question_page=request.args.get('question_page', 1, type=int)) if result else None
            return render_template('learning/exam_plans.html', page='detail', plan=plan, report=result, changes_page=changes_page, request_id=uuid.uuid4().hex,
                                   **context(conn.cursor(), options(conn.cursor())))
        finally:
            conn.close()

    @bp.route('/api/exam-plans/preview', methods=['POST'])
    def preview():
        conn = get_db()
        try:
            result = report(conn.cursor(), dict(config=plans.validate(request.get_json()), revision=0, snapshot={}))
            return jsonify({key: result[key] for key in ('calendar', 'stats', 'workload', 'low', 'high', 'capacity', 'shortfall', 'target', 'slots', 'missing_folders', 'work_state', 'estimate_available')})
        finally:
            conn.close()

    @bp.route('/exam-plans/<plan_id>/action', methods=['POST'])
    def action(plan_id):
        conn = get_db()
        try:
            name = request.form.get('action')
            with registry_lock:
                conn.execute('BEGIN IMMEDIATE')
                snapshot = report(conn.cursor(), plans.get(conn.cursor(), plan_id))['snapshot'] if name == 'acknowledge' else None
                if name == 'acknowledge' and request.form.get('snapshot_token') != plans.digest(snapshot):
                    raise plans.PlanConflict('Study material changed after this page opened. Reload and inspect the new changes; nothing was marked as seen.')
                plans.control(conn, plan_id, name, int(request.form.get('revision', '0')), request.form.get('generation'), snapshot=snapshot,
                              expected_dashboard=request.form.get('dashboard_token'))
            return redirect('/exam-plans' if name == 'delete' else '/exam-plans/' + plan_id)
        except ValueError:
            conn.rollback()
            raise
        finally:
            conn.close()

    @bp.route('/api/exam-plans/<plan_id>/generate', methods=['POST'])
    def generate(plan_id):
        data = request.get_json()
        if not isinstance(data, dict) or set(data) != {'request_id', 'revision', 'generation', 'fingerprint', 'mode', 'count'}:
            raise ValueError('Invalid practice request. Reload the plan.')
        if not isinstance(data['mode'], str) or data['mode'] not in {'suggested', 'missed', 'focused', 'due'} or type(data['count']) is not int or not 1 <= data['count'] <= 50:
            raise ValueError('Choose 1–50 questions and a supported practice mode.')
        plans.validate_request_id(data['request_id'])
        conn = get_db()
        try:
            # Existing registry lock serializes local publication/context changes. The DB
            # reservation remains authoritative across concurrent processes and restarts.
            with registry_lock:
                cur = conn.cursor()
                plan = plans.require_version(cur, plan_id, data['revision'], data['generation'])
                old = cur.execute('SELECT * FROM exam_plan_actions WHERE request_id=?', (data['request_id'],)).fetchone()
                if old:
                    previous = plans.reserve_action(conn, plan_id, data)
                    opts = options(cur)
                    entry = next((e for e in opts['registry'] if e.get('id') == previous['quiz_id'] and e.get('html') == previous['html']), None)
                    url = plans.valid_link(entry or {}, data_folder=opts['data_folder'], quiz_folder=opts['quiz_folder'], artifact_names=opts['artifact_names'])
                    if previous['state'] == 'published' and url:
                        return jsonify(url=url, replayed=True)
                    if previous['state'] != 'retryable':
                        raise plans.PlanConflict('This publication is pending or unavailable. Retry after it finishes. If interrupted or deleted, reload after DLMS recovery and explicitly start new work. This request will not create a second quiz.')
                result = report(cur, plan)
                if data['fingerprint'] != result['fingerprint']:
                    raise plans.PlanConflict('Content or Learning Scope changed. Reload and review the updated plan before starting.')
                candidates = result['selected'] if data['mode'] == 'suggested' else result['candidates']
                if data['mode'] in {'missed', 'due'}:
                    ids = set(result[data['mode']])
                    candidates = [c for c in candidates if c['question_id'] in ids]
                # The planner has already reserved the coverage lane and applied
                # diversity across lanes. Ranking it again can displace coverage.
                selected = (candidates[:data['count']] if data['mode'] == 'suggested' else
                            plans.learning._adaptive_study_select_candidates(candidates, data['count'])) if candidates else []
                if not selected:
                    raise plans.PlanConflict('No eligible questions remain for this selection. Reload for current progress or choose optional additional practice.')
                payload = [plans.learning._question_payload_from_db(cur, c['question_id']) for c in selected]
                if not all(payload):
                    raise plans.PlanConflict('Source content changed. Reload the plan before generating practice.')
                for number, item in enumerate(payload, 1):
                    item['number'] = number
                previous = plans.reserve_action(conn, plan_id, data, retry=True)
                if previous:
                    raise plans.PlanConflict('This request is already running. Retry for its saved result.')
                def confirmed_rollback():
                    recovery = get_db()
                    try:
                        recovery.execute("UPDATE exam_plan_actions SET state='retryable' WHERE request_id=? AND generation=? AND quiz_id IS NULL", (data['request_id'], data['generation']))
                        recovery.commit()
                    finally:
                        recovery.close()
                try:
                    _, html = publish('Exam Plan — ' + plan['config']['name'], payload, filename_prefix='adaptive_study', generation_kind='adaptive_study',
                                      snapshot_existing_assets=True, publication_rollback=confirmed_rollback, publication_record=plans.publication_callback(data['request_id'], data['generation'], plan_id=plan_id, revision=data['revision'], sources={c['question_id']: result['snapshot'][str(c['question_id'])]['revision'] for c in selected}))
                except Exception:
                    # Leave the durable reservation intact: uncertain publication must
                    # never be retried as a second quiz. Existing journal handles recovery.
                    raise
                return jsonify(url='/quizzes/' + html, replayed=False)
        finally:
            conn.close()

    @bp.errorhandler(sqlite3.Error)
    @bp.errorhandler(OSError)
    def storage_failure(_exc):
        message = 'Storage is unavailable. Retry the same request; if publication was interrupted, reload after DLMS recovery. Saved history is retained.'
        if request.is_json:
            return jsonify(error=message), 503
        return render_template('learning/exam_plans.html', page='error', error=message), 503

    @bp.errorhandler(ValueError)
    def invalid(exc):
        code = 409 if isinstance(exc, plans.PlanConflict) else 400
        if request.is_json:
            return jsonify(error=str(exc)), code
        flash(str(exc), 'error')
        return render_template('learning/exam_plans.html', page='error', error=str(exc)), code

    return bp
