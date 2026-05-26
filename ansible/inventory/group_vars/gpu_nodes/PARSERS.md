# vLLM Tool Call Parsers

Reference for `parser_profiles` in `vars.yaml`. The wrong parser causes tool calls
to appear as plain text on the second conversation turn.

## Qwen / Nemotron models

| Parser | Use for |
|---|---|
| `qwen3_xml` | Qwen3 / Qwen3.5 / Qwen3.6 Instruct and MoE models |
| `qwen3_xml` | NVIDIA Nemotron-3 (Qwen3-based architecture) |
| `qwen3_coder` | Qwen3-Coder variants only |

Instruct and Coder models emit tool calls in different formats. Mixing them up breaks
multi-turn tool use: turn 1 may work by accident, turn 2 always fails.

## Other parsers (vLLM v0.21.0)

Full list from `--tool-call-parser` flag:

```
cohere_command3, cohere_command4,
deepseek_v3, deepseek_v31, deepseek_v32, deepseek_v4,
ernie45, functiongemma, gemma4, gigachat3, glm45, glm47,
granite, granite-20b-fc, granite4,
hermes, hunyuan_a13b, hy_v3, internlm, jamba, kimi_k2,
lfm2, llama3_json, llama4_json, llama4_pythonic, longcat,
mimo, minimax, minimax_m2, mistral, olmo3, openai,
phi4_mini_json, poolside_v1, pythonic,
qwen3_coder, qwen3_xml,
seed_oss, step3, step3p5, xlam
```

Run to get the current list for a given vLLM image:
```bash
docker run --rm --entrypoint="" vllm/vllm-openai:<tag> \
  python3 -m vllm.entrypoints.openai.api_server --help 2>&1 | grep -i "tool-call-parser"
```

## Reasoning parsers

Set alongside `tool_call_parser` when the model has a thinking/reasoning mode.
With `enable_thinking: false` in `chat_template_kwargs` this is a no-op but harmless.

| Parser | Use for |
|---|---|
| `qwen3` | Qwen3 / Qwen3.5 / Qwen3.6 |
| `nemotron_v3` | NVIDIA Nemotron v3 |
| `minimax_m2_append_think` | MiniMax M2 |
| `gemma4` | Gemma 4 |
