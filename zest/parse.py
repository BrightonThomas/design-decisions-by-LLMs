"""Normalize raw downloads into the unified Trajectory schema (schema.py).

Trajectory formats differ per agent scaffold, so each normalizer tries a
series of known shapes and logs-and-skips anything it cannot interpret —
unknown formats are a finding, not a crash: they tell us which scaffolds
need a dedicated parser in the next iteration.

Recognized step shapes (tried in order):
  1. {"trajectory": [{"thought", "action", "observation"}, ...]}   (SWE-agent .traj)
  2. {"history"/"messages": [{"role", "content"}, ...]}            (chat-style)
  3. top-level list of {"role", "content"} messages

Usage:
    python -m zest.parse --source swebench
    python -m zest.parse --source tbench
    python -m zest.parse --source tbench21
    python -m zest.parse --source mosaic
    python -m zest.parse --source all
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .paths import NORMALIZED_DIR, RAW_MOSAIC, RAW_SWEBENCH, RAW_TBENCH20, RAW_TBENCH21, ensure_dirs
from .schema import Step, Trajectory, write_jsonl

MAX_FIELD_CHARS = 20_000  # keep pathological observations from bloating the corpus


def _clip(text) -> str | None:
    if text is None:
        return None
    s = str(text)
    if len(s) > MAX_FIELD_CHARS:
        return s[:MAX_FIELD_CHARS] + f"\n...[clipped {len(s) - MAX_FIELD_CHARS} chars]"
    return s


# ---------------------------------------------------------------- step shapes

def _steps_from_thought_action_obs(items: list) -> list[Step] | None:
    """Shape 1: explicit thought/action/observation records (SWE-agent style)."""
    if not items or not all(isinstance(it, dict) for it in items):
        return None
    keys = set().union(*(it.keys() for it in items))
    if not ({"thought", "action"} & keys or {"response", "observation"} & keys):
        return None
    steps = []
    for i, it in enumerate(items):
        steps.append(
            Step(
                index=i,
                thought=_clip(it.get("thought") or it.get("response")),
                action=_clip(it.get("action")),
                observation=_clip(it.get("observation")),
            )
        )
    return steps


def _steps_from_messages(items: list) -> list[Step] | None:
    """Shapes 2/3: role/content chat messages. Assistant turns become
    thought+action; the following tool/user turn becomes the observation."""
    if not items or not all(isinstance(it, dict) and "role" in it for it in items):
        return None

    def content_text(msg) -> str:
        c = msg.get("content", "")
        if isinstance(c, list):  # anthropic-style content blocks
            return "\n".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in c
            )
        return str(c)

    steps: list[Step] = []
    current: Step | None = None
    for msg in items:
        role = msg.get("role")
        if role == "assistant":
            if current is not None:
                steps.append(current)
            text = content_text(msg)
            calls = msg.get("tool_calls") or []
            action = "\n".join(json.dumps(c, default=str) for c in calls) or None
            current = Step(index=len(steps), thought=_clip(text), action=_clip(action))
        elif role in ("tool", "user", "system") and current is not None:
            current.observation = _clip(content_text(msg))
            steps.append(current)
            current = None
    if current is not None:
        steps.append(current)
    return steps or None


def steps_from_obj(obj) -> list[Step] | None:
    if isinstance(obj, dict):
        for key in ("trajectory", "traj", "steps"):
            if isinstance(obj.get(key), list):
                found = _steps_from_thought_action_obs(obj[key])
                if found:
                    return found
        for key in ("history", "messages"):
            if isinstance(obj.get(key), list):
                found = _steps_from_messages(obj[key])
                if found:
                    return found
    if isinstance(obj, list):
        return _steps_from_thought_action_obs(obj) or _steps_from_messages(obj)
    return None


# ------------------------------------------------------- ATIF (Terminal-Bench)

def is_atif(obj) -> bool:
    """ATIF = Agent Trajectory Interchange Format, used by tbench.ai leaderboard
    trajectory downloads (schema_version like 'ATIF-v1.6')."""
    return isinstance(obj, dict) and str(obj.get("schema_version", "")).upper().startswith("ATIF")


def _atif_observation(step: dict) -> str | None:
    """Observation sits at the STEP level (sibling of tool_calls) as
    observation.results[].content, and is the environment's reply to the
    step's tool call(s)."""
    obs = step.get("observation") or {}
    results = obs.get("results") if isinstance(obs, dict) else None
    if not results:
        return None
    parts = [str(r.get("content", "")) for r in results if isinstance(r, dict)]
    return _clip("\n".join(p for p in parts if p)) or None


