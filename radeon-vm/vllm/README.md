# Radeon vLLM

The Compose service serves a local Hugging Face safetensors checkpoint over
the OpenAI-compatible API on `192.168.30.105:8000`. The endpoint has no API
key configured; restrict network access to trusted clients. Both the local and
NAS model libraries are mounted read-write as requested; restrict access to
this container accordingly. `data/` contains writable caches. The Ollama
Compose service was removed; its model volume and local identity data remain.

The configured model and its path are in `.env`. The default is
Qwen3.8-27B GPTQ, text only, configured for 262,144 tokens over two GPUs.
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
cd /docker/radeon-vm/vllm
docker compose config --quiet
docker compose up -d
docker compose logs -f vllm
curl http://192.168.30.105:8000/v1/models
curl http://192.168.30.105:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -N -d '{"model":"qwen3.8-27b-gptq","messages":[{"role":"user","content":"Say hello briefly."}],"max_tokens":128,"stream":true}'
```

The current settings use two GPUs, a 262144-token limit, up to five concurrent
sequences, prefix caching and a 0.9 per-GPU memory utilization target. The
sequences share the available KV cache, so five simultaneous maximum-length
requests are not guaranteed to fit. Prefix caching reuses matching prompt
prefixes; unrelated prompt content cannot share cached state. The utilization
target is not a hard VRAM limit or a GPU reservation; competing inference
processes can still cause out-of-memory errors. `NCCL_P2P_DISABLE=1` and
disabled custom all-reduce are conservative settings, not performance tuning;
AMD SMI reported P2P
disabled between the two cards. Loading a model can use swap on this VM;
loading the GPTQ model from NFS previously took several minutes. The older
Qwen3-32B-AWQ checkpoint was
removed after its GPTQ alternative was downloaded. Change
`VLLM_MODEL_DIR`, `VLLM_SERVED_MODEL_NAME`, and any necessary
runtime settings in `.env`, then recreate with `docker compose up -d`.

## Local and NAS models

The VM model disk is mounted at `/models`: its `vllm/` and `llama-cpp/`
directories are separate local libraries. This container sees `/models/vllm`
as `/models/local` and the Tank NFS named volume as `/models/nas`. Set
`VLLM_MODEL_SOURCE` to `local` or `nas` and `VLLM_MODEL_DIR` to the checkpoint
path relative to that library. The default is the local Qwen checkpoint.
Both container mounts are writable, including the shared NAS. The local disk is
excluded from Proxmox VM backups but inherits the host's ZFS snapshot policy;
treat its contents as a cache, not a PBS backup. Changing the selected model
requires recreating the service.

VM 105's 200 GiB `rpool-vm:vm-105-models` disk is mounted by filesystem UUID
at `/models`; the generated mount unit is ordered before Docker. The local
Qwen3.8, Gemma 4, Granite 4.2, and Phi 4 Reasoning Plus safetensors copies
were checksum-verified before their NAS originals were removed. GGUF and
Ollama versions remain on the NAS. Qwen has been smoke-tested locally; the
other checkpoints have not been tested for runtime compatibility or GPU fit.
Existing NAS snapshots can retain deleted files until their normal expiration.

Edit the `MODELS` list near the top of `download-models.py` to select public
Hugging Face model IDs or URLs. Append `@<commit>` to pin a revision; without
one, the script resolves the current `main` revision. Mount the local disk and
run:

```bash
cd /docker/radeon-vm/vllm
python3 download-models.py
```

The script uses the existing vLLM image, without a GPU or a host Python
package. Repeated runs quickly verify existing files against Hugging Face
metadata and sizes; this is not a full content checksum. It refuses to overwrite
an incomplete or mismatched checkpoint, resumes its own partial downloads, and
promotes them only after verification. It needs internet access; the current
Qwen checkpoint requires roughly 20 GiB of free space. Select the local root
and checkpoint in `.env`, then recreate the service. Set `VLLM_MODEL_DISK` if
the dedicated disk is mounted somewhere other than `/models`.

For four cards, first validate passthrough, cooling, PSU headroom and ROCm
visibility for all four; then set `VLLM_TENSOR_PARALLEL_SIZE: 4` and recreate
the service. Four workers may require more VM RAM. Check that the selected
model supports that parallelism, run an inference test, and verify VRAM usage
on every card. Benchmark P2P and
all-reduce separately before enabling them. Cards currently expose 250 W
stock caps; do not assume the previous 180 W power target is active.

Automatic tool choice is enabled with the `qwen3_xml` parser, matching the
current checkpoint's XML tool-call template. When changing models, set
`VLLM_TOOL_CALL_PARSER` in `.env` to a parser compatible with the new model's
chat template before recreating the service. These are server settings and
apply to all clients; OpenCode's `--auto` controls permission approval instead.

The Compose command also enables `--reasoning-parser qwen3`. The checkpoint's
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
