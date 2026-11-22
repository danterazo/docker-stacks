# Experimental llama.cpp RDNA2 stack

This is an **alternative**, not a companion, to vLLM: don't build or start it while vLLM is initializing or benchmarking, and don't run both engines on these GPUs at once. Nothing starts automatically. This stack has not yet been built or run on this VM.

It uses [edwinbrowwn/llama.cpp-rdna2](https://github.com/edwinbrowwn/llama.cpp-rdna2) at `e194cbddce45178467cef4afab0e3400ea357406`, on the locally present `blivioniag/vllm-rdna:v0.31.0-extras` ROCm 7.14 image pinned by digest. It builds HIP for `gfx1030` with RCCL required; speculative sidecars and the web UI are not built. GitHub must be reachable for the source fetch. Reproducibility also depends on the pinned base image remaining available; overrides to build arguments change the build.

The initial model is the existing Qwen3.5-35B-A3B Q4_K_M GGUF under `/tank/models`, mounted read-only. Edit `LLAMA_MODEL` to another path **relative to `/tank/models`**; no model is downloaded. The model file must be readable by the configured UID and the NAS must already be mounted. The ~20 GiB model, context, build cache and memory-mapped pages can pressure this VM's 15 GiB RAM, nearly exhausted swap and limited root disk. One build job is the default, not a guarantee of success. Check available RAM, swap and root space first; stop if resources are inadequate. The build can take significant time and disk. No disk cleanup is performed by these instructions.

## First trial (only after the vLLM benchmark is finished)

1. Stop vLLM using its own documented procedure and verify it has released GPU memory. Do not stop or change other services without authorization.
2. From this directory:

   ```sh
   cp .env.example .env
   ```

   Check the LAN IP (`ip -br -4 addr`), UID/GID (`id`) and device groups (`ls -ln /dev/kfd /dev/dri`). Update `.env` if needed. The current two-card default is `LLAMA_TENSOR_SPLIT=1,1`; for four V620s, use `1,1,1,1` after independently validating the new hardware/topology. All visible HIP GPUs are available to the server; verify the startup logs show the expected devices and split. Adjust `LLAMA_CONTEXT_SIZE` only after observing memory usage.
3. Validate, build, and start explicitly:

   ```sh
   docker compose config --quiet
   docker compose build
   docker compose up -d --no-build
   docker compose logs -f llama-cpp
   ```

4. Once ready, check the endpoint and send a small OpenAI-compatible test:

   ```sh
   curl -f http://192.168.30.105:8080/health
   curl -f http://192.168.30.105:8080/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"messages":[{"role":"user","content":"Say hello briefly."}],"max_tokens":32}'
   ```

   Replace the address and port with the values in `.env`. Health returns 503 while loading and 200 when ready; Docker's 15-minute start period is not a startup deadline. Inspect logs and GPU memory if unhealthy. The LAN endpoint has **no authentication**: restrict access using the network/firewall, and do not expose it to untrusted networks. Only a text GGUF is configured, not a vision projector.
5. After testing, stop it and verify GPU memory is released before returning to vLLM:

   ```sh
   docker compose down
   ```

## Multi-GPU and safety notes

The initial configuration uses llama.cpp's layer split, not its experimental tensor-parallel mode, with Flash Attention, 8192 context and one request slot. This is a conservative starting point, not a performance or fit guarantee; Qwen3.5 support, correctness, throughput, VRAM and context fit must be tested on this exact two-card VM. The fork's README primarily describes a tested four-V620 tensor-split setup, not this two-card VM. Compare equivalent workloads and context against vLLM before choosing one engine.

ROCm peer access is currently disabled on this VM. The stack does not force direct P2P; it sets `NCCL_P2P_DISABLE=1` and disables the fork's broad `GGML_HIP_RDNA2_AUTO` profile, including its automatic host-snapshot all-reduce optimizations. This also disables other RDNA2 auto optimizations, so performance may be lower. Do not set `GGML_CUDA_P2P=0`: this fork checks for the variable's **presence**. At the pinned revision, the fork can independently enable HIP peer access on a qualified four-V620 hop-2 topology when HIP reports every peer accessible, even with RDNA2 Auto disabled; reassess that source behavior and topology before a four-card deployment. RCCL is compiled in but layer split does not establish that RCCL collectives are being used. No P2P, RCCL tensor-split performance, stability, or four-card behavior is claimed here.

The source build and runtime use the same pinned base image, but availability of its ROCm compiler, RCCL development files and dynamic dependencies has not been verified by an actual build. The build fails if required components are missing. If an ROCm illegal-memory fault occurs, treat subsequent results as unreliable until the affected GPU is reset or the VM rebooted through an approved procedure.