def _parse_ts(ts) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def atif_trajectory(obj: dict, fallback_id: str, source: str = "tbench") -> Trajectory | None:
    """Normalize one ATIF document into a unified Trajectory.

    - system step  -> meta['system_prompt'] (once), not a decision step
    - first user   -> meta['task_prompt'] (context), not a decision step
    - agent message (plain text) -> Step(thought=message)
    - agent tool_calls -> one Step per call: thought=arguments.description,
      action=function_name + command, observation=nested results content

    Every raw step (system/user/agent alike) carries an ATIF `timestamp`.
    Step.timestamp preserves the raw value per emitted Step (when one raw
    step produces several Steps, e.g. multiple tool_calls, they share it --
    ATIF timestamps a turn, not an individual tool call). Trajectory-level
    `duration_seconds` is the span between the earliest and latest parseable
    timestamp across ALL raw steps (including system/user), so it reflects
    the true wall-clock length of the whole run, not just the agent's turns.
    """
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list):
        return None

    agent_info = obj.get("agent") or {}
    meta: dict = {
        "schema_version": obj.get("schema_version"),
        "session_id": obj.get("session_id"),
        "total_tokens": (obj.get("final_metrics") or {}).get("total_tokens"),
    }

    steps: list[Step] = []
    all_ts: list[datetime] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        step_source = raw.get("source")
        message = raw.get("message")
        tool_calls = raw.get("tool_calls") or []
        ts = raw.get("timestamp")
        parsed_ts = _parse_ts(ts)
        if parsed_ts is not None:
            all_ts.append(parsed_ts)

        if step_source == "system":
            meta.setdefault("system_prompt", _clip(message))
            continue
        if step_source == "user":
            # first user turn is the task; keep only the first as context
            meta.setdefault("task_prompt", _clip(message))
            continue

        # agent step
        if tool_calls:
            # observation is at the step level; attach it to the last tool_call
            # step so the action->observation pairing is preserved.
            step_obs = _atif_observation(raw)
            for j, tc in enumerate(tc for tc in tool_calls if isinstance(tc, dict)):
                args = tc.get("arguments") or {}
                fn = tc.get("function_name") or ""
                command = args.get("command") or args.get("input") or ""
                action = _clip(f"{fn} {command}".strip()) if (fn or command) else None
                is_last = j == len(tool_calls) - 1
                steps.append(
                    Step(
                        index=len(steps),
                        thought=_clip(args.get("description")),
                        action=action,
                        observation=step_obs if is_last else None,
                        timestamp=ts,
                    )
                )
        elif message and message != "(tool use)":
            steps.append(Step(index=len(steps), thought=_clip(message), timestamp=ts))

    if not steps:
        return None

    duration = (max(all_ts) - min(all_ts)).total_seconds() if len(all_ts) >= 2 else None
    if duration is not None and duration < 1.0:
        duration = 1.0  # some ATIF exports batch-write near-identical timestamps

    return Trajectory(
        source=source,
        agent=str(agent_info.get("name") or "unknown"),
        model=agent_info.get("model_name"),
        task_id=str(obj.get("session_id") or fallback_id),
        resolved=None,  # ATIF carries no pass/fail; outcome unknown
        steps=steps,
        duration_seconds=duration,
        meta=meta,
    )


# ------------------------------------------------------------------- sources

def _load_resolved_ids(submission_dir: Path) -> set[str]:
    results = submission_dir / "results.json"
    if not results.exists():
        return set()
    try:
        data = json.loads(results.read_text(encoding="utf-8"))
        return set(data.get("resolved", []))
    except (json.JSONDecodeError, AttributeError):
        return set()


