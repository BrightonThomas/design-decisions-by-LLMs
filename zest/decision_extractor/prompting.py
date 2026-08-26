from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_prompt(template_path: Path, schema_path: Path, trajectory: dict[str, Any]) -> str:
    template = template_path.read_text(encoding="utf-8")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if "{{SCHEMA_JSON}}" not in template or "{{TRAJECTORY_JSON}}" not in template:
        raise ValueError("Prompt template is missing a required placeholder")
    return (
        template.replace("{{SCHEMA_JSON}}", json.dumps(schema, ensure_ascii=False, indent=2))
        .replace("{{TRAJECTORY_JSON}}", json.dumps(trajectory, ensure_ascii=False, indent=2))
    )

