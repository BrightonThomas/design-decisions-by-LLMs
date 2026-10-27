# `/show_dx` for OpenCode

This integration analyzes a **saved OpenCode Desktop session on demand**. It does
not capture a live stream. The command reads the complete current session from
the already-running Desktop service before posting an analysis request, then
calls the local `dx` MCP server. No separate OpenCode CLI installation is needed.
The server uses the
general D1–D8 definitions in `annotations/codebook_v2.md` and returns an HTML
review with links from every decision to its recorded source steps.

## Requirements

- OpenCode V2, which supports `.opencode/plugins/` command registration and
  local MCP servers.
- The repository's Python environment (`uv sync` installs the `mcp` package).
- The local OpenCode API client (`npm ci --prefix .opencode` after a fresh clone).
- Ollama running locally and access to the configured extraction model. The
  default is `gpt-oss:120b-cloud`; the machine must be signed in to Ollama for
  that cloud model. The analysis model can differ from the model that created
  the session.

The default cloud extractor receives the recorded task text and trajectory,
including any sensitive content the session contains. Use a local Ollama model
instead if that information must not leave the machine.

Open this repository in OpenCode Desktop after installing dependencies. OpenCode
loads `opencode.jsonc` and `.opencode/plugins/show-dx.ts` automatically. Check
`/mcps` in Desktop to confirm that `dx` is connected. Use the normal OpenCode
workflow for a task and then enter:

```
/show_dx
```

The command snapshots the full session through the Desktop service's export API,
then posts only `/show_dx — Analyze this session's design decisions.` in chat.
A session `context` hook supplies the operational instructions to the outgoing
model request without storing them as the visible user prompt. Request metadata
links that short message to its saved snapshot. Instructions apply only while
that message is the latest committed user request, including tool continuations;
they do not apply to later coding requests or other sessions.

The OpenCode model calls `dx_analyze_snapshot_file`. Its reply reports decision
counts, up to ten decision summaries with source steps, and a path to the
self-contained HTML review. Open that file in a
browser. Results and snapshots are saved under `outputs/opencode_dx/`, which is
already excluded from Git.

Restart OpenCode Desktop after updating the plugin. Existing long command
messages are not changed. This is a visual cleanup, not token reduction: the
model still receives the instructions, and tool activity/results remain visible.
Earlier DX requests and their replies are excluded from subsequent trajectory
analysis, including both the old long prompt and the new short message.

Set `DX_OLLAMA_MODEL` before starting OpenCode to choose another Ollama model.
Set `DX_OLLAMA_URL` to change the Ollama API endpoint (default:
`http://127.0.0.1:11434/api/generate`). The model must return JSON as directed
by the prompt; Ollama cloud models do not currently support constrained schema
output. `DX_OUTPUT_DIR` can relocate snapshots and results, but the OpenCode
plugin and MCP server must receive the same value.

## Output and limits

Each result contains the normalized recorded trajectory, D1–D8 decisions,
visibility (`EXPLICIT`, `CONTEXTUAL`), exact evidence excerpts,
and source message/part IDs. The HTML view has collapsible recorded steps and
links from decisions to those steps. A repeated analysis of the same recorded
coding trajectory with the same model and codebook reuses its saved result,
even if an earlier `/show_dx` exchange is now present in the session.

Long sessions are analyzed in overlapping chunks. The extractor's raw response
for each successful model call is saved next to the JSON and HTML results under
the Git-ignored `outputs/opencode_dx/results/` directory. Decisions are
validated individually against exact recorded evidence. An invalid decision is
listed with its index and error while other valid decisions are kept. Invalid
JSON or a failed model call still fails its entire chunk. Any such result is
marked **partial** and must not be treated as complete; only complete results
are reused from cache. The normalized `thought` field contains
only recorded assistant text or reasoning parts, not hidden internal reasoning.
The unit of analysis is the whole OpenCode session, so use one session per
coding task when comparing agents.

The MCP server also works independently of the command. Its tool takes the
absolute path to a snapshot written under `outputs/opencode_dx/snapshots/`.

## Current codebook

The extractor loads the Design decision, Taxonomy, Visibility and Annotation
rules sections from `annotations/codebook_v2.md`, including category boundaries
and examples. Workbook-specific cell instructions are excluded. Unsupported or
unclear candidates are omitted, not assigned a third visibility label. Evidence
validation checks exact excerpts and step references; it does not independently
prove that the model's category interpretation is correct.

The `show-dx-v2` extraction version prevents older cached analyses from being
reused under the revised rules. Existing results remain unchanged. Restart
OpenCode Desktop or reconnect the MCP server after updating its Python code.

## Local task example

The multi-source data merger example is in
`outputs/opencode_dx/example_environment/multi-source-data-merger/`.
It uses the original Terminal-Bench 2.1 JSON, CSV and Parquet inputs. Its
`README.md` contains the OpenCode task prompt and local verification instructions.
The task is deliberately unsolved. Open the repository root in Desktop to keep
the existing command and MCP configuration available, and use a fresh session
for the task. The separately stored verifier is excluded from the coding
agent's permitted scope by the task prompt, not by a filesystem security boundary.
