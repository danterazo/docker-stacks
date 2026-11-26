# Radeon vLLM

The Compose service is configured to serve a local Hugging Face safetensors
checkpoint over the OpenAI-compatible API on `192.168.30.150:8000` and
`https://vllm.samskeyti.net`. The endpoint requires a bearer token from
`.secrets`; `VLLM_API_KEY_NAMES` in `.env` selects which client variables the
service accepts. The service pins
`ghcr.io/opengfx1030/vllm-rdna:v0.34.0-1-rocm7.14.0`, rather than the moving
nightly tag. The local model library is mounted read-write; the NAS library is
not mounted. `data/` contains writable caches.

The configured model and its path are in `.env`. The current model is
`palmfuture/Qwen3.6-35B-A3B-GPTQ-Int4`, served as `qwen3.6-35b-a3b` with
262,144 tokens over two tensor-parallel V620 ranks.
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
  -N -d '{"model":"qwen3.6-35b-a3b","messages":[{"role":"user","content":"Say hello briefly."}],"max_tokens":128,"stream":true}'
```

The current configuration uses two tensor-parallel ranks, 262144 tokens, up to
six concurrent sequences and a 0.80 per-GPU memory utilization target. The
35B GPTQ checkpoint is retained because the preceding two-card validation
loaded the model at about 24.5 GiB per V620. The utilization target is not a
hard VRAM limit or a GPU reservation; competing inference processes can still
cause out-of-memory errors. `NCCL_P2P_DISABLE=1` and disabled custom all-reduce
are conservative settings, not performance tuning; AMD SMI reported P2P
disabled between the two cards. Loading a model can use swap on this VM;
loading the GPTQ model from NFS previously took several minutes. The older
Qwen3-32B-AWQ checkpoint was removed after its GPTQ alternative was downloaded.
Change
`VLLM_MODEL_DIR`, `VLLM_SERVED_MODEL_NAME`, and the capacity settings in `.env`,
then recreate with `docker compose up -d`. Stable image, cache, and RDNA2
settings are grouped in `compose.yaml`; architecture-specific CLI flags are
defined beside the rest of the startup command.

## Agent quality benchmark

`scripts/run-aider-benchmark.sh` runs the official Aider polyglot coding
benchmark in an isolated, ephemeral Docker container on this LXC. The setup is
idempotent and pins both Aider and the exercise dataset. It never starts a
long-running benchmark service, and the container is removed after each run.

```bash
cd /docker/vllm
scripts/run-aider-benchmark.sh setup
scripts/run-aider-benchmark.sh run qwen36-smoke 1 1 python 1
scripts/run-aider-benchmark.sh run qwen36-agents 30 6 cpp,go,java,javascript,python,rust 2
scripts/run-aider-benchmark.sh stats
```

The `run` arguments are a run name, exercise count, parallel session count,
comma-separated languages and attempt count. The benchmark uses a 65536-token
model context so concurrent agents have a bounded, representative working set.
Results are stored under
`/tmp/ai/vllm-agent-benchmark/aider/tmp.benchmarks` and report first- and
second-attempt pass rates plus malformed edits, syntax errors, context-window
failures and test time. Benchmark code generated by the model runs only inside
the Aider container.

## Two-card parallelism A/B (2026-11-26)

PP2 and TP2 used the same image, Qwen3.6-35B-A3B GPTQ-Int4 checkpoint, MTP=1,
250 W card caps, 262144-token server limit and 80% GPU-memory target. The
measured workload was five sequential requests with about 958 prompt tokens
and 256 output tokens, followed by three synchronized four-client cohorts with
128 output tokens each.

| Metric | PP2 | TP2 | TP2 change |
| :-- | --: | --: | --: |
| Median first token latency | 0.421 s | 0.284 s | 32.5% lower |
| Median single-request decode | 71.93 tok/s | 103.95 tok/s | 44.5% higher |
| Median four-client aggregate output | 133.85 tok/s | 193.11 tok/s | 44.3% higher |
| Maximum four-client first token latency | 1.382 s | 1.026 s | 25.7% lower |
| Maximum junction temperature | 68 C | 71 C | 3 C higher |
| Healthy fan-control samples | 71/71 | 49/49 | Healthy |

Both modes completed their API requests without an OOM, restart or inference
error. Neither mode passed the PCIe stability gate. PP2 had five correctable
`BadTLP` events in its startup/test window. TP2 startup added one event, and the
benchmark added two more, for eight total on this boot. All eight were marked
corrected by hardware, with zero uncorrectable AER events or GPU resets.

The repeated PP2 and TP2 results were tight, with no failed request, timeout or
obvious performance outlier attributable to an event. A corrected PCIe TLP can
still require a replay and incur a brief latency cost, so this observation does
not prove zero effect at the transaction level. It does show no material
user-visible degradation in this bounded test: the TP2 run retained its
throughput advantage and both modes completed cleanly. No sustained run should
be considered stable until the affected card, route and riser combinations are
isolated and retested. TP2 remains active because it delivered the higher
throughput, but the performance result does not clear the underlying PCIe faults.

## Qwen3-Coder-Next W4A16 trial (2026-11-26)

`btbtyler09/Qwen3-Coder-Next-GPTQ-4bit` was tested as a 47 GiB GPTQ model
using two tensor-parallel ranks. The checkpoint is stored on Kex under
`/tank/models/language-models/hf_safetensors/btbtyler09/` and exposed read-only
to CT 150 through its `/models/nas` NFS bind; the trial did not consume more
space on Kveikur's model dataset. It loaded 22.76 GiB on each V620 at 90%
memory utilization, with 32,768 tokens configured and 3.63 GiB available per
GPU for KV cache. Startup took 319 seconds from the Kex NFS source.

Both models used the same TP2 hardware, 250 W caps, five maximum sequences,
about 1,040 prompt tokens for short requests, 22,540 tokens for long-context
requests and 256 output tokens. The stress arm used four simultaneous clients.
The current model retained its MTP=1 setting; Coder-Next has no MTP head.

| Metric | Qwen3.6-35B-A3B | Coder-Next 80B-A3B GPTQ |
| :-- | --: | --: |
| Short-request median TTFT | 0.492 s | 1.102 s |
| Short-request median decode | 29.89 tok/s | 49.02 tok/s |
| 22.5K-context TTFT | 12.02 s | 23.65 s |
| 22.5K-context prefill | 1,875 tok/s | 953 tok/s |
| 22.5K-context decode | 71.40 tok/s | 38.09 tok/s |
| Four-client aggregate output | 180.28 tok/s | 65.62 tok/s |
| Four-client maximum TTFT | 1.191 s | 4.434 s |
| Model memory per GPU | 11.74 GiB | 22.76 GiB |
| Tested maximum context | 262,144 | 32,768 |
| Thinking mode | Supported | Not supported |
| Startup | Local model, about 40 s | Kex NFS, 319 s |
| Correctable BadTLP added during benchmark | 7 | 9 |

Coder-Next's advantage on the short raw-completion prompt was content- and
MTP-acceptance-dependent; it was approximately twice as slow on the short TTFT
and lost decisively on long-context and four-client throughput. Both models
returned successful content and parsed a required calculator tool call. The
Coder-Next trial produced no OOM, container restart or request failure.

The published third-party picture does not justify replacing the current
model. Qwen3.6-35B-A3B reports 73.4 on SWE-bench Verified and 51.5 on
Terminal-Bench 2.0; the
[Coder-Next technical report](https://ar5iv.labs.arxiv.org/html/2603.00729)
reports 70.6–71.3 on SWE-bench across evaluated agent scaffolds and 25.8–36.2
on its Terminal-Bench variants. Benchmark scaffolds are not perfectly
comparable, but Coder-Next does not show a clear quality margin, has no
thinking mode and uses more VRAM. The active service was restored to
Qwen3.6-35B-A3B TP2 with MTP=1 after the trial. The Coder-Next checkpoint
remains on Kex as an optional streamed comparison model.

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

Automatic tool choice is enabled with the `qwen3_coder` parser, matching the
current checkpoint's XML tool-call template. When changing model families,
update the parser flags in `compose.yaml` to match the new chat template before
recreating the service. These are server settings and apply to all clients;
OpenCode's `--auto` controls permission approval instead.

The Compose command also enables `--reasoning-parser qwen3`. The checkpoint's
chat template puts `<think>` in the prompt, so without the reasoning parser
the generated reasoning and `</think>` appear in normal assistant content.
After recreating the service, verify a streamed `/v1/chat/completions` response
contains reasoning in a separate `reasoning` or `reasoning_content` delta and
the answer in `content`. This has not yet been verified on this deployment.
For a different model family, select a reasoning parser compatible with its
template instead of assuming the Qwen parser applies.

OpenCode's vLLM discovery cannot infer tool support. Even with the server's
tool parser enabled, check the selected model's OpenCode capabilities and
explicitly enable tools there if needed. Validate actual tool calls before
relying on them. The power-cap benchmark uses `/v1/completions`, not chat
completions; do not compare runs across server configuration changes without
recording the difference.

## Qwen3.5 MTP benchmark (2026-11-23)

The Qwen3.5 checkpoint ships one MTP layer, and vLLM 0.31.0+rdna supports it
with `{"method":"mtp","num_speculative_tokens":1}`. An otherwise identical
single-request benchmark used a fixed 512-input/256-output random workload,
`temperature=0`, three warmups, eight measured requests and thinking disabled.

| Draft tokens | Output tok/s | Median TPOT | Acceptance | Result                                                        |
| -----------: | -----------: | ----------: | ---------: | ------------------------------------------------------------- |
|            0 |        53.25 |    17.91 ms |          - | Baseline                                                      |
|            1 |        70.84 |    12.27 ms |     74.44% | Enabled                                                       |
|            2 |        46.85 |    16.98 ms |     65.09% | Rejected                                                      |
|            3 |            - |           - |          - | Rejected; RDNA draft-decode path raises `NotImplementedError` |

MTP=1 improved output throughput by 33.0% and reduced median TPOT by 31.5%.
It uses about 24.5 GiB per V620 at the current 80% memory target and reduces
available KV cache from 12.22 GiB to 10.87 GiB per GPU. Keep the one-token
setting; higher values do not improve this workload and MTP=3 cannot initialize.
