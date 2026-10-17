"""Headless regular Firefox control, captured synthetic Mix Questions; no host input."""
import argparse,importlib.util,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from tests.server_mode.gui_performance import METRICS,FILTER_SCRIPT
from desktop.isolation import PROJECT

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    for leaf in ['home','config','cache','data','tmp','firefox-profile']: (out/leaf).mkdir(mode=0o700)
    env=dict(os.environ,HOME=str(out/'home'),XDG_CONFIG_HOME=str(out/'config'),XDG_CACHE_HOME=str(out/'cache'),XDG_DATA_HOME=str(out/'data'),TMPDIR=str(out/'tmp'),QUIZAPP_DATA_DIR=str(out/'server-data'),DLMS_PERF_LOG=str(out/'requests.jsonl'),DLMS_PERF_READY=str(out/'port'),DLMS_PERF_QUIZZES='24',DLMS_PERF_QUESTIONS='150')
    for key in ['PYTHONPATH','PYTHONHOME','DISPLAY','XAUTHORITY','WAYLAND_DISPLAY','WAYLAND_SOCKET']:env.pop(key,None)
    env.update(GDK_BACKEND='x11',MOZ_ENABLE_WAYLAND='0')
    server_log=(out/'server.log').open('w');server=subprocess.Popen([sys.executable,'-m','tests.server_mode.performance_server'],cwd=PROJECT,env=env,stdout=server_log,stderr=subprocess.STDOUT,start_new_session=True)
    browser=None;firefox=None;firefox_log=None
    def wait(predicate,timeout=90):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        raise TimeoutError('Firefox synthetic benchmark')
    try:
        wait(lambda:(out/'port').exists() or server.poll() is not None);assert server.poll() is None
        origin='http://127.0.0.2:'+ (out/'port').read_text()
        spec=importlib.util.spec_from_file_location('mix_firefox_bidi',PROJECT/'tests/browser/_bidi.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
        binary=shutil.which('firefox');assert binary
        firefox_log=(out/'firefox.log').open('w');argv=[binary,'--headless','--no-remote','--profile',str(out/'firefox-profile'),'--remote-debugging-port',str(port),'about:blank']
        firefox=subprocess.Popen(argv,env=env,stdout=firefox_log,stderr=subprocess.STDOUT,start_new_session=True)
        (out/'owners.json').write_text(json.dumps([{'pid':x.pid,'start_ticks':Path(f'/proc/{x.pid}/stat').read_text().rsplit(')',1)[1].split()[19]} for x in [server,firefox]]))
        deadline=time.monotonic()+30
        while browser is None:
            assert firefox.poll() is None
            if time.monotonic()>deadline:raise TimeoutError('Firefox startup')
            try:browser=module.FirefoxBidi.connect('127.0.0.1',port,timeout=.5)
            except (OSError,module.BidiError):time.sleep(.05)
        browser.start_session();browser.command('browsingContext.setViewport',{'context':browser.context,'viewport':{'width':600,'height':550},'devicePixelRatio':1})
        samples=[]
        for cache in ['cold','warm']:
            browser.command('network.setCacheBehavior',{'contexts':[browser.context],'cacheBehavior':'bypass' if cache=='cold' else 'default'})
            for repeat in range(3):
                start=time.monotonic();browser.command('browsingContext.navigate',{'context':browser.context,'url':origin+'/quiz-composer','wait':'complete'},timeout=90);finish=time.monotonic()
                metrics=json.loads(browser.evaluate(METRICS));assert browser.evaluate("document.querySelectorAll('.mixed-builder-question').length")==3600
                filters=[]
                for folder in ['synthetic folder 1','','synthetic folder 1']:
                    assert browser.evaluate(FILTER_SCRIPT.replace('FOLDER_VALUE',json.dumps(folder)))
                    wait(lambda:browser.evaluate('window.__filterMeasure?.done===true'))
                    value=json.loads(browser.evaluate('JSON.stringify(window.__filterMeasure)'));assert value['shown']==(900 if folder else 3600);filters.append(value)
                row={'cache':cache,'repeat':repeat,'finished_ms':1000*(finish-start),'browser':metrics,'filters':filters};samples.append(row)
                with (out/'samples.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
                print(cache,repeat,round(row['finished_ms']),flush=True)
        (out/'result.json').write_text(json.dumps({'samples':samples,'binary':binary,'version':subprocess.check_output([binary,'--version'],env=env,text=True).strip(),'boundary':'Regular Firefox headless, not native Omarchy browser; cold bypasses cache, warm normal cache; no wrapper or production server'},indent=2)+'\n')
    finally:
        if browser:browser.close()
        for proc in [firefox,server]:
            if proc is not None and proc.poll() is None:proc.terminate();proc.wait(timeout=15)
        if firefox_log:firefox_log.close()
        server_log.close()
    return 0
if __name__=='__main__':raise SystemExit(main())
