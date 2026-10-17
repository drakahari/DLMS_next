"""Actionable real captured Certification errors without native Settings authority."""
import argparse,json,time


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);a=p.parse_args()
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    q=QtChecks(a.profile,automated=True);report={'source_instrumented':True,'physical_acceptance':False}
    try:
        q.go('/certifications/new')
        q.js("(()=>{let f=document.querySelector('form.cert-form');f.elements.field_name.value='';f.noValidate=true;f.submit();return true})()")
        end=time.monotonic()+15
        while q.window.view.page().last_http_status!=400 and time.monotonic()<end:q.delay(.05)
        assert q.window.view.page().last_http_status==400
        q.wait("document.readyState==='complete' && Boolean(document.querySelector('form.cert-form'))")
        assert q.window.view.isVisible() and q.window.view.isEnabled()
        assert not q.window.settings_panel.isVisible() and not q.window.settings_fallback.isVisible()
        assert not q.window._settings_ready('backup')
        # Hidden controls can retain QWidget enabled state; authority is the
        # verified current Settings document. Even a synthetic click must fail.
        q.window.settings_buttons['create_backup'].click();q.delay(.1)
        assert not q.window._backup_creating and not q.window.download_results
        report.update(certification_http400=True,actionable_form_visible=True,native_settings_disabled=True)
        q.go('/')
        report['passed']=True
    finally:
        q.close();q.delay(.3)
        report['close_complete']=q.window._close_complete
        (q.paths['root']/'wv-cert-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    assert report.get('passed') and report['close_complete']


if __name__=='__main__':main()
