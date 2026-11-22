#!/usr/bin/env bash
set -euo pipefail

case ${1:---serve} in
    --print) export PRINT=1 ;;
    --serve)
        # These are conservative gates for this experiment, not proven minimums.
        python - <<'PY'
from pathlib import Path
import json

def require(ok, message):
    if not ok:
        raise SystemExit(message)

mem = {line.split(':', 1)[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:', 'MemAvailable:'))}
require(mem['MemTotal'] >= 48 * 1024**2 and mem['MemAvailable'] >= 32 * 1024**2,
        'Experiment requires at least 48 GiB VM RAM and 32 GiB currently available.')
cards = []
for node in Path('/sys/class/drm').glob('renderD*'):
    dev = node / 'device'
    if not (Path('/dev/dri') / node.name).exists():
        continue
    if (dev / 'vendor').read_text().strip() == '0x1002' and (dev / 'device').read_text().strip() == '0x73a1':
        cards.append(dev.resolve())
require(len(set(cards)) == 4, 'Experiment requires four visible V620 render devices.')
for card in cards:
    require(int((card / 'mem_info_vram_used').read_text()) < 1024**3,
            f'{card.name} already has over 1 GiB VRAM allocated; stop competing workloads first.')

def expect(path, n):
    require(path.is_file() and path.stat().st_size == n, f'Missing or wrong size: {path}')

# Pinned download file sizes, not a substitute for checksum verification.
for i, n in enumerate((102400512288, 20007503112, 19960933248, 20008579224, 13134032728), 1):
    expect(Path(f'/model/model-{i:05d}-of-00005.safetensors'), n)
for i in range(128):
    expect(Path(f'/ples_int4/shard_{i}.safetensors'), 250001376)
json.loads(Path('/ples_int4/META.json').read_text())
PY
        ;;
    *) echo 'Expected --serve or --print' >&2; exit 2 ;;
esac

# Use the exact recipe shipped in the pinned image, not a moving Git branch.
# The launcher can clean up processes, so run it only inside this container.
exec bash /src/vllm/tools/rdna/serve_rdna.sh RECIPE=flashnext-mtp0 \
    MODEL=/model VENV=/usr PLE=int4-disk PLE_QUANT_DIR=/ples_int4 \
    HOST=0.0.0.0 PORT=8000 TP=4 SEQS=1 TUNABLEOP=0 TUNED_CONFIG=0 \
    MAXLEN="${FLASH_NEXT_CONTEXT:-32768}" KV="${FLASH_NEXT_KV_BYTES:-4026531840}" \
    RUN_CWD=/tmp VLLM_CACHE_ROOT=/state/flash-next/vllm TRITON_CACHE_DIR=/state/flash-next/triton \
    TORCHINDUCTOR_CACHE_DIR=/state/flash-next/inductor TORCH_EXTENSIONS_DIR=/state/flash-next/extensions \
    NCCL_P2P_DISABLE=1 VLLM_RDNA_AR=0 VLLM_FORCE_CUSTOM_ALL_REDUCE=0 \
    'FEATURES=expert-parallel prefix-caching mamba-align language-model-only skip-mm-profiling' \
    "EXTRA_ARGS=--disable-custom-all-reduce --kv-cache-dtype float16 --reasoning-parser ${FLASH_NEXT_REASONING_PARSER:-qwen3}"
