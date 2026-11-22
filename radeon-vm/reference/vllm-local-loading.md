# Qwen3.8 Local Load Test

On 2026-11-22, `qwen3.8-27b-gptq` was loaded on two V620s with the same
262144-token, TP2 settings from the new local ext4 filesystem on VM 105's
200 GiB ZFS-backed model disk. The measured vLLM weight-loading phase was
25.63 seconds, versus 178.37 seconds observed in a prior NFS-backed startup
with the same checkpoint and settings: approximately 7.0 times faster in these
single runs. Caches, system load and timing conditions were not controlled;
this is not a cold-cache or repeated statistical benchmark.

The local run reached `/health` 125.03 seconds after Compose was invoked,
including 10.96 seconds for container recreation. Both tensor-parallel ranks
reported about 29 seconds for model loading, and a short chat request returned
`OK`. Other model-copy verification was paused during the measurement. The
local disk was temporarily mounted from `/srv/vllm-models` into the container
for this test; the intended persistent layout is `/models/vllm`.

`amd-smi metric -P` reported PCIe generation/width but `N/A` for current
bandwidth sent and received for both V620s. The guest driver exposed no
`pcie_bw` sysfs counter; no actual GPU PCIe RX/TX rates were measured.
