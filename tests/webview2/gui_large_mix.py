"""Bounded actual captured-UI exercise; programmatic timing, not visible acceptance."""
import argparse,json,time,statistics


def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--idle',type=int,default=30)
    p.add_argument('--scale',type=float,default=1);a=p.parse_args()
    if not 10<=a.idle<=120 or a.scale not in (1,1.25,1.5):raise ValueError('Bounded diagnostic only')
    import os
    if a.scale!=1:os.environ['QT_SCALE_FACTOR']=str(a.scale)
    import package_windows_webview2
    package_windows_webview2.ACTIVE=True
    from desktop.webview2_shell import DesktopWindow
    import desktop.shell
    desktop.shell.DesktopWindow=DesktopWindow
    from tests.gate1.qt_checks import QtChecks
    from tests.windows.normal_candidate import request,multipart
    from PySide6.QtCore import QTimer
    q=QtChecks(a.profile,automated=True);pulses=[]
    timer=QTimer();timer.setInterval(20);timer.timeout.connect(lambda:pulses.append(time.monotonic()))
    report={'source_instrumented':True,'normal_package':False,'physical_acceptance':False,'requested_qt_scale':a.scale}
    try:
        port,nonce=q.window.port,q.window.nonce
        headers={'Origin':f'http://127.0.0.1:{port}','Sec-Fetch-Site':'same-origin','X-DLMS-CSRF-Refresh':'1'}
        _,body,response=request(port,nonce,'GET','/api/csrf-token',headers=headers)
        csrf=json.loads(body)['csrf_token'];headers['Cookie']='; '.join(x.split(';',1)[0] for x in response['_set_cookies']);headers['X-CSRFToken']=csrf
        for bank in range(2):
            text='\n'.join(f'{i}. Synthetic bank {bank} question {i}?\nA. First\nC. Third\nCorrect Answer: A\n' for i in range(1,3001)).encode()
            data,media=multipart('file','synthetic.txt','text/plain',text,{'quiz_title':f'Synthetic bank {bank}','csrf_token':csrf})
            assert request(port,nonce,'POST','/process',data,headers|{'Content-Type':media})[0] in (200,302)
        q.window.resize(1280,850);q.go('/library');q.wait("document.body.innerText.includes('Synthetic bank 1')")
        start=time.monotonic();q.go('/quiz-composer');q.wait("document.querySelectorAll('[name=question_ids]').length===6000",45)
        report['mix_entry_seconds']=round(time.monotonic()-start,3)
        report['viewport']=json.loads(q.js('JSON.stringify({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,screenWidth:screen.width,screenHeight:screen.height})'))
        report['qt_view']={'width':q.window.view.width(),'height':q.window.view.height(),'dpr':q.window.view.devicePixelRatioF()}
        import ctypes
        from ctypes import wintypes
        native_hwnd=int(q.window.view.native_window.winId())
        rect=wintypes.RECT()
        user=ctypes.windll.user32
        user.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        user.GetClientRect.restype=wintypes.BOOL
        user.GetDpiForWindow.argtypes=[wintypes.HWND]
        user.GetDpiForWindow.restype=wintypes.UINT
        assert user.GetClientRect(native_hwnd,ctypes.byref(rect))
        report['native_client']={'width':rect.right-rect.left,'height':rect.bottom-rect.top,
                                 'dpi':user.GetDpiForWindow(native_hwnd)}
        q.js("document.querySelectorAll('[name=question_ids]').forEach((b,i)=>{if(i<50)b.click()});true")
        assert q.js("document.querySelectorAll('[name=question_ids]:checked').length") == 50
        q.js("document.getElementById('clearSelection').click();document.getElementById('mixedQuizTitle').value='Synthetic 日本語 6000';document.getElementById('mixedQuizTitle').dispatchEvent(new Event('input',{bubbles:true}));true")
        assert q.js("document.querySelectorAll('[name=question_ids]:checked').length") == 0
        timer.start()
        report['scroll']=q.js("""(async()=>{let intervals=[],last=performance.now(),begin=last;await new Promise(resolve=>{
          function step(now){intervals.push(now-last);last=now;scrollTo(0,((now-begin)/3000)*Math.max(0,document.body.scrollHeight-innerHeight));
          if(now-begin<3000)requestAnimationFrame(step);else resolve()}requestAnimationFrame(step)});
          intervals=intervals.slice(1).sort((a,b)=>a-b);scrollTo(0,0);return {frames:intervals.length,
          median_ms:intervals[Math.floor(intervals.length/2)],p95_ms:intervals[Math.floor(intervals.length*.95)],over25:intervals.filter(x=>x>25).length}})()""",8)
        timer.stop()
        report['native_heartbeat_max_ms']=round(max((b-a)*1000 for a,b in zip(pulses,pulses[1:])),2)
        q.window.mode_identity.setFocus();q.delay(.2);q.window.view.setFocus();q.delay(.2)
        q.window.resize(1100,760);q.delay(.2);q.window.resize(1280,850);q.delay(.3)
        assert q.js("document.getElementById('mixedQuizTitle').value")=='Synthetic 日本語 6000'
        report['input_focus_resize_retained']=True
        report['graphics']=q.js("(()=>{const g=document.createElement('canvas').getContext('webgl2');const e=g?.getExtension('WEBGL_debug_renderer_info');return {renderer:g&&e?g.getParameter(e.UNMASKED_RENDERER_WEBGL):null,version:g?g.getParameter(g.VERSION):null}})()")
        observed=[];q.window.view.command('modules',callback=observed.append)
        end=time.monotonic()+10
        while not observed and time.monotonic()<end:q.delay(.05)
        report['modules']=observed[0] if observed else None
        before=q.js('performance.timeOrigin');q.delay(a.idle)
        assert before==q.js('performance.timeOrigin')
        assert q.js("document.querySelectorAll('[name=question_ids]').length===6000 && document.getElementById('mixedQuizTitle').value==='Synthetic 日本語 6000'")
        report.update(idle_seconds=a.idle,same_document_after_idle=True,runtime=q.window.view.runtime_info,passed=True,
                      visible_corruption_absence_established=False)
    finally:
        timer.stop();q.close();q.delay(.3);report['close_complete']=q.window._close_complete
        (q.paths['root']/'wv-large-mix.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='modules'},indent=2),flush=True)
    assert report.get('passed') and report['close_complete']


if __name__=='__main__':main()
