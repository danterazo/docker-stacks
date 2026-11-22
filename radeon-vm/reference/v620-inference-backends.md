# V620 inference backends: research and measurements

## This VM

- Two Radeon Pro V620s, about 30 GiB visible VRAM each; GPU-to-GPU P2P was
  reported disabled by `amd-smi topology`. Do not force P2P or a custom
  all-reduce without separate topology and correctness validation.
- The VM has about 15 GiB RAM and 8 GiB swap; large checkpoints can be slow
  to load from NFS and may cause memory pressure even if weights fit in VRAM.
- vLLM `blivioniag/vllm-rdna:v0.31.0-extras`, Qwen3-32B-AWQ, TP2, FP16,
  one request, 32K configured max: 3.26 output tokens/s on one short streamed
  request. A 32,735-token synthetic retrieval prompt measured 187 prompt
  tokens/s and 2.46 output tokens/s over an eight-token completion. This
  is not a GPU-wide throughput limit or a cross-engine comparison.
- The logs identify `auto_awq` and RCCL/PYNCCL. This image's AutoAWQ code can
  dispatch through generic AWQ operations; ROCm enables Triton AWQ. A slow
  dispatch is a credible hypothesis, not a confirmed root cause. The image
  also logs an `is_hip_gfx1250` Triton import error. P2P and VM overhead are
  other possible contributors. Validate with controlled comparisons.

## Community starting points

- [V620 stack selection](https://blivioniag.github.io/gfx1030-wiki/choose-a-stack.html):
  ROCm/HIP llama.cpp RDNA2 fork for GGUF and low concurrency; vLLM RDNA extras
  for batching and prefix-cached multi-agent workloads. Both are legitimate
  candidates, not a blanket claim that one always wins.
- [vLLM quantization](https://blivioniag.github.io/gfx1030-wiki/vllm/quantization.html):
  GPTQ can select the native `RDNA2W4A16LinearKernel`; inspect the actual
  log. Community also reports native AWQ dispatch on some versions, so check
  the exact checkpoint, fork and image rather than assuming all AWQ is slow.
- [llama.cpp backends](https://blivioniag.github.io/gfx1030-wiki/llama-cpp/building.html):
  Vulkan is a real option on some AMD systems, but that V620 page reports RADV
  hard crashes and recommends HIP for multi-GPU tensor split. These are
  community reports, not a local test. Do not silently run crash-prone Vulkan
  tensor-parallel experiments on a shared host.
- [V620 llama.cpp fork](https://blivioniag.github.io/gfx1030-wiki/llama-cpp/rdna2-overview.html)
  and [community benchmarks](https://blivioniag.github.io/gfx1030-wiki/llama-cpp/rdna2-benchmarks.html):
  the gfx1030-tuned ROCm fork is worth an A/B against vLLM. Community numbers
  and model quantizations differ; none predicts this VM's throughput.

Compare identical or clearly stated model/quantization, context, prompt,
output length, concurrency, cache state and hardware; measure warm TTFT,
prefill, decode and correctness. Stream API output while testing. Comparing
GPTQ against GGUF is useful operationally but is not an isolated backend A/B.

## Qwen3.8-27B GPTQ, vLLM TP2 (2026-11-22)

The text-only `qwen3.8-27b-gptq-benchmark` endpoint loaded on both V620s
with `RDNA2W4A16LinearKernel`, FP16 KV, and a configured 262,144-token
limit. A repeat streamed 32-token prompt generated 53 output tokens with
0.23 s to first token, 2.11 s elapsed, and approximately 27.7 decode
tokens/s. This confirms serving and short-context decoding—not a full
262K request or a head-to-head result against llama.cpp. The 3.26 tokens/s
AWQ baseline used a different model as well as different quantization.
