"""Actual Qt daily-use credential/evidence/Help journey, separate-process reopen.

Uses only newly named disposable profiles. Native chooser test selection is
application-local and never sends host-wide input. This is source Qt evidence,
not acceptance of physical keyboard input or final packaged rendering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import traceback

from tests.gate1.qt_checks import QtChecks


def rows(db: Path, table: str):
    with sqlite3.connect(db) as conn:
        return conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()


def until(q, fn, label, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        q.delay(.1)
    raise TimeoutError(label)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    parser.add_argument('--reopen', action='store_true')
    args = parser.parse_args()
    if not args.profile.startswith('dailyjourney'):
        raise ValueError('This driver accepts only dedicated dailyjourney profiles')
    q = QtChecks(args.profile, automated=True)
    db = q.paths['backend'] / 'results.db'
    report = {'profile': args.profile, 'reopen': args.reopen, 'kind': 'instrumented-frozen-Qt' if getattr(sys, 'frozen', False) else 'source-app-local-Qt'}
    record = q.paths['root'] / 'daily-certification.json'
    try:
        if args.reopen:
            prior = json.loads(record.read_text())
            cid = prior['credential_id']
            assert rows(db, 'certifications') == [tuple(r) for r in prior['certification_rows']]
            actual = [(r[0], r[1], r[2], hashlib.sha256(r[3]).hexdigest())
                      for r in rows(db, 'certification_attachments')]
            assert actual == [tuple(r) for r in prior['attachment_hashes']]
            report['separate_process_rows_and_assets_equal'] = True
        else:
            from PIL import Image
            from pypdf import PdfWriter
            badge = q.paths['tmp'] / 'daily-badge.png'
            certificate = q.paths['tmp'] / 'daily-certificate.pdf'
            Image.new('RGB', (40, 40), (0, 160, 190)).save(badge)
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=100)
            writer.write(certificate)
            report['certificate_sha256'] = hashlib.sha256(certificate.read_bytes()).hexdigest()
            q.go('/certifications/new')
            q.js("""(()=>{const f=document.querySelector('form.cert-form');
              f.elements.field_name.value='Daily-use Credential';
              f.elements.field_issuer.value='Synthetic Issuer';
              f.elements.field_earned.value='2026-01-03';
              f.elements.field_expiration.value='2028-01-03';return true})()""")
            q.window.file_selection_for_test = badge
            q.click_css('input[name=badge]')
            q.window.file_selection_for_test = certificate
            q.click_css('input[name=certificate]')
            assert q.js("document.querySelector('input[name=certificate]').files[0]?.name") == certificate.name
            q.js("document.querySelector('form.cert-form').requestSubmit();true")
            saved = until(q, lambda: next((r for r in rows(db, 'certifications')
                         if json.loads(r[1]).get('name') == 'Daily-use Credential'), None), 'credential save')
            cid = saved[0]
            report['credential_id'] = cid
            report['certification_rows'] = rows(db, 'certifications')
            report['attachment_hashes'] = [(r[0], r[1], r[2], hashlib.sha256(r[3]).hexdigest())
                                          for r in rows(db, 'certification_attachments')]
            assert len(report['attachment_hashes']) == 2
            q.go(f'/certifications/{cid}')
            current_path = q.js('location.pathname')
            for repetition in range(2):
                before = len(q.window.download_results)
                q.js("document.querySelector('a[href^=\"/certifications/attachments/\"]').click();true")
                item = until(q, lambda: next((r for r in q.window.download_results[before:]
                             if r['state'] != 'in_progress'), None), 'PDF evidence download')
                assert item['state'] == 'completed', item
                assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() == report['certificate_sha256']
                assert q.js('location.pathname') == current_path
                assert q.js("document.body.innerText.includes('Daily-use Credential')")
                assert q.window.view.isVisible() and not q.window.settings_fallback.isVisible()
            report['repeated_pdf_download_and_usable_detail'] = True
        q.go(f'/certifications/{cid}')
        assert q.js("document.body.innerText.includes('Daily-use Credential')")
        q.go('/certifications/' + cid + '/edit')
        assert q.js("document.querySelector('[name=field_earned]').value") == '2026-01-03'
        assert q.js("document.querySelector('[name=field_expiration]').value") == '2028-01-03'
        q.go('/help/certifications')
        assert q.js("document.title.toLowerCase().includes('certification')")
        assert q.js("document.querySelectorAll('main a[href], article a[href], a[href^=\"/help/\"]').length") > 0
        report['help_and_edit_navigation'] = True
        report['pass'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        traceback.print_exc()
        image = q.paths['root'] / 'daily-certification-failure.png'
        if q.window.grab().save(str(image)):
            report['failure_screenshot'] = str(image)
    finally:
        (q.paths['root'] / ('daily-certification-reopen.json' if args.reopen else 'daily-certification.json')).write_text(
            json.dumps(report, indent=2) + '\n')
        q.close()
    print(json.dumps(report, indent=2))
    return 0 if report.get('pass') else 1


if __name__ == '__main__':
    raise SystemExit(main())
