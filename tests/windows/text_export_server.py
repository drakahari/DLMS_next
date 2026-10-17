"""Captured backend and self-driving synthetic page, without native privileges."""
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import app as dlms
from flask import request
from werkzeug.serving import make_server

out = Path(os.environ['DLMS_EXPORT_EVIDENCE'])
for i, title in enumerate(('Zulu synthetic', 'Alpha synthetic')):
    dlms._publish_quiz(title, [
        {'number': n, 'type': 'choice', 'question': f'Neutral question {i}-{n}?',
         'choices': [{'label': 'A', 'text': 'First', 'is_correct': True},
                     {'label': 'C', 'text': 'Third', 'is_correct': False}],
         'correct': ['A'], 'explanation': 'Synthetic only.'} for n in (1, 2)],
        filename_prefix=f'export_fixture_{i}', exam_minutes=5)

@dlms.app.after_request
def observe(response):
    if request.path in ('/', '/library') and response.status_code == 200:
        script = '''<script>addEventListener('load',()=>{
          if(location.pathname==='/') { if(!sessionStorage.exportStarted) setTimeout(()=>location.href='/library',1200); return; }
          if(sessionStorage.exportStarted)return; sessionStorage.exportStarted='yes';
          const before=performance.timeOrigin;
          setTimeout(()=>{
            document.querySelector('a[href="/export/all_quizzes.txt"]').click();
            const gl=document.createElement('canvas').getContext('webgl2');
            const ext=gl?.getExtension('WEBGL_debug_renderer_info');
            setTimeout(()=>fetch('/__export_observe?'+new URLSearchParams({
              sameDocument:performance.timeOrigin===before,ready:document.readyState,
              library:location.pathname==='/library',visible:!document.hidden,
              webglRenderer:gl&&ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):'unavailable'})),4000);
          },2000);
        });</script>'''
        response.set_data(response.get_data().replace(b'</body>', script.encode()+b'</body>'))
    if request.path.startswith('/export/'):
        with (out/'responses.jsonl').open('a') as log:
            log.write(json.dumps({'path':request.path,'status':response.status_code,
                'disposition':response.headers.get('Content-Disposition'),
                'type':response.headers.get('Content-Type'),'bytes':len(response.get_data())})+'\n')
    return response

@dlms.app.get('/__export_observe')
def observed():
    (out/'page-observation.json').write_text(json.dumps(dict(request.args),indent=2)+'\n')
    return '', 204

server = make_server('127.0.0.2', 0, dlms.app, threaded=True)
(out/'port').write_text(str(server.server_port))
server.serve_forever()