def parse_swebench() -> list[Trajectory]:
    out, skipped = [], []
    for submission_dir in sorted(RAW_SWEBENCH.iterdir() if RAW_SWEBENCH.exists() else []):
        if not submission_dir.is_dir():
            continue
        resolved_ids = _load_resolved_ids(submission_dir)
        agent = submission_dir.name  # e.g. 20240402_sweagent_gpt4
        for f in sorted((submission_dir / "trajs").rglob("*")):
            if not f.is_file():
                continue
            try:
                obj = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                skipped.append(f.name)
                continue
            steps = steps_from_obj(obj)
            if not steps:
                skipped.append(f.name)
                continue
            task_id = f.stem
            out.append(
                Trajectory(
                    source="swebench",
                    agent=agent,
                    model=agent.split("_", 1)[-1] if "_" in agent else None,
                    task_id=task_id,
                    resolved=(task_id in resolved_ids) if resolved_ids else None,
                    steps=steps,
                    meta={"file": f.name, "submission": submission_dir.name},
                )
            )
    _report("swebench", out, skipped)
    return out


def parse_tbench() -> list[Trajectory]:
    """Parse Terminal-Bench trajectories downloaded from the tbench.ai
    leaderboard into data/raw/tbench2.0/. Files are ATIF-v1.6 JSON, saved
    with a '-traj.json' name; non-ATIF files are skipped and logged.
    Applies the `_task_map.json` map (run uuid -> task checksum) to set
    `task_id` -- the checksum is the real, cross-agent-stable task
    identifier; the ATIF document's own `session_id` field (the fallback
    when a uuid isn't in the map) is an unrelated per-run value that never
    matches across agents. Also applies `_rewards.json` (run uuid -> reward)
    to set `resolved` -- scraped from each task page's embedded trial data
    by tbench20_web.runs_for_submission; the ATIF document itself carries no
    pass/fail field, same as tbench21."""
    out, skipped = [], []
    if not RAW_TBENCH20.exists():
        _report("tbench", out, skipped)
        return out

    task_map = {}
    task_map_file = RAW_TBENCH20 / "_task_map.json"
    if task_map_file.exists():
        try:
            task_map = json.loads(task_map_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    rewards = {}
    rewards_file = RAW_TBENCH20 / "_rewards.json"
    if rewards_file.exists():
        try:
            rewards = json.loads(rewards_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    files = sorted(
        f for f in RAW_TBENCH20.rglob("*")
        if f.is_file() and f.suffix in (".json", ".jsonl")
        and f.stem.endswith("-traj") and ".cache" not in f.parts
    )
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            objs = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if f.suffix == ".jsonl"
                else [json.loads(text)]
            )
        except json.JSONDecodeError:
            skipped.append(f.name)
            continue
        uuid = f.stem.replace("-traj", "")
        for i, obj in enumerate(objs):
            if not is_atif(obj):
                skipped.append(f"{f.name}[{i}] (not ATIF)")
                continue
            traj = atif_trajectory(obj, fallback_id=f.stem)
            if traj is None:
                skipped.append(f"{f.name}[{i}] (ATIF, no usable steps)")
                continue
            if uuid in task_map:
                traj.task_id = task_map[uuid]
            if uuid in rewards:
                traj.resolved = rewards[uuid] >= 1
                traj.meta["reward"] = rewards[uuid]
            traj.meta["file"] = f.name
            out.append(traj)
    _report("tbench", out, skipped)
    return out


def parse_tbench21() -> list[Trajectory]:
    """Parse Terminal-Bench 2.1 trajectories mined from the Harbor hub into
    `data/raw/tbench2.1/<agent>__<model>/<trialId>-traj.json` (ATIF-v1.7).
    Applies the `_rewards.json` map (trial_id -> reward) to set `resolved`,
    and `_task_names.json` (trial_id -> task name) to set `task_id` -- the
    task name is the real, cross-agent-stable identifier; trial_id itself is
    unique per run/attempt and can never show overlap across agents."""
    base = RAW_TBENCH21
    out, skipped = [], []
    if not base.exists():
        _report("tbench21", out, skipped)
        return out

    rewards = {}
    rewards_file = base / "_rewards.json"
    if rewards_file.exists():
        try:
            rewards = json.loads(rewards_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    task_names = {}
    task_names_file = base / "_task_names.json"
    if task_names_file.exists():
        try:
            task_names = json.loads(task_names_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    for f in sorted(base.rglob("*-traj.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            skipped.append(f.name)
            continue
        if not is_atif(obj):
            skipped.append(f.name)
            continue
        trial_id = f.stem.replace("-traj", "")
        traj = atif_trajectory(obj, fallback_id=trial_id, source="tbench21")
        if traj is None:
            skipped.append(f.name)
            continue
        traj.task_id = task_names.get(trial_id, trial_id)
        traj.meta["file"] = f.name
        traj.meta["entry"] = f.parent.name
        if trial_id in rewards:
            traj.resolved = rewards[trial_id] >= 1
            traj.meta["reward"] = rewards[trial_id]
        out.append(traj)
    _report("tbench21", out, skipped)
    return out


_MOSAIC_TITLE_KEYS = ("title", "pr_title", "name")
_MOSAIC_BODY_KEYS = ("body", "pr_body", "description", "text")


def _first(row: dict, keys) -> str | None:
    for k in keys:
        if row.get(k):
            return str(row[k])
    return None


def parse_mosaic() -> list[Trajectory]:
    """MOSAIC rows are pull requests, not live reasoning traces. Each PR
    becomes a single-step Trajectory whose 'thought' is the PR description —
    the decision-in-practice record used for breadth, not step-level analysis.

    Agent identity lives in the HuggingFace config name (e.g.
    "PullRequests_Claude"), not in any per-row field — a row's own "author"
    is the human/bot GitHub account, not our agent label. fetch_mosaic.py
    saves one file per config, named after it, so the filename stem is the
    source of truth here."""
    out, skipped = [], []
    files = sorted(RAW_MOSAIC.glob("*.jsonl"))
    if not files:
        _report("mosaic", out, skipped)
        return out
    for path in files:
        agent = path.stem.split("_", 1)[-1] if "_" in path.stem else path.stem
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    skipped.append(f"{path.name}[{i}]")
                    continue
                title = _first(row, _MOSAIC_TITLE_KEYS)
                body = _first(row, _MOSAIC_BODY_KEYS)
                meta = {k: _clip(v) if isinstance(v, str) else v for k, v in row.items()}
                out.append(
                    Trajectory(
                        source="mosaic",
                        agent=agent,
                        model=None,
                        task_id=str(row.get("id") or row.get("pr_id") or row.get("url") or f"{path.stem}-row{i}"),
                        resolved=None,
                        steps=[Step(index=0, thought=_clip(f"{title or ''}\n\n{body or ''}".strip()))],
                        meta=meta,
                    )
                )
    _report("mosaic", out, skipped)
    return out


# --------------------------------------------------------------------- CLI

def _report(source: str, out: list, skipped: list) -> None:
    print(f"[{source}] parsed {len(out)} trajectories, skipped {len(skipped)} unrecognized files/records")
    for name in skipped[:10]:
        print(f"  skipped: {name}")
    if len(skipped) > 10:
        print(f"  ... and {len(skipped) - 10} more")


PARSERS = {
    "swebench": parse_swebench,
    "tbench": parse_tbench,
    "tbench21": parse_tbench21,
    "mosaic": parse_mosaic,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=[*PARSERS, "all"], default="all")
    args = ap.parse_args()

    ensure_dirs()
    sources = list(PARSERS) if args.source == "all" else [args.source]
    for src in sources:
        trajectories = PARSERS[src]()
        if trajectories:
            path = NORMALIZED_DIR / f"{src}.jsonl"
            n = write_jsonl(trajectories, path)
            print(f"[{src}] wrote {n} -> {path}\n")
        else:
            print(f"[{src}] nothing to write (no raw data downloaded yet?)\n")
    print("Next: python -m zest.stats")


if __name__ == "__main__":
    main()
