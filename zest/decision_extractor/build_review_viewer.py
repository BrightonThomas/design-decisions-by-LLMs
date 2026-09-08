from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .core import read_jsonl


def _json_for_script(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def build_viewer(
    trajectories_path: Path,
    output_path: Path,
    predictions_path: Path | None = None,
) -> None:
    trajectories = list(read_jsonl(trajectories_path))
    predictions = list(read_jsonl(predictions_path)) if predictions_path and predictions_path.exists() else []
    payload = {"trajectories": trajectories, "predictions": predictions}
    document = VIEWER_HTML.replace("__PILOT_DATA__", _json_for_script(payload))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a self-contained trajectory review viewer")
    parser.add_argument("--trajectories", type=Path, required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_viewer(args.trajectories, args.output, args.predictions)
    print(json.dumps({"trajectories": str(args.trajectories), "output": str(args.output)}))


VIEWER_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Decision extraction review</title>
<style>
:root{--ink:#17202a;--muted:#697586;--line:#dfe4ea;--paper:#fff;--bg:#f4f6f8;--green:#1f7a5a;--green-soft:#e8f4ef;--blue:#315b9a;--blue-soft:#edf3fb;--red:#a33b3b;--red-soft:#faecec;--amber:#9a6500;--amber-soft:#fff4d6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
button,select,textarea{font:inherit}.app{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:100vh}.sidebar{background:#18232f;color:#fff;padding:22px 16px;position:sticky;top:0;height:100vh;overflow:auto}.brand{font-size:19px;font-weight:700;margin:0 8px 4px}.sub{color:#b8c4d2;font-size:13px;margin:0 8px 18px}.task-button{width:100%;text-align:left;border:0;border-radius:9px;padding:11px;margin:3px 0;background:transparent;color:#dae2eb;cursor:pointer}.task-button:hover,.task-button.active{background:#2a3b4c;color:#fff}.task-button strong{display:block}.task-button span{font-size:12px;color:#aebdca}.main{padding:24px 30px 80px;max-width:1500px}.toolbar{display:flex;gap:9px;justify-content:flex-end;margin-bottom:14px}.btn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:8px 12px;cursor:pointer}.btn.primary{background:var(--green);border-color:var(--green);color:#fff}.header,.panel{background:var(--paper);border:1px solid var(--line);border-radius:12px}.header{padding:20px 22px;margin-bottom:16px}.header h1{font-size:24px;margin:0 0 5px}.meta{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}.badge{padding:4px 8px;background:#edf0f3;border-radius:999px;font-size:12px}.layout{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(330px,.65fr);gap:16px;align-items:start}.panel{padding:18px}.panel h2{font-size:17px;margin:0 0 12px}.description{white-space:pre-wrap;max-height:210px;overflow:auto;background:#f8f9fa;border-radius:8px;padding:12px;color:#374151}.panel-summary{display:flex;align-items:center;gap:10px;cursor:pointer;list-style:none}.panel-summary::-webkit-details-marker,.step-head::-webkit-details-marker{display:none}.panel-summary h2{margin:0}.panel-summary .small{margin-left:auto}.trajectory-controls{display:flex;gap:8px;margin:12px 0}.step{border:1px solid var(--line);border-radius:10px;margin:10px 0;overflow:hidden;scroll-margin-top:14px}.step.decision{border-color:#e2b858;box-shadow:0 0 0 2px var(--amber-soft)}.step-head{display:flex;align-items:center;padding:7px 11px;background:#f7f8fa;font-weight:650;cursor:pointer;list-style:none}.step-head:before{content:'▸';margin-right:7px;color:var(--muted)}.step[open]>.step-head:before{content:'▾'}.step-head span:first-child{margin-right:auto}.step-fields{padding:4px 12px 11px}.field{margin-top:9px}.field-name{font-size:11px;font-weight:750;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}.field-text{white-space:pre-wrap;overflow-wrap:anywhere;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px;background:#fbfcfd;border-left:3px solid #ccd4dd;padding:7px 9px}.empty{color:#929aa4;font-style:italic}.event{border:1px solid var(--line);border-left:4px solid var(--blue);border-radius:9px;padding:12px;margin:10px 0;cursor:pointer}.event:hover{background:#fafcff}.event-title{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.event-title strong{margin-right:auto}.cat{background:var(--blue-soft);color:var(--blue);font-weight:750}.reason{background:var(--green-soft);color:var(--green);font-weight:750}.event p{margin:7px 0}.evidence{font-size:12px;color:#4c5867;border-top:1px solid var(--line);padding-top:7px}.review{display:grid;grid-template-columns:130px 1fr;gap:8px;margin-top:9px}.review textarea{width:100%;min-height:58px;border:1px solid var(--line);border-radius:7px;padding:7px}.review select{border:1px solid var(--line);border-radius:7px;padding:6px;background:#fff}.notice{border-radius:9px;padding:11px 12px;background:var(--amber-soft);color:#6e4a00}.notice.error{background:var(--red-soft);color:var(--red)}.summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}.metric{border:1px solid var(--line);border-radius:8px;padding:10px}.metric strong{font-size:20px;display:block}.sticky{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto}.small{font-size:12px;color:var(--muted)}
.pilot-analysis{border-top:2px solid var(--line);margin-top:20px;padding-top:17px}.pilot-analysis h2{margin-bottom:5px}.analysis-note{font-size:12px;color:var(--muted);margin:0 0 13px}.analysis-block{border:1px solid var(--line);border-radius:9px;margin:10px 0;background:#fbfcfd;overflow:hidden}.analysis-block>summary{cursor:pointer;font-weight:700;padding:10px 12px;list-style:none}.analysis-block>summary::-webkit-details-marker{display:none}.analysis-block>summary:before{content:'▸';display:inline-block;margin-right:7px;color:var(--muted)}.analysis-block[open]>summary:before{content:'▾'}.analysis-body{padding:0 10px 11px}.analysis-body h3{font-size:13px;margin:11px 0 5px}.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:7px;background:#fff}.dist-table{border-collapse:collapse;width:100%;min-width:680px;font-size:11px;line-height:1.25}.dist-table th,.dist-table td{border-bottom:1px solid var(--line);padding:6px 7px;text-align:right;white-space:nowrap}.dist-table tr:last-child td{border-bottom:0}.dist-table th{background:#eef2f6;color:#435063;font-weight:750}.dist-table th:first-child,.dist-table td:first-child{text-align:left;position:sticky;left:0;background:#fff;max-width:180px;overflow:hidden;text-overflow:ellipsis}.dist-table th:first-child{background:#eef2f6}.table-caption{font-size:11px;color:var(--muted);margin:5px 1px 11px}
@media(max-width:950px){.app{grid-template-columns:1fr}.sidebar{position:relative;height:auto}.layout{grid-template-columns:1fr}.sticky{position:relative;max-height:none}.main{padding:16px}}
</style>
</head>
<body>
<div class="app"><aside class="sidebar"><div class="brand">Decision review</div><div class="sub">10-trajectory pilot</div><div id="taskList"></div></aside>
<main class="main"><div class="toolbar"><button class="btn" id="prev">Previous</button><button class="btn" id="next">Next</button><button class="btn primary" id="export">Export review JSON</button></div><section id="content"></section></main></div>
<script id="pilot-data" type="application/json">__PILOT_DATA__</script>
<script>
const DATA=JSON.parse(document.getElementById('pilot-data').textContent);let current=0;
const taskListEl=document.getElementById('taskList'),contentEl=document.getElementById('content');
const prevButton=document.getElementById('prev'),nextButton=document.getElementById('next'),exportButton=document.getElementById('export');
let state={};try{state=JSON.parse(localStorage.getItem('decision-review-v1')||'{}')}catch(error){state={}}
const predByTrial=new Map(DATA.predictions.map(p=>[p.trial_id,p]));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function save(){try{localStorage.setItem('decision-review-v1',JSON.stringify(state))}catch(error){}}
function reviewKey(t,e){return `${t.trial_id}:${e.event_id}`}
function renderList(){taskListEl.innerHTML=DATA.trajectories.map((t,i)=>`<button class="task-button ${i===current?'active':''}" data-i="${i}"><strong>${i+1}. ${esc(t.task_id.replace('terminal-bench/',''))}</strong><span>${esc(t.harness)} · ${esc(t.model)}</span></button>`).join('');document.querySelectorAll('.task-button').forEach(b=>b.onclick=()=>{current=+b.dataset.i;render()})}
function field(name,value){return `<div class="field"><div class="field-name">${name}</div><div class="field-text ${value?'':'empty'}">${value?esc(value):'Not recorded'}</div></div>`}
const CATEGORY_LABELS={D1:'Diagnostic / analytical',D2:'Algorithm / optimisation',D3:'Shape / representation',D4:'Parameter / configuration',D5:'Implementation / efficiency',D6:'Recovery / revision',D7:'Verification',D8:'Termination / submission'};
const CATEGORY_CODES=Object.keys(CATEGORY_LABELS);
const percent=(count,total)=>total?`${Math.round(100*count/total)}%`:'—';
function pilotGroups(fieldName){const groups=new Map();DATA.trajectories.forEach(t=>{const p=predByTrial.get(t.trial_id);if(!p?.valid)return;const name=t[fieldName]||'Unknown',events=p.extraction?.events||[];if(!groups.has(name))groups.set(name,{name,trajectories:0,events:[]});const group=groups.get(name);group.trajectories+=1;group.events.push(...events)});return [...groups.values()].sort((a,b)=>a.name.localeCompare(b.name))}
function categoryTable(fieldName){const rows=pilotGroups(fieldName).map(g=>`<tr><td title="${esc(g.name)}">${esc(g.name)}</td><td>${g.trajectories}</td><td>${g.events.length}</td>${CATEGORY_CODES.map(code=>`<td>${percent(g.events.filter(e=>e.primary_category===code).length,g.events.length)}</td>`).join('')}</tr>`).join('');return `<div class="table-wrap"><table class="dist-table"><thead><tr><th>${fieldName==='harness'?'Harness':'Model'}</th><th>Runs</th><th>Events</th>${CATEGORY_CODES.map(code=>`<th title="${esc(CATEGORY_LABELS[code])}">${code}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div><p class="table-caption">Cells are percentages of primary decision events within each row. Hover over D1–D8 for category names.</p>`}
function visibilityTable(fieldName){const rows=pilotGroups(fieldName).map(g=>{const count=(key,value)=>g.events.filter(e=>e[key]===value).length;return `<tr><td title="${esc(g.name)}">${esc(g.name)}</td><td>${g.trajectories}</td><td>${g.events.length}</td><td>${percent(count('decision_visibility','STATED'),g.events.length)}</td><td>${percent(count('decision_visibility','BEHAVIOURAL'),g.events.length)}</td><td>${percent(count('reason_visibility','EXPLICIT'),g.events.length)}</td><td>${percent(count('reason_visibility','CONTEXTUAL'),g.events.length)}</td><td>${percent(count('reason_visibility','UNAVAILABLE'),g.events.length)}</td></tr>`}).join('');return `<div class="table-wrap"><table class="dist-table"><thead><tr><th>${fieldName==='harness'?'Harness':'Model'}</th><th>Runs</th><th>Events</th><th>Stated</th><th>Behavioural</th><th>Explicit reason</th><th>Contextual reason</th><th>No visible reason</th></tr></thead><tbody>${rows}</tbody></table></div><p class="table-caption">Decision and reason visibility are calculated separately; each set of visibility percentages uses events within the row as its denominator.</p>`}
function pilotAnalysis(){const valid=DATA.trajectories.filter(t=>predByTrial.get(t.trial_id)?.valid),eventCount=valid.reduce((n,t)=>n+(predByTrial.get(t.trial_id)?.extraction?.events?.length||0),0);return `<section class="pilot-analysis"><h2>Pilot distributions</h2><p class="analysis-note">RQ1/RQ2 descriptive results across ${valid.length} valid trajectories and ${eventCount} candidate events. These are unreviewed extractor outputs, not accuracy estimates.</p><details class="analysis-block" open><summary>RQ1 · Decision categories</summary><div class="analysis-body"><h3>By harness</h3>${categoryTable('harness')}<h3>By model</h3>${categoryTable('model')}</div></details><details class="analysis-block" open><summary>RQ2 · Decision and reason visibility</summary><div class="analysis-body"><h3>By harness</h3>${visibilityTable('harness')}<h3>By model</h3>${visibilityTable('model')}</div></details></section>`}
function render(){renderList();const t=DATA.trajectories[current],p=predByTrial.get(t.trial_id),events=p?.extraction?.events||[],decisionSteps=new Set(events.flatMap(e=>e.source_steps||[]));
let status;if(!p)status=`<div class="notice">Extraction pending. The trajectory is ready, but no model output has been loaded.</div>`;else if(!p.valid)status=`<div class="notice error"><strong>Invalid extraction</strong><br>${esc((p.errors||[]).map(e=>e.message).join(' · '))}</div>`;else status=`<div class="notice">Structured extraction passed schema and source-evidence validation.</div>`;
const steps=t.steps.map(s=>`<details class="step ${decisionSteps.has(s.step)?'decision':''}" id="step-${s.step}" open><summary class="step-head"><span>Step ${s.step}</span>${decisionSteps.has(s.step)?'<span class="badge">Decision evidence</span>':''}</summary><div class="step-fields">${field('Thought',s.thought)}${field('Action',s.action)}${field('Observation',s.observation)}</div></details>`).join('');
const eventHtml=events.length?events.map(e=>{const k=reviewKey(t,e),r=state[k]||{};return `<article class="event" data-step="${e.source_steps[0]}"><div class="event-title"><strong>${esc(e.event_id)} · ${esc(e.decision_summary)}</strong><span class="badge cat">${esc(e.primary_category)}</span><span class="badge reason">${esc(e.primary_reason)}</span></div><p><b>Selected:</b> ${esc(e.selected_option)}</p><p><b>Reason:</b> ${esc(e.reason_summary||'No observable reason')}</p><p class="small">Steps ${esc(e.source_steps.join(', '))} · ${esc(e.decision_visibility)} decision · ${esc(e.reason_visibility)} reason · ${esc(e.confidence)} confidence</p><div class="evidence">${e.evidence.map(x=>`Step ${x.step}, ${esc(x.field)}: “${esc(x.excerpt)}”`).join('<br>')}</div><div class="review"><select data-key="${esc(k)}"><option value="">Review…</option><option ${r.status==='accepted'?'selected':''} value="accepted">Accepted</option><option ${r.status==='corrected'?'selected':''} value="corrected">Corrected</option><option ${r.status==='rejected'?'selected':''} value="rejected">Rejected</option></select><textarea data-key="${esc(k)}" placeholder="Optional correction or note">${esc(r.note||'')}</textarea></div></article>`}).join(''):'<div class="notice">No decision events are currently available for this trajectory.</div>';
contentEl.innerHTML=`<header class="header"><h1>${esc(t.task_id.replace('terminal-bench/',''))}</h1><div class="small">${esc(t.trial_id)}</div><div class="meta"><span class="badge">${esc(t.category)}</span><span class="badge">${esc(t.difficulty)}</span><span class="badge">${esc(t.harness)}</span><span class="badge">${esc(t.model)}</span><span class="badge">${t.steps.length} steps</span><span class="badge">Resolved</span></div></header><div class="layout"><div><section class="panel"><h2>Task description</h2><div class="description">${esc(t.task_description)}</div></section><details class="panel trajectory-panel" id="trajectoryPanel" style="margin-top:16px" open><summary class="panel-summary"><h2>Complete trajectory</h2><span class="small">${t.steps.length} collapsible steps</span></summary><div class="trajectory-controls"><button class="btn" id="expandSteps">Expand all</button><button class="btn" id="collapseSteps">Collapse all</button></div><div id="trajectorySteps">${steps}</div></details></div><aside class="panel sticky"><h2>Extracted decisions</h2><div class="summary"><div class="metric"><strong>${events.length}</strong><span>events</span></div><div class="metric"><strong>${new Set(events.map(e=>e.primary_category)).size}</strong><span>categories</span></div><div class="metric"><strong>${p?.valid?'Yes':'—'}</strong><span>valid</span></div></div>${status}${eventHtml}${pilotAnalysis()}</aside></div>`;
document.getElementById('expandSteps').onclick=()=>document.querySelectorAll('#trajectorySteps .step').forEach(step=>step.open=true);
document.getElementById('collapseSteps').onclick=()=>document.querySelectorAll('#trajectorySteps .step').forEach(step=>step.open=false);
document.querySelectorAll('.event').forEach(e=>e.onclick=x=>{if(!x.target.matches('select,textarea')){const panel=document.getElementById('trajectoryPanel'),step=document.getElementById('step-'+e.dataset.step);panel.open=true;if(step)step.open=true;step?.scrollIntoView({behavior:'smooth'})}});
document.querySelectorAll('select[data-key]').forEach(x=>x.onchange=()=>{state[x.dataset.key]={...(state[x.dataset.key]||{}),status:x.value};save()});document.querySelectorAll('textarea[data-key]').forEach(x=>x.oninput=()=>{state[x.dataset.key]={...(state[x.dataset.key]||{}),note:x.value};save()});}
prevButton.onclick=()=>{current=(current-1+DATA.trajectories.length)%DATA.trajectories.length;render()};nextButton.onclick=()=>{current=(current+1)%DATA.trajectories.length;render()};
exportButton.onclick=()=>{const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),reviews:state},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='decision-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};render();
</script>
</body></html>'''


if __name__ == "__main__":
    main()
