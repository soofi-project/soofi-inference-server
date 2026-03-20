# Qwen3 / Qwen3.5 tool call parser for Triton OpenAI frontend.
#
# Parses the native XML format produced by Qwen3-series models:
#
#   <think>\n\n</think>\n\n          (empty think block — thinking disabled)
#
#   <tool_call>
#   <function=func_name>
#   <parameter=param1>
#   value1
#   </parameter>
#   </function>
#   </tool_call>
#
# Registered as "qwen3_coder" to match --tool-call-parser qwen3_coder.

import json
import re
import uuid
from typing import Union

from engine.utils.tokenizer import AnyTokenizer
from engine.utils.tool_call_parsers.tool_call_parser import (
    ToolCallParser,
    ToolParserManager,
)
from schemas.openai import (
    ChatCompletionMessageToolCall,
    ChatCompletionMessageToolCallChunk,
    ChatCompletionMessageToolCalls,
    ChatCompletionResponseMessage,
    ChatCompletionStreamResponseDelta,
    Function1,
    Function2,
)

_TOOL_START = "<tool_call>"
_TOOL_END = "</tool_call>"
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_TOOL_BLOCK_RE = re.compile(
    re.escape(_TOOL_START) + r"(.*?)" + re.escape(_TOOL_END), re.DOTALL
)
_FUNCTION_RE = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_PARAM_RE = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.DOTALL)


def _strip_think(text: str) -> str:
    """Remove complete <think>...</think> blocks."""
    return _THINK_RE.sub("", text)


def _parse_xml_block(inner: str) -> dict | None:
    """Parse <function=name><parameter=k>v</parameter>...</function> into a dict."""
    m = _FUNCTION_RE.search(inner)
    if not m:
        return None
    name = m.group(1).strip()
    args: dict = {}
    for pm in _PARAM_RE.finditer(m.group(2)):
        key = pm.group(1).strip()
        raw = pm.group(2).strip()
        # Try JSON decode for typed values (numbers, booleans, objects)
        try:
            args[key] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            args[key] = raw
    return {"name": name, "arguments": args}


@ToolParserManager.register_module("qwen3_coder")
class Qwen3CoderToolParser(ToolCallParser):
    def __init__(self, tokenizer: AnyTokenizer):
        super().__init__(tokenizer)
        self.prev_tool_call_arr: list[dict] = []
        self.current_tool_id: int = -1
        self.current_tool_name_sent: bool = False
        self.streamed_args_for_tool: list[str] = []
        # streaming state
        self._emitted_tool_ids: set[int] = set()

    # ------------------------------------------------------------------ #
    #  Non-streaming                                                       #
    # ------------------------------------------------------------------ #

    def parse_tool_calls(
        self, full_text: str, role: str, backend: str
    ) -> ChatCompletionResponseMessage:
        clean = _strip_think(full_text)

        if _TOOL_START not in clean:
            return ChatCompletionResponseMessage(
                tool_calls=None, content=clean.strip() or full_text, role=role
            )

        pre_content = clean[: clean.find(_TOOL_START)].strip()
        matches = _TOOL_BLOCK_RE.findall(clean)

        if not matches:
            return ChatCompletionResponseMessage(
                tool_calls=None, content=clean.strip(), role=role
            )

        parsed = [_parse_xml_block(m) for m in matches]
        parsed = [p for p in parsed if p is not None]

        if not parsed:
            return ChatCompletionResponseMessage(
                tool_calls=None, content=clean.strip(), role=role
            )

        tool_calls = ChatCompletionMessageToolCalls(
            root=[
                ChatCompletionMessageToolCall(
                    id=f"cmpl-{uuid.uuid1()}",
                    type="function",
                    function=Function1(
                        name=p["name"],
                        arguments=json.dumps(p["arguments"]),
                    ),
                )
                for p in parsed
            ]
        )
        return ChatCompletionResponseMessage(
            tool_calls=tool_calls,
            content=pre_content or "",
            role=role,
        )

    # ------------------------------------------------------------------ #
    #  Streaming                                                           #
    # ------------------------------------------------------------------ #
    #
    # Strategy: buffer until </tool_call> is complete, then emit the full
    # tool call in one shot.  For regular text, suppress the think preamble
    # and pass everything after </think> through token by token.
    # ------------------------------------------------------------------ #

    def parse_tool_calls_streaming(
        self, current_text: str, delta_text: str, backend: str
    ) -> Union[ChatCompletionStreamResponseDelta, None]:

        # ── Phase 1: before any <tool_call> ──────────────────────────────
        if _TOOL_START not in current_text:
            # Suppress <think>\n\n</think>\n\n preamble; stream everything after.
            if "</think>" not in current_text:
                return None  # still inside / before think block

            # Only stream the portion of delta that follows </think>
            after_think = current_text.split("</think>", 1)[-1]
            prev_text = current_text[: -len(delta_text)] if delta_text else current_text
            prev_after = prev_text.split("</think>", 1)
            prev_after_think = prev_after[-1] if len(prev_after) > 1 else ""
            new_content = after_think[len(prev_after_think):]
            if new_content:
                return ChatCompletionStreamResponseDelta(content=new_content)
            return None

        # ── Phase 2: we have tool call(s) ────────────────────────────────
        complete_blocks = _TOOL_BLOCK_RE.findall(current_text)
        num_complete = len(complete_blocks)

        # Emit each newly completed tool call once
        for idx in range(num_complete):
            if idx in self._emitted_tool_ids:
                continue
            # New complete tool call — emit it
            self._emitted_tool_ids.add(idx)
            parsed = _parse_xml_block(complete_blocks[idx])
            if parsed is None:
                continue
            args_json = json.dumps(parsed["arguments"])
            self.current_tool_id = idx
            self.current_tool_name_sent = True
            self.streamed_args_for_tool.append(args_json)
            self.prev_tool_call_arr.append(parsed)
            return ChatCompletionStreamResponseDelta(
                tool_calls=[
                    ChatCompletionMessageToolCallChunk(
                        index=idx,
                        type="function",
                        id=f"cmpl-{uuid.uuid1()}",
                        function=Function2(
                            name=parsed["name"], arguments=args_json
                        ).model_dump(exclude_none=True),
                    )
                ]
            )

        # No new complete block — partial in progress, stream nothing
        return None
