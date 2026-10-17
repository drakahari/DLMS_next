"""Explicit source WebView2 factory for existing synthetic controller checks.

No normal package test hook is installed. Legacy names remain in raw reports;
the wrapper receipt identifies the substituted renderer and instrumented scope.
"""
import argparse,importlib,json,sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--module',required=True);a,extras=p.parse_known_args()
    allowed={'tests.windows.gui_local_text_export','tests.windows.gui_workflows',
             'tests.gate1.gui_foundation','tests.server_mode.gui_text_download',
             'tests.windows.gui_attachment_backup',
             'tests.gate1.gui_study_pending','tests.gate1.gui_exam_recovery',
             'tests.blocka.gui_durable_crash','tests.blockb.gui_menu_adoption',
             'tests.settings.gui_native_roundtrip','tests.shutdown.gui_lifecycle'}
    if a.module not in allowed:raise ValueError('Only reviewed synthetic check modules')
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow  # This test process only.
    sys.argv=[a.module,*extras]
    module=importlib.import_module(a.module)
    if a.module=='tests.blocka.gui_durable_crash' and sys.platform=='win32':
        # Windows os.kill(SIGTERM) uses TerminateProcess. Limit this existing
        # test's POSIX spelling to its own disposable launcher, never a PID scan.
        import signal
        from types import SimpleNamespace
        module.signal=SimpleNamespace(SIGKILL=signal.SIGTERM)
        if '--phase' in extras and '--profile' in extras:
            phase=extras[extras.index('--phase')+1]
            if phase in ('accepted','committed'):
                from desktop.isolation import profile_paths
                root=profile_paths(extras[extras.index('--profile')+1],create=False)['root']
                if (root/f'recovery-pause-{phase}.json').exists():
                    raise ValueError('Preserved checkpoint exists; use a fresh synthetic profile for another crash case')
    # Captured quiz initialization is asynchronous after document completion.
    # Wait for its supported readiness contract before synthetic button input.
    from tests.gate1.qt_checks import QtChecks
    class ReadyChecks(QtChecks):
        def go(self,path):
            super().go(path)
            if path.startswith('/quizzes/'):
                self.wait("typeof quizRecoveryReady!=='undefined' && quizRecoveryReady===true",20)
    if hasattr(module,'QtChecks'):module.QtChecks=ReadyChecks
    result=module.main()
    print(json.dumps({'module':a.module,'renderer':'WebView2','source_instrumented':True,'normal_package':False,'return':result}),flush=True)
    return result or 0

if __name__=='__main__':raise SystemExit(main())
