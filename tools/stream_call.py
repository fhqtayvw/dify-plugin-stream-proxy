import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage


# Fallback shown to the user when the target app streams nothing at all.
# Triggered only on zero output: the target workflow FAILED, or the stream was
# cut before the first text chunk arrived. Answers that already produced any
# content (including truncated ones) are left untouched.
SERVICE_UNAVAILABLE_NOTICE = (
    '抱歉，服务暂时不可用，本次查询未返回结果，请稍后重试。若多次失败请联系管理员。'
)


class StreamCallTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        query = tool_parameters.get('query', '')
        app_id = tool_parameters.get('app_id', '')
        conv_id = tool_parameters.get('conversation_id', '')
        inputs_dict = self._parse_inputs(tool_parameters.get('inputs', ''))

        response = self.session.app.chat.invoke(
            app_id=app_id,
            inputs=inputs_dict,
            query=query,
            response_mode='streaming',
            conversation_id=conv_id,
            user='stream-proxy',
        )

        answer_parts = []
        new_conv_id = conv_id

        try:
            for chunk in response:
                # Every streaming event carries conversation_id, so pick it up
                # unconditionally first. Relying on message_end alone is not
                # enough: that event may never arrive if the stream gets cut.
                cid = chunk.get('conversation_id')
                if cid:
                    new_conv_id = cid

                event = chunk.get('event', '')
                if event == 'message':
                    text = chunk.get('answer', '')
                    if text:
                        answer_parts.append(text)
                        yield self.create_text_message(text)
                elif event == 'message_end':
                    new_conv_id = chunk.get('conversation_id', conv_id)
                    break
                elif event == 'workflow_finished':
                    break
                elif event == 'error':
                    err = chunk.get('message', 'Unknown error')
                    yield self.create_text_message('[Error] ' + err)
        except Exception:
            # The plugin daemon enforces a hard read deadline on backwards
            # invocation of non-LLM streams: DIFY_BACKWARDS_INVOCATION_READ_TIMEOUT
            # (default 240000 ms, counted from the moment the request is issued).
            # When it fires, the response body is closed while a read is pending,
            # raising "use of closed network connection" / "failed to read system
            # header". By then the target app's answer has usually streamed out in
            # full, so swallow the error and finish with whatever we accumulated.
            # Letting it propagate instead would FAIL the tool node, and in a
            # router-style workflow the downstream nodes that persist
            # conversation state would never run -- the next turn would then
            # reuse a stale conversation_id.
            # Only Exception is swallowed; GeneratorExit (raised when the
            # response is cancelled) must keep propagating.
            pass
        finally:
            close = getattr(response, 'close', None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        full_answer = ''.join(answer_parts)

        if not full_answer.strip():
            # Zero-output fallback. Neither path above (cut stream / FAILED target
            # workflow) emitted a single message event, so answer_parts is empty.
            # Without this the tool's built-in text output would be an empty
            # string, and an answer node rendering it would show the user a blank
            # screen with no hint that anything went wrong.
            # Sent via create_text_message so it lands in the tool node's built-in
            # text output -- no output_schema change and no variable reference
            # change needed on the caller side.
            full_answer = SERVICE_UNAVAILABLE_NOTICE
            yield self.create_text_message(full_answer)

        yield self.create_json_message({
            'answer': full_answer,
            'conversation_id': new_conv_id,
        })
        yield self.create_variable_message('answer', full_answer)
        yield self.create_variable_message('conversation_id', new_conv_id)

    @staticmethod
    def _parse_inputs(raw: Any) -> dict:
        """Normalize the `inputs` parameter into the dict the target app expects.

        Accepts a JSON object string (what a `form: llm` parameter produces) or an
        already-parsed dict. A falsy value means the target app declares no
        start-node variables, so return an empty dict rather than failing.
        """
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw

        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                'The `inputs` parameter must be a JSON object string, '
                'e.g. {"key": "value"}. Got: ' + repr(raw)[:200]
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                'The `inputs` parameter must be a JSON object, got '
                + type(parsed).__name__ + '.'
            )

        return parsed
