"""Read-only aggregation; preserves failures and native timing uncertainty."""
import argparse,json,statistics
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

def main():
 p=argparse.ArgumentParser();p.add_argument('evidence',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 assert not a.output.exists(),'Do not overwrite evidence'
 runs=json.loads((a.evidence/'progress.json').read_text());requests=[];malformed=[]
 for i,line in enumerate((a.evidence/'requests.jsonl').read_text().splitlines()):
  try:requests.append(json.loads(line))
  except ValueError:malformed.append({'line':i+1,'bytes':len(line)})
 native=[]
 for run in runs:
  if run['engine']!='webview2':continue
  snapshots=json.loads((a.evidence/f"webview2-{run['repetition']}"/'native-windows.json').read_text());previous=None;changes=[]
  for snapshot in snapshots:
   windows=snapshot['windows'];label=next((x for x in windows if x['class'].startswith('WindowsForms10.STATIC.')),None)
   if not label:continue
   cover=next((x for x in windows if x['hwnd']==label['parent']),None)
   renderer=next((x for x in windows if x['class']=='Chrome_RenderWidgetHostHWND'),None)
   value=(cover['visible'] if cover else None,renderer['visible'] if renderer else None)
   if value!=previous:
    changes.append({'at':snapshot['at'],'cover_visible':value[0],'renderer_visible':value[1],
      'cover_rect':cover['rect'] if cover else None,'renderer_rect':renderer['rect'] if renderer else None})
    previous=value
  reveal=[]
  for sample in run['samples']:
   matching=[]
   for request in requests:
    if request.get('phase')!='request':continue
    q=parse_qs(urlsplit(request['path']).query)
    if q.get('__wvperf')==[sample['run']] and q.get('cycle')==[str(sample['cycle'])] and q.get('stage')==[str(sample['stage'])]:matching.append(request)
   if len(matching)!=1:
    reveal.append({'cycle':sample['cycle'],'stage':sample['stage'],'request_count':len(matching)});continue
   start=matching[0]['at'];states=[s for s in snapshots if start<=s['at']<=sample['received_monotonic']]
   show=next((s for s in states if any(x['class'].startswith('WindowsForms10.STATIC.') and x['visible'] for x in s['windows'])),None)
   exposed=next((s for s in states if (show is None or s['at']>=show['at']) and any(x['class'].startswith('WindowsForms10.STATIC.') and not x['visible'] for x in s['windows']) and any(x['class']=='Chrome_RenderWidgetHostHWND' and x['visible'] for x in s['windows'])),None)
   reveal.append({'cycle':sample['cycle'],'stage':sample['stage'],'path':sample['path'],
      'request_at':start,'cover_observed':show is not None,
      'cover_off_renderer_visible_upper_bound_ms':round((exposed['at']-start)*1000,2) if exposed else None,
      'sample_period_ms':50,'correct_pixels_established':False})
  native.append({'repetition':run['repetition'],'changes':changes,'page_reveals':reveal})
 summary=[]
 for engine in ('webview2','chrome'):
  for cycle in (0,1):
   for stage in range(4):
    sample=[s for run in runs if run['engine']==engine for s in run['samples'] if s['cycle']==cycle and s['stage']==stage]
    def median(f):return round(statistics.median(f(s) for s in sample),2)
    summary.append({'engine':engine,'cycle':cycle,'stage':stage,'n':len(sample),'path':sample[0]['path'],
     'request_ms':median(lambda s:s['nav']['requestStart']),'response_start_ms':median(lambda s:s['nav']['responseStart']),
     'response_end_ms':median(lambda s:s['nav']['responseEnd']),'dcl_ms':median(lambda s:s['nav']['domContentLoadedEventEnd']),
     'load_ms':median(lambda s:s['loaded']),'two_frame_ms':median(lambda s:s['frameReady']),
     'content_ready_ms':median(lambda s:s.get('contentReady',s['frameReady'])),
     'range_two_frame_ms':[round(min(s['frameReady'] for s in sample),2),round(max(s['frameReady'] for s in sample),2)]})
 result={'summary':summary,'native':native,'malformed_request_lines':malformed,'all_measurements_preserved':True,
   'uncertainty':'Native cover polling gives <=sampling-interval plus scheduling uncertainty. DOM/frames/visible HWNDs do not establish correct pixels.'}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
