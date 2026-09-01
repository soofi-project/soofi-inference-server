# vLLM Tool Call Parsers

Reference for `parser_profiles` in `vars.yaml`. The wrong parser causes tool calls
to appear as plain text on the second conversation turn.

## Qwen / Nemotron models

| Parser | Use for |
|---|---|
| `qwen3_xml` | Qwen3 / Qwen3.5 / Qwen3.6 Instruct and MoE models |
| `qwen3_coder` | Qwen3-Coder variants, **Qwen3.8**, NVIDIA Nemotron-3 (uses `肇`/`uito` + `<function>` format) |

Instruct and Coder models emit tool calls in different formats. Mixing them up breaks
multi-turn tool use: turn 1 may work by accident, turn 2 always fails.

**Qwen3.8 is the exception to the family pattern above.** Despite being an Instruct-style
model (and reusing the `Qwen3_5ForConditionalGeneration` architecture), its vLLM recipe
specifies `--tool-call-parser qwen3_coder` together with `--reasoning-parser qwen3` —
i.e. the `qwen3_coder` profile, not `qwen3_xml`. Don't "correct" it to `qwen3_xml`.
See https://recipes.vllm.ai/Qwen/Qwen3.8-27B

## Meta Muse-Glimmer

`muse_glimmer` for **both** `--tool-call-parser` and `--reasoning-parser` — this is the
one profile where the pairing is mandatory rather than a convention. Muse-Glimmer emits
neither JSON tool calls nor `<think>` tags; every turn is channel-scoped
(`to=self<|message|>`, `<|start|>assistant to=<tool><|message|>`, ATEM-style
`<atem:invoke>` blocks, closed with `<|eom|>`/`<|eot|>`). The reasoning parser is what
forces `skip_special_tokens=False`; drop it and the reasoning and tool channels collapse
into plain content — tool use looks broken while the model is doing the right thing.

Not available in the `vllm_defaults.tag` image: support ships in vllm-project/vllm#51655
and the `vllm/vllm-openai:muse-glimmer` build, which `muse-glimmer-30b-multi` pins.
See https://recipes.vllm.ai/meta-models/Muse-Glimmer-30B

## Other parsers

Full list from the `--tool-call-parser` flag, **as captured on vLLM v0.21.0**.
`vllm_defaults.tag` is now v0.27.1, so this list is stale — re-run the command
below against the image you actually deploy before trusting it:

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

Note: models can pin their own image via `repository`/`tag` in `vars.yaml`
(`qwen38-27b-coding` runs `qwen38-x86_64-cu130`), so the list above — taken from
`vllm_defaults.tag` — is not necessarily what those containers accept. Check per image.

## Reasoning parsers

Set alongside `tool_call_parser` when the model has a thinking/reasoning mode.
With `enable_thinking: false` in `chat_template_kwargs` this is a no-op but harmless.

| Parser | Use for |
|---|---|
| `qwen3` | Qwen3 / Qwen3.5 / Qwen3.6 / Qwen3.8 |
| `nano_v3` | NVIDIA Nemotron-3 Nano (requires `reasoning_parser_plugin`) |
| `nemotron_v3` | NVIDIA Nemotron v3 (legacy) |
| `minimax_m2_append_think` | MiniMax M2 |
| `gemma4` | Gemma 4 |
| `muse_glimmer` | Meta Muse-Glimmer (mandatory — see above) |
