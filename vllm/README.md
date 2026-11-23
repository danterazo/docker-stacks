# Radeon vLLM

The Compose service is configured to serve a local Hugging Face safetensors
checkpoint over the OpenAI-compatible API on `192.168.30.150:8000` and
`https://vllm.samskeyti.net`. The endpoint requires a bearer token from
`.secrets`; `VLLM_API_KEY_NAMES` in `.env` selects which client variables the
service accepts. The local model library is mounted read-write; the NAS library
is not mounted. `data/` contains writable caches.

The configured model and its path are in `.env`. The default is
`google/gemma-4-E4B-it-qat-w4a16-ct`, served as `gemma-4-e4b-qat` with
131,072 tokens over two GPUs.
Check `/v1/models` for the served name and context limit; this does not
establish full-length inference. The earlier
DeepSeek-R1-Distill-Qwen-1.5B FP16 smoke-test checkpoint is now under
`/tank/models/language-models/hf_safetensors/deepseek-ai/`. An Ollama model
name is not a Hugging Face checkpoint path.

## Verified smoke test (2026-11-21)

With two V620s, the service loaded both tensor-parallel ranks, `/health`
returned 200 and a chat completion answered `2 + 2` correctly. Each GPU used
about 9.1 GiB of VRAM after initialization. This was a basic smoke test, not a
performance or long-running stability benchmark. The image logged a Triton
kernel import warning (`is_hip_gfx1250`); this FP16 Qwen2 test still worked,
but other models or quantizations may be affected. The tested image digest is
`sha256:16cbf6a09c879b2c69012c60bed4eb935e3029839bc641d1a9574931e8b9f127`;
the upstream tag may change when pulled again.

Startup took a few minutes on the first run. The VM used roughly 2.7 GiB of
swap during the test, and the image left about 17 GiB free on the root disk.
Monitor host RAM, swap and disk space before scaling or loading larger models.

## Qwen3-32B-AWQ long-prompt baseline (2026-11-22)

At TP2 and a 32768-token configured limit, two sequential streamed requests
using repeated filler and a simple early-prompt code both returned the correct
code. The 7190-token request took 16.32 s to first token (~440 prompt tokens/s)
and the 26315-token request took 120.67 s (~218 prompt tokens/s); short output
decode was approximately 3.05 and 2.57 tokens/s respectively. These are
single-request estimates, not comprehensive throughput or quality tests. The
26K test alone did not establish the model's full 32K capability. A separate
32,735-prompt-token test with 32 output tokens reserved succeeded, returned
the correct code, and measured 175.19 s to first token (~187 prompt tokens/s)
and approximately 2.46 output tokens/s. This is a simple retrieval check,
not comprehensive long-context accuracy validation. Per-second sensor
samples recorded maximum edge/junction/memory temperatures of 64/84/58 °C
and 66/81/58 °C on the two GPUs. Stop or adjust long load if cooling is
inadequate; those junction readings approached the benchmark's 90 °C cutoff.

```bash
cd /docker/vllm
docker compose config --quiet
docker compose up -d
docker compose logs -f vllm
curl https://vllm.samskeyti.net/v1/models \
  -H "Authorization: Bearer $VLLM_API_KEY"
curl https://vllm.samskeyti.net/v1/chat/completions \
  -H "Authorization: Bearer $VLLM_API_KEY" \
  -H 'Content-Type: application/json' \
  -N -d '{"model":"gemma-4-e4b-qat","messages":[{"role":"user","content":"Say hello briefly."}],"max_tokens":128,"stream":true}'
```

The current configuration requests two GPUs, 131072 tokens, up to five
concurrent sequences and a 0.80 per-GPU memory utilization target. This target is not a
hard VRAM limit or a GPU reservation; competing inference processes can still
cause out-of-memory errors. `NCCL_P2P_DISABLE=1` and disabled custom all-reduce
are conservative settings, not performance tuning; AMD SMI reported P2P
disabled between the two cards. Loading a model can use swap on this VM;
loading the GPTQ model from NFS previously took several minutes. The older
Qwen3-32B-AWQ checkpoint was
removed after its GPTQ alternative was downloaded. Change
`VLLM_MODEL_DIR`, `VLLM_SERVED_MODEL_NAME`, and any necessary
runtime settings in `.env`, then recreate with `docker compose up -d`.

## Kveikur LXC Model Storage

The LXC maps the host library `/rpool/data/models/safetensors` to
`/models/safetensors`; Compose exposes that directory inside the inference
container as `/models/local`. `VLLM_MODEL_DIR` is relative to the library root,
for example `btbtyler09/Qwen3.8-27B-GPTQ-4bit`. Model files remain writable for
the dante UID and can be added with the model manager. The NAS model library is
not mounted into this LXC; its original files remain on the NAS.

To download or verify the pinned Hugging Face model list in this LXC, use:

```bash
cd /docker/vllm
VLLM_MODEL_ROOT=/models/safetensors python3 download-models.py
```

The script uses the existing vLLM image without a GPU. It verifies the expected
file metadata and sizes, not full content hashes, and refuses to overwrite an
incomplete or mismatched checkpoint. The local ZFS-backed model directory is
shared from the Proxmox host; do not copy it into the LXC root filesystem.

Automatic tool choice is enabled with the `gemma4` parser, matching the
current checkpoint's XML tool-call template. When changing models, set
`VLLM_TOOL_CALL_PARSER` in `.env` to a parser compatible with the new model's
chat template before recreating the service. These are server settings and
apply to all clients; OpenCode's `--auto` controls permission approval instead.

The Compose command also enables `--reasoning-parser gemma4`. The checkpoint's
chat template puts `<think>` in the prompt, so without the reasoning parser
the generated reasoning and `</think>` appear in normal assistant content.
After recreating the service, verify a streamed `/v1/chat/completions` response
contains reasoning in a separate `reasoning` or `reasoning_content` delta and
the answer in `content`. This has not yet been verified on this deployment.
For a different model, select a reasoning parser compatible with its template
instead of assuming the Qwen parser applies.

OpenCode's vLLM discovery cannot infer tool support. Even with the server's
tool parser enabled, check the selected model's OpenCode capabilities and
explicitly enable tools there if needed. Validate actual tool calls before
relying on them. The power-cap benchmark uses `/v1/completions`, not chat
completions; do not compare runs across server configuration changes without
recording the difference.
