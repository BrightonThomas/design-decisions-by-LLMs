// OpenCode's Windows plugin loader does not resolve bare imports from .opencode/node_modules.
import { Service } from "../node_modules/@opencode/client/dist/promise/service.js"
import { mkdir, writeFile } from "node:fs/promises"
import { join, resolve } from "node:path"
import { randomUUID } from "node:crypto"

const analysisMessage = "/show_dx — Analyze this session's design decisions."

function analysisInstructions(snapshotPath: string): string {
  return `For the current /show_dx request only: call the connected dx_analyze_snapshot_file MCP tool exactly once with snapshot_path=${JSON.stringify(snapshotPath)}. If its result is already in this turn, summarize that result without calling it again. Wait for its result. Show the validated decision count, D1–D8 counts, and up to ten concise decision summaries with their source step numbers. Give the HTML result path for the full review. If complete is false, state that the analysis is partial and show failed chunks or rejected decision indices with their errors and raw response paths. Do not interpret zero validated decisions as no decisions. Do not classify the session yourself or include this request in the analyzed trajectory. Do not repeat these operational instructions in your reply.`
}

async function exportSession(sessionID: string): Promise<unknown> {
  // Discover the already-running Desktop service; never launch a CLI process.
  const endpoint = await Service.discover()
  if (!endpoint) throw new Error("OpenCode Desktop service was not found")
  const url = new URL(`/api/experimental/session/${encodeURIComponent(sessionID)}/export`, endpoint.url)
  url.searchParams.set("sanitize", "false")
  const response = await fetch(url, {
    headers: Service.headers(endpoint),
    signal: AbortSignal.timeout(30_000),
  })
  if (!response.ok) throw new Error(`OpenCode session export failed (HTTP ${response.status})`)
  const maximumBytes = 80 * 1024 * 1024
  const reportedBytes = Number(response.headers.get("content-length") || 0)
  if (reportedBytes > maximumBytes) throw new Error("Session export exceeds 80 MB")
  const body = await response.text()
  if (Buffer.byteLength(body, "utf8") > maximumBytes) throw new Error("Session export exceeds 80 MB")
  const payload = JSON.parse(body)
  const exported = payload?.data
  if (!exported || !Array.isArray(exported.messages)) {
    throw new Error("OpenCode returned a session export without messages")
  }
  return exported
}

export default {
  id: "show-dx",
  async setup(ctx) {
    // Only the outgoing model request receives the instructions, not chat history.
    // Read committed context so queued requests and plugin reloads retain the
    // right snapshot, without keeping a permanent per-session override.
    const contextRegistration = await ctx.session.hook("context", async (event) => {
      const messages = await ctx.session.context({ sessionID: event.sessionID })
      const latestUser = messages.findLast((message) => message.type === "user")
      const metadata = latestUser?.metadata
      if (latestUser?.text !== analysisMessage || metadata?.dx_analysis_request !== true) return
      const snapshotPath = metadata.dx_snapshot_path
      if (typeof snapshotPath !== "string" || !snapshotPath) {
        throw new Error("The /show_dx request is missing its snapshot path; run /show_dx again")
      }
      event.system.push({ type: "text", text: analysisInstructions(snapshotPath) })
    })
    const commandRegistration = await ctx.command.transform((editor) => {
      editor.add({
        name: "show_dx",
        description: "Analyze this session's recorded design decisions",
        execute: async ({ sessionID, prompt, delivery }) => {
          if (!/^[A-Za-z0-9_-]{3,100}$/.test(sessionID)) {
            throw new Error("Unexpected OpenCode session ID")
          }
          // Export before adding the analysis request to the conversation.
          const exported = await exportSession(sessionID)
          const root = resolve(process.env.DX_OUTPUT_DIR || join(ctx.location.directory, "outputs", "opencode_dx"))
          const snapshotDir = join(root, "snapshots")
          await mkdir(snapshotDir, { recursive: true })
          const snapshotPath = join(snapshotDir, `${sessionID}-${Date.now()}-${randomUUID()}.json`)
          await writeFile(snapshotPath, JSON.stringify({
            session_id: sessionID,
            source: "opencode-session-export",
            export: exported,
          }), "utf8")
          await ctx.session.prompt({
            ...prompt,
            sessionID,
            delivery,
            text: analysisMessage,
            metadata: {
              dx_analysis_request: true,
              dx_snapshot_path: snapshotPath,
            },
          })
        },
      })
    })
    return async () => {
      await commandRegistration.dispose()
      await contextRegistration.dispose()
    }
  },
}
