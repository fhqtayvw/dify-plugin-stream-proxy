# Dify Stream Proxy

A Dify plugin that lets one Dify app call **another Dify app** and stream the child app's answer
back to the user **in real time**.

[中文文档](README.zh-CN.md)

---

## Why this exists

Dify's built-in tools can hit an external HTTP endpoint, but there is no supported way for a
workflow to invoke *another Dify app* and pass the child app's answer chunks through as they are
generated.

That gap hurts whenever you build a **router / front-door app** in front of several specialist apps:

```
user -> router app  ──classify intent──>  specialist app (streams a long answer)
                    <─── chunks ────────
```

Without streaming passthrough the router must wait for the specialist to finish and then echo the
whole answer at once. The user stares at a blank screen for 30+ seconds and the typing effect is
gone. `stream-proxy` closes that gap: the tool consumes the child app's SSE stream and re-emits each
chunk immediately.

## Features

- **Real-time passthrough** — answer chunks are forwarded the moment they arrive.
- **Multi-turn continuity** — returns the child app's `conversation_id` so the caller can keep context.
- **Zero-output fallback** — if the child streams nothing at all, a human-readable notice is emitted
  instead of leaving the answer node blank.
- **Survives the daemon's read deadline** — the plugin daemon's backwards-invocation timeout is
  handled gracefully; see [The 240 s read limit](#the-240-s-read-limit).

## Requirements

- Dify 1.x with the plugin daemon running.
- The target app must live in the **same Dify instance** (this plugin uses backwards invocation via
  the inner API, not an external HTTP call).
- The target app must be published.

## Install

**From a release**

1. Download `stream-proxy.difypkg` from [Releases](../../releases).
2. In Dify: **Plugins → Install Plugin → Install from local package**, pick the `.difypkg`.

**From source**

```bash
pip install dify-plugin-cli
dify plugin package . -o stream-proxy.difypkg
```

Or run `./build.sh`.

## Usage

Add the **Stream Call** tool to a workflow node and fill in the parameters:

| Parameter | Required | Description |
|---|:---:|---|
| `query` | ✅ | The user query to forward to the target app. |
| `app_id` | ✅ | UUID of the target app. Find it in the app's URL: `https://<your-dify>/app/<app_id>/...` |
| `conversation_id` | — | The target app's conversation id, to keep multi-turn context. Leave empty to start a new conversation. |
| `inputs` | — | JSON object of the target app's start-node variables, e.g. `{"user_id": "abc"}`. Leave empty if the target app declares none. Malformed JSON raises an error rather than silently sending no inputs. |

### Output

| Output | Type | Description |
|---|---|---|
| `text` | built-in | Each answer chunk, streamed. Bind this to your answer node. |
| `answer` | variable | The fully accumulated answer text. |
| `conversation_id` | variable | The target app's conversation id — persist it to keep context on the next turn. |

A typical router workflow chains two turns like this:

```
turn 1:  start -> classify -> stream_call(query, app_id)
                             └─ save conversation_id into a conversation variable
turn 2:  start -> stream_call(query, app_id, conversation_id=<saved>)
                             └─ overwrite the variable with the returned id
```

## The 240 s read limit

The plugin daemon imposes a hard read deadline on backwards invocation of **non-LLM** streams:

```
DIFY_BACKWARDS_INVOCATION_READ_TIMEOUT   # default 240000 ms, counted from request start
```

When the deadline fires, the response body is closed while a read is pending, which surfaces as
`use of closed network connection` / `failed to read system header`. This is a daemon-level limit —
it is **not** configurable from the plugin.

Two consequences:

1. **Answers longer than ~4 minutes may be truncated.** The plugin does not raise on the deadline —
   it finishes with whatever it has already accumulated, so a partially streamed answer still
   reaches the user. If your app regularly produces longer answers, raise
   `DIFY_BACKWARDS_INVOCATION_READ_TIMEOUT` on the `plugin_daemon` service and restart it.
2. **Conversation state is preserved.** Swallowing the error keeps the tool node from FAILing, so the
   downstream nodes that persist `conversation_id` still run. If the node FAILed instead, the next
   turn would silently reuse a stale conversation id.

## Known limitations

- The zero-output fallback message is a hardcoded Chinese string. Edit `SERVICE_UNAVAILABLE_NOTICE`
  in `tools/stream_call.py` to change or translate it.
- The provider-level `log_level` credential is declared but not wired to the SDK logger — it has no
  effect at runtime. It is kept for forward compatibility.
- Only the target app's `message` / `message_end` / `workflow_finished` / `error` events are
  interpreted; other SSE events are ignored.

## License

[MIT](LICENSE)
