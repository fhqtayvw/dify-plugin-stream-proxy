# Dify 流式代理

一个 Dify 插件：让一个 Dify 应用调用**另一个 Dify 应用**，并把子应用的回答**实时流式**透传给用户。

[English](README.md)

---

## 为什么需要它

Dify 内置工具可以调外部 HTTP 接口，但没有受支持的方式让一个工作流去调用*另一个 Dify 应用*，
并把子应用的回答片段边生成边透传出来。

只要你在做**路由 / 统一入口**类的应用，这个缺口就会咬人：

```
用户 -> 路由应用  ──意图分类──>  专家应用（流式输出长回答）
                  <─── 片段 ────
```

没有流式透传时，路由必须等专家应用全部跑完，再把整段回答一次性吐出来。用户盯着空白屏
30 多秒，打字机效果也没了。`stream-proxy` 就是补这个口子的：工具消费子应用的 SSE 流，
每收到一片就立刻转发一片。

## 特性

- **实时透传** —— 回答片段一到就转发。
- **多轮上下文** —— 返回子应用的 `conversation_id`，调用方可据此维持上下文。
- **零输出兜底** —— 子应用一个字都没流出来时，输出一句人话提示，而不是让回答节点空着。
- **扛得住守护进程的读超时** —— 见下方[「240 秒读上限」](#240-秒读上限)。

## 环境要求

- Dify 1.x，且 plugin daemon 正常运行。
- 目标应用必须在**同一个 Dify 实例**内（本插件走 inner API 的反向调用，不是外部 HTTP 调用）。
- 目标应用必须已发布。

## 安装

**从 Release 安装**

1. 从 [Releases](../../releases) 下载 `stream-proxy.difypkg`。
2. 进入 Dify：**插件 → 安装插件 → 通过本地文件安装**，选择该 `.difypkg`。

**从源码构建**

```bash
pip install dify-plugin-cli
dify plugin package . -o stream-proxy.difypkg
```

或直接运行 `./build.sh`。

## 配置

配置项在 **Provider 凭据页**（安装后打开插件点「配置」）。

| 配置项 | 默认 | 说明 |
|---|---|---|
| `language` | `en_US` | 内置兜底提示文案的语言。可选 `en_US`、`zh_Hans`、`ja_JP`、`pt_BR` —— 即 Dify 插件 i18n 模型真正携带的 4 个 locale。 |
| `fallback_message` | （空） | 填写后**原样输出**，覆盖 `language`。用于自定义文案、追加联系方式，或使用上表以外的语言。 |
| `log_level` | `INFO` | 为向前兼容而声明，见「已知限制」。 |

**为什么语言要做成配置而不是自动识别？** plugin daemon 不向插件暴露终端用户的 locale ——
`ToolRuntime` 只有 `credentials`、`user_id`、`session_id`。没有可识别的东西，只能显式指定。

## 使用

在工作流节点中添加 **Stream Call** 工具，填写参数：

| 参数 | 必填 | 说明 |
|---|:---:|---|
| `query` | ✅ | 转发给目标应用的用户查询。 |
| `app_id` | ✅ | 目标应用的 UUID。在应用 URL 里找：`https://<你的dify>/app/<app_id>/...` |
| `conversation_id` | — | 目标应用的会话 ID，用于维持多轮上下文。留空则开启新会话。 |
| `inputs` | — | 目标应用开始节点变量的 JSON 对象，例如 `{"user_id": "abc"}`。目标应用没有输入变量时留空。JSON 格式错误会直接报错，而不是悄悄发空参数。 |

### 输出

| 输出 | 类型 | 说明 |
|---|---|---|
| `text` | 内置 | 每一片回答，流式输出。绑定到你的回答节点。 |
| `answer` | 变量 | 聚合后的完整回答文本。 |
| `conversation_id` | 变量 | 目标应用的会话 ID —— 持久化它即可在下一轮保持上下文。 |

典型的路由工作流两轮之间这样串：

```
第 1 轮：start -> classify -> stream_call(query, app_id)
                              └─ 把 conversation_id 存进会话变量
第 2 轮：start -> stream_call(query, app_id, conversation_id=<已保存的>)
                              └─ 用返回的新 id 覆盖该变量
```

## 240 秒读上限

plugin daemon 对**非 LLM** 的反向调用有一条写死的读取时限：

```
DIFY_BACKWARDS_INVOCATION_READ_TIMEOUT   # 默认 240000 ms，从请求发起算起
```

到点后响应体会在读取挂起时被关闭，表现为 `use of closed network connection` /
`failed to read system header`。这是 daemon 层的限制，**插件侧改不了**。

两个后果：

1. **超过约 4 分钟的回答可能被截断。** 插件不会因超时抛异常 —— 它用已累积到的内容正常收尾，
   所以已经流出去的那部分回答仍然能到用户手里。如果你的应用经常输出更长的回答，在
   `plugin_daemon` 服务上调大 `DIFY_BACKWARDS_INVOCATION_READ_TIMEOUT` 并重启。
2. **会话状态得以保留。** 吞掉异常使工具节点不会 FAIL，下游写 `conversation_id` 的节点因此
   照常执行。若节点 FAIL，下一轮就会悄悄复用旧的会话 ID。

## 已知限制

- 内置兜底文案只覆盖 `en_US`、`zh_Hans`、`ja_JP`、`pt_BR` 四种语言。其他语言通过
  `fallback_message` 配置项实现。其中 `ja_JP` 和 `pt_BR` 是尽力而为的翻译，欢迎指正。
- Provider 层的 `log_level` 凭据声明了但没接到 SDK 的 logger 上，运行时无实际效果，
  保留是为了向前兼容。
- 只解析目标应用的 `message` / `message_end` / `workflow_finished` / `error` 事件，
  其他 SSE 事件一律忽略。

## 许可证

[MIT](LICENSE)
