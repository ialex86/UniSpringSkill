// unispring-game-dev hooks for OpenCode (V2 plugin API, verified on OpenCode 2.2.5).
// Installed by install.py --agent opencode as .opencode/plugins/unispring-gate.js.
// The checks are agent_hook.py's, the same as for Claude Code, Codex, Cursor and Copilot:
//   session start (first user message) -> agent_hook.py opencode start   (session baseline)
//   after edit/write/patch             -> agent_hook.py opencode edit    (text appended to the tool result)
//   end of a turn (step ended, stop)   -> agent_hook.py opencode stop    (text posted once as a message)
// One continuation per user message: the mark is cleared when the user writes again.
// Load errors don't show in the CLI: see ~/.local/share/opencode/log/opencode.log.
import { Plugin } from "@opencode/plugin"

const HOOK = "{{SKILL_DIR}}/scripts/hooks/agent_hook.py"
const EDIT_TOOLS = ["edit", "write", "patch", "multiedit", "apply_patch"]

function runHook(root, event, args, timeoutMs) {
  try {
    const result = Bun.spawnSync({
      cmd: ["python3", `${root}/${HOOK}`, "opencode", event],
      stdin: new TextEncoder().encode(JSON.stringify({ cwd: root, ...args })),
      cwd: root,
      timeout: timeoutMs, // milliseconds
    })
    return result.stdout?.toString?.() ?? ""
  } catch {
    return "" // the gate, the git hook and CI still hold if the hook can't run
  }
}

export default Plugin.define({
  id: "unispring-gate",
  async setup(ctx) {
    const root = ctx.location.directory // canonical (e.g. /private/tmp/...): compare with it as is
    const started = new Set()
    const continued = new Set()

    await ctx.tool.hook("execute.after", (event) => {
      if (!EDIT_TOOLS.includes(event.tool) || event.status !== "completed") return
      const text = runHook(root, "edit", { tool_name: event.tool, tool_input: event.input }, 60000)
      if (!text.trim() || !event.result || typeof event.result !== "object") return
      // Only result.content reaches the model (result.output and a replaced result do not).
      event.result.content = [...(event.result.content ?? []), { type: "text", text }]
    })

    const controller = new AbortController()
    void (async () => {
      for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
        const sid = event.data?.sessionID
        if (!sid || event.location?.directory !== root) continue
        if (event.type === "session.inbox.enqueued" && event.data?.item?.type === "user") {
          continued.delete(sid) // a new user message: the next stop may ask for one fix again
          if (!started.has(sid)) {
            started.add(sid)
            runHook(root, "start", {}, 120000)
          }
          continue
        }
        if (event.type !== "session.step.ended" || event.data?.finish !== "stop") continue
        const active = continued.has(sid)
        const text = runHook(root, "stop", { stop_hook_active: active }, 180000)
        if (!text.trim() || active) continue
        continued.add(sid)
        await ctx.session.synthetic({ sessionID: sid, text })
      }
    })()
    return () => controller.abort()
  },
})
