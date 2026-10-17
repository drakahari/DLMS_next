"""Repeatable real-DBus tests with no system service activation or browser.

Requires the existing test Python/Qt and Fedora's dbus-run-session,
dbus-python/GLib (/usr/bin/python3). These are test prerequisites, not bundled
runtime dependencies. All paths/output must be a fresh directory in .gate1.
"""
import argparse,html,json,os,subprocess,sys
from pathlib import Path


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 project=Path(__file__).resolve().parents[2]
 root=args.output.absolute()
 if not root.resolve().is_relative_to(project/'.gate1'):raise ValueError('New project-local test area required')
 if len(os.fsencode(root/'bus'))>100:raise ValueError('Use a shorter .gate1 output path for the UNIX bus socket')
 root.mkdir(mode=0o700)
 for name in ('home','config','data','cache','runtime','tmp'):(root/name).mkdir(mode=0o700)
 config=root/'private-bus.conf'
 config.write_text('<busconfig><type>session</type><listen>unix:path='+html.escape(str(root/'bus'))+'</listen><auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>\n')
 env=dict(os.environ,HOME=str(root/'home'),XDG_CONFIG_HOME=str(root/'config'),XDG_DATA_HOME=str(root/'data'),XDG_CACHE_HOME=str(root/'cache'),XDG_RUNTIME_DIR=str(root/'runtime'),TMPDIR=str(root/'tmp'),QT_QPA_PLATFORM='offscreen')
 results=[]
 for mode in ('success','early','legacy','cancel','failure','timeout','unavailable','owner-loss','error','invalid-handle','client-close'):
  with (root/(mode+'.log')).open('w') as log:
   run=subprocess.run(['dbus-run-session','--config-file='+str(config),'--',sys.executable,'-m','tests.session_browser.private_bus_check',str(root/mode),mode],env=env,cwd=project,stdout=log,stderr=subprocess.STDOUT,timeout=15)
  assert run.returncode==0,(mode,(root/(mode+'.log')).read_text())
  results.append(json.loads((root/mode/'result.json').read_text()))
 (root/'results.json').write_text(json.dumps(results,indent=2)+'\n')
 print(f'{len(results)} private-session portal cases passed; no system activation directories or real browser')

if __name__=='__main__':main()
