# Opt-in Flash-Next experiment

Do not use this stack on the current two-card VM. On 2026-11-22 the guest
reported 15 GiB RAM and two V620s with no direct peer access. Kveikur reported
30 GiB total RAM and a 16 GiB VM 105 allocation. The script's four-card,
48 GiB total guest RAM, and 32 GiB free RAM requirements are conservative
experiment gates, not requirements established by a successful run.

## Assets and memory placement

| Asset | Source | Revision |
| --- | --- | --- |
| vLLM + RDNA launcher | `blivioniag/vllm-rdna:v0.31.0-extras` | image digest `16cbf6a09c879b2c69012c60bed4eb935e3029839bc641d1a9574931e8b9f127` |
| Main checkpoint | `wtdcode/Qwen3.8-Flash-Next-AWQ-W4A16` | `0939125b929543a783ce700c90e36dd1a575c00c` |
| PLE sidecar | `primitive-ai/Qwen3.8-Flash-Next-PLE-quant`, `ples_int4/` only | `a0fa93f2b9ed5fcab0cf01b60e88ff1ce13a4763` |
| Alternate llama.cpp trial | `unsloth/Qwen3.8-Flash-Next-GGUF`, `UD-Q3_K_XL/` | `f5d175de2cf7f720d45d6064019a81fcf056e986` |

The exact launch recipe is bundled inside the pinned image at
`/src/vllm/tools/rdna/recipes/flashnext-mtp0.env`; do not fetch or mix in
launcher files from a different branch. The launcher and loader were inspected
and the Compose dry run succeeded against the NAS mounts; this did not load
any weights. The 168 GiB download includes a roughly 95 GiB BF16 embedding
shard. `PLE=int4-disk` uses the separate 29.8 GiB mapped INT4 table instead
of pinning the BF16 table. The other main shards total about 68 GiB on disk
(excluding the optional draft). Also budget for repacking/temporary
allocations, cache and graphs; disk sizes are not memory measurements. On
56 GB DDR4 do not enable host KV or expert offload for the initial trial.
Prefer an SSD with adequate separate capacity for the sidecar. The VM's root
disk is not a good staging destination for another ~30 GiB of files.

## Dry run and first trial

From this directory:

```sh
docker compose -f compose.flash-next.yaml --profile experiment config --quiet
docker compose -f compose.flash-next.yaml run --rm --no-deps flash-next --print
```

After all downloads are hash-verified, confirm four usable V620s, enough RAM
allocated to the guest, and actual SSD/NAS latency. Stop the primary vLLM
service before reserving the GPUs for the experiment. The experiment binds
only to `127.0.0.1:8001` and will not restart on failure:

```sh
docker compose stop vllm
docker compose -f compose.flash-next.yaml --profile experiment up -d
docker compose -f compose.flash-next.yaml logs -f flash-next
```

The launch wrapper gates startup on the hardware and expected file sizes,
then selects TP4, expert parallelism, text only, one sequence, FP16, 32K,
and no speculative decoding, CPU KV offload, P2P or custom all-reduce. It
uses the bundled upstream preset for graph mode and KV-cache budget.
Use `FLASH_NEXT_PLE` for an alternate SSD-backed path; mount it before
starting. Use `FLASH_NEXT_CONTEXT` to test 128K, then 262,144, after measuring
available cache and actual throughput. `FLASH_NEXT_KV_BYTES` is a per-GPU
cache budget; do not increase it without measuring free memory on every GPU.

Verify streaming text correctness, TTFT, decode rate, then structured tool
calls after enabling the appropriate tool parser. Record full prompt length,
actual output, KV pool, RAM/swapping and PLE read latency. Try multi-agent
concurrency and MTP only after the one-stream baseline. The community tests
do not establish performance on this VM's no-P2P topology. Start with native
262K maximum; 1M requires the publisher's YaRN override and a separate
runtime/quality test. It is not enabled in this stack.

Rollback (does not change checkpoints):

```sh
docker compose -f compose.flash-next.yaml --profile experiment down
docker compose up -d vllm
```

References: [V620 recipe and caveats](https://blivioniag.github.io/gfx1030-wiki/vllm/flash-next-serve.html),
[Qwen's model card and scaling override](https://huggingface.co/Qwen/Qwen3.8-Flash-Next#best-practices).
