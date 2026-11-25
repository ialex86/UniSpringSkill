// Runs templates/hooks/opencode-plugin.js under Bun against a fake OpenCode context whose
// events have the shapes recorded on OpenCode 2.2.5 (tool execute.after, session.inbox.enqueued,
// session.step.ended), and the real agent_hook.py. Used by test_agents.py when bun is installed.
// usage: bun opencode_harness.js <plugin.js rendered> <project root>
const [pluginPath, root] = process.argv.slice(2)
const plugin = (await import(pluginPath)).default

const afterHooks = []
const messages = []
const queue = []
let wake = null
const push = (event) => { queue.push(event); if (wake) { wake(); wake = null } }

const ctx = {
  location: { directory: root },
  tool: { hook: async (name, fn) => { if (name === "execute.after") afterHooks.push(fn) } },
  session: { synthetic: async (m) => { messages.push(m) } },
  event: {
    subscribe: ({ signal }) => ({
      async *[Symbol.asyncIterator]() {
        while (!signal.aborted) {
          if (!queue.length) await new Promise((r) => { wake = r; setTimeout(r, 50) })
          while (queue.length) yield queue.shift()
        }
      },
    }),
  },
}

const settle = () => new Promise((r) => setTimeout(r, 300))
const cleanup = await plugin.setup(ctx)
const sid = "ses_test"
const here = { directory: root }

push({ type: "session.inbox.enqueued", location: here, data: { sessionID: sid, item: { type: "user" } } })
await settle()

// The model edits the service and adds an `else`, after the session baseline was taken.
await Bun.write(`${root}/${process.env.EDITED_PATH}`, process.env.DIRTY_TEXT)
const edit = {
  tool: "edit", sessionID: sid, status: "completed",
  input: { path: process.env.EDITED_PATH, oldString: "a", newString: "b" },
  result: { content: [{ type: "text", text: "Edited (1 replacement)" }] },
}
for (const fn of afterHooks) await fn(edit)

push({ type: "session.step.ended", location: here, data: { sessionID: sid, finish: "stop" } })
await settle()
push({ type: "session.step.ended", location: here, data: { sessionID: sid, finish: "stop" } }) // after the retry
await settle()
push({ type: "session.step.ended", location: { directory: "/elsewhere" }, data: { sessionID: sid, finish: "stop" } })
await settle()
push({ type: "session.inbox.enqueued", location: here, data: { sessionID: sid, item: { type: "user" } } })
await settle()
push({ type: "session.step.ended", location: here, data: { sessionID: sid, finish: "stop" } }) // a new user turn
await settle()

cleanup()
console.log(JSON.stringify({
  editContent: edit.result.content.map((c) => c.text),
  messages: messages.map((m) => m.text),
  baseline: await Bun.file(`${root}/.unispring-cache/opencode-session-baseline.json`).exists(),
}))
process.exit(0)
