import csv,json,os,subprocess,tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(r'D:\Studies\UZH-M.Sc\THESIS\design-decisions-by-LLMs'); INPUT=ROOT/'outputs/month4_open_coding_clustering/selected_trajectories_350.jsonl'; OUT=ROOT/'outputs/gpt_luna_light_v2'; RAW=OUT/'raw_responses'; MODEL='gpt-5.6-luna'
SYSTEM=open(ROOT/'annotations/open_coding_extractor_prompt_v2.md',encoding='utf-8').read()+"\n\nReturn ONLY JSON with exactly {\"decisions\":[{\"source_steps\":[2,3],\"decision_summary\":\"...\",\"decision_type_label\":\"...\",\"visibility\":\"EXPLICIT\"}]} and no markdown."
PY= r'C:\Users\Brighton\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
def rows(p):
    if not p.exists(): return {}
    with p.open(encoding='utf-8-sig',newline='') as f:return {r['trial_id']:r for r in csv.DictReader(f) if r.get('trial_id')}
def write(p,rs,fields):
    q=p.with_suffix(p.suffix+'.tmp')
    with q.open('w',encoding='utf-8-sig',newline='') as f: w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
    os.replace(q,p)
def one(n,t):
    tid=str(t.get('trial_id') or t.get('id')); prompt=SYSTEM+'\n\nTRAJECTORY JSON:\n'+json.dumps(t,ensure_ascii=False)
    schema={'type':'object','additionalProperties':False,'required':['decisions'],'properties':{'decisions':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['source_steps','decision_summary','decision_type_label','visibility'],'properties':{'source_steps':{'type':'array','items':{'type':'integer'}},'decision_summary':{'type':'string'},'decision_type_label':{'type':'string'},'visibility':{'type':'string','enum':['EXPLICIT','CONTEXTUAL','UNAVAILABLE']}}}}}}
    with tempfile.TemporaryDirectory(prefix='open-coding-') as d:
        sp=Path(d)/'schema.json';op=Path(d)/'response.json';sp.write_text(json.dumps(schema),encoding='utf-8')
        cmd=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--sandbox','read-only','--cd',d,'--output-schema',str(sp),'--output-last-message',str(op),'--model',MODEL,'-']
        r=subprocess.run(cmd,input=prompt,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=900)
        if r.returncode: raise RuntimeError((r.stderr or r.stdout or str(r.returncode))[-2000:])
        data=json.loads(op.read_text(encoding='utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('decisions'),list): raise ValueError('invalid response')
    name=f'trajectory_{n:04d}.json';(RAW/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    task=str(t.get('task_id') or '');model=str(t.get('model') or '');h=str(t.get('harness') or t.get('agent') or '')
    ev=[{'trajectory_id':t.get('id',tid),'task_id':task,'model':model,'harness':h,'decision_number':i,'source_steps':';'.join(map(str,e['source_steps'])),'decision_summary':e['decision_summary'],'decision_type_label':e['decision_type_label'],'visibility':e['visibility']} for i,e in enumerate(data['decisions'],1)]
    done={'trajectory_id':t.get('id',tid),'trial_id':tid,'task_id':task,'model':model,'harness':h,'decision_count':len(ev),'raw_response_file':name,'processed_at':datetime.now(timezone.utc).isoformat()}
    return done,ev,None
def main():
    OUT.mkdir(exist_ok=True);RAW.mkdir(exist_ok=True);ts=[json.loads(x) for x in INPUT.read_text(encoding='utf-8').splitlines() if x.strip()]; cp=OUT/'completed_trajectory_index.csv';fp=OUT/'failed_trajectory_index.csv';ep=OUT/'decision_events.csv';done=rows(cp);fail=rows(fp);events=[]
    if ep.exists():
        with ep.open(encoding='utf-8-sig',newline='') as f:events=list(csv.DictReader(f))
    pending=[(i,t) for i,t in enumerate(ts,1) if str(t.get('trial_id') or t.get('id')) not in done]
    df=['trajectory_id','trial_id','task_id','model','harness','decision_count','raw_response_file','processed_at']; ff=['trajectory_id','trial_id','task_id','model','harness','error','failed_at']; ef=['trajectory_id','task_id','model','harness','decision_number','source_steps','decision_summary','decision_type_label','visibility']
    with ThreadPoolExecutor(max_workers=8) as ex:
        fs={ex.submit(one,n,t):(n,t) for n,t in pending}
        for k,f in enumerate(as_completed(fs),1):
            n,t=fs[f];tid=str(t.get('trial_id') or t.get('id'));task=str(t.get('task_id') or '');model=str(t.get('model') or '');h=str(t.get('harness') or t.get('agent') or '')
            try: d,ev,_=f.result();done[tid]=d;events.extend(ev)
            except Exception as e: fail[tid]={'trajectory_id':t.get('id',tid),'trial_id':tid,'task_id':task,'model':model,'harness':h,'error':f'{type(e).__name__}: {e}','failed_at':datetime.now(timezone.utc).isoformat()}
            write(ep,events,ef);write(cp,list(done.values()),df);write(fp,list(fail.values()),ff);print(f'{len(done)}/{len(ts)} completed={len(done)} failed={len(fail)}',flush=True)
    (OUT/'run_manifest.json').write_text(json.dumps({'input_path':str(INPUT),'output_dir':str(OUT),'model':MODEL,'run_model_label':'gpt_luna_light_v2','prompt_version':'open-coding-v2-requested-contract','finished_at':datetime.now(timezone.utc).isoformat(),'trajectory_count':len(ts),'completed_count':len(done),'failed_count':len(fail)},indent=2),encoding='utf-8')
if __name__=='__main__':main()
