import csv, json, os, subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\Studies\UZH-M.Sc\THESIS\design-decisions-by-LLMs")
INPUT = ROOT / "outputs" / "month4_open_coding_clustering" / "selected_trajectories_350.jsonl"
OUT = ROOT / "outputs" / "gpt_luna_light_v2"
RAW = OUT / "raw_responses"
MODEL = "gpt-5.6-luna"
PROMPT_VERSION = "open-coding-v2-requested-contract"

SYSTEM = '''You are extracting observable design-decision events from one software-agent trajectory.
Read the complete trajectory chronologically. A design decision is a meaningful choice between plausible alternatives that influences how the agent proceeds or what solution it produces. Do not use any predefined taxonomy or prior trajectories. Return zero, one, or several events. Do not force events.

Record an event only when the trajectory provides evidence that the agent selected, rejected, prioritized, or changed a meaningful option. Exclude routine commands, mechanical execution of an earlier choice, repeated unchanged execution, observations without a choice, syntax corrections, repeated final summaries, and unobservable reasoning.

Each event is one distinct choice. Merge nearby steps only when they describe or implement the same choice; start a new event when the agent makes a different choice or meaningfully changes an earlier choice. Keep source_steps minimal and ordered.

For every event, produce a reusable broad task-independent label of approximately 2–5 words describing the kind of choice, not the exact technique. Put concrete details in the neutral one-sentence decision_summary. Use EXPLICIT if the text directly states the choice, CONTEXTUAL if the choice is clearly demonstrated by actions/code/tool use but not directly stated, and UNAVAILABLE only if a choice is confirmed but cannot be reconstructed reliably. Do not create speculative events.

Return only valid JSON with exactly this shape: {"decisions":[{"source_steps":[2,3],"decision_summary":"...","decision_type_label":"...","visibility":"EXPLICIT"}]}. No markdown.'''

def write_csv(path, rows, fields):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    os.replace(tmp, path)

def load_index(path):
    if not path.exists(): return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["trial_id"]: r for r in csv.DictReader(f) if r.get("trial_id")}

def main():
    OUT.mkdir(parents=True, exist_ok=True); RAW.mkdir(exist_ok=True)
    completed_path = OUT / "completed_trajectory_index.csv"
    failed_path = OUT / "failed_trajectory_index.csv"
    events_path = OUT / "decision_events.csv"
    completed = load_index(completed_path); failed = load_index(failed_path)
    event_fields = ["trajectory_id","task_id","model","harness","decision_number","source_steps","decision_summary","decision_type_label","visibility"]
    completed_fields = ["trajectory_id","trial_id","task_id","model","harness","decision_count","raw_response_file","processed_at"]
    failed_fields = ["trajectory_id","trial_id","task_id","model","harness","error","failed_at"]
    events = []
    if events_path.exists():
        with events_path.open(encoding="utf-8-sig", newline="") as f: events = list(csv.DictReader(f))
    with INPUT.open(encoding="utf-8") as f:
        trajectories = [json.loads(line) for line in f if line.strip()]
    schema = {"type":"object","additionalProperties":False,"required":["decisions"],"properties":{"decisions":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["source_steps","decision_summary","decision_type_label","visibility"],"properties":{"source_steps":{"type":"array","items":{"type":"integer"}},"decision_summary":{"type":"string"},"decision_type_label":{"type":"string"},"visibility":{"type":"string","enum":["EXPLICIT","CONTEXTUAL","UNAVAILABLE"]}}}}}}
    for n, t in enumerate(trajectories, 1):
        tid = str(t.get("trial_id") or t.get("id") or "")
        if tid in completed: continue
        task = str(t.get("task_id") or ""); model = str(t.get("model") or ""); harness = str(t.get("harness") or t.get("agent") or "")
        raw_name = f"trajectory_{n:04d}.json"; raw_path = RAW / raw_name
        prompt = SYSTEM + "\n\nTRAJECTORY JSON:\n" + json.dumps(t, ensure_ascii=False)
        try:
            with tempfile.TemporaryDirectory(prefix="open-coding-") as d:
                sp = Path(d) / "schema.json"; op = Path(d) / "response.json"
                sp.write_text(json.dumps(schema), encoding="utf-8")
                cmd = ["codex","exec","--ephemeral","--ignore-user-config","--skip-git-repo-check","--sandbox","read-only","--cd",d,"--output-schema",str(sp),"--output-last-message",str(op),"--model",MODEL,"-"]
                r = subprocess.run(cmd, input=prompt, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=900, check=False)
                if r.returncode != 0: raise RuntimeError((r.stderr or r.stdout or f"exit {r.returncode}")[-3000:])
                data = json.loads(op.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("decisions"), list): raise ValueError("invalid response shape")
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            for i, e in enumerate(data["decisions"], 1):
                events.append({"trajectory_id":t.get("id",tid),"task_id":task,"model":model,"harness":harness,"decision_number":i,"source_steps":";".join(str(x) for x in e["source_steps"]),"decision_summary":e["decision_summary"],"decision_type_label":e["decision_type_label"],"visibility":e["visibility"]})
            completed[tid] = {"trajectory_id":t.get("id",tid),"trial_id":tid,"task_id":task,"model":model,"harness":harness,"decision_count":len(data["decisions"]),"raw_response_file":raw_name,"processed_at":datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            failed[tid] = {"trajectory_id":t.get("id",tid),"trial_id":tid,"task_id":task,"model":model,"harness":harness,"error":f"{type(e).__name__}: {e}","failed_at":datetime.now(timezone.utc).isoformat()}
        write_csv(events_path, events, event_fields)
        write_csv(completed_path, list(completed.values()), completed_fields)
        write_csv(failed_path, list(failed.values()), failed_fields)
        print(f"{n}/{len(trajectories)} completed={len(completed)} failed={len(failed)}", flush=True)
    manifest = {"input_path":str(INPUT),"output_dir":str(OUT),"model":MODEL,"run_model_label":"gpt_luna_light_v2","prompt_version":PROMPT_VERSION,"started_at":None,"finished_at":datetime.now(timezone.utc).isoformat(),"trajectory_count":len(trajectories),"completed_count":len(completed),"failed_count":len(failed),"raw_response_dir":str(RAW)}
    (OUT / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

if __name__ == "__main__": main()
