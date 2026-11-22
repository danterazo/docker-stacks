# Hugging Face model library reorganization

On 2026-11-22, `/tank/models/language-models/safetensors` was renamed to
`/tank/models/language-models/hf_safetensors`. It is a directory inside the
`tank/models` ZFS dataset, not a separate dataset. Existing model directories
are moved within that filesystem, preserving their files. New downloads use
`hf_safetensors/<publisher>/<repository>`; model names and quantization remain
in the model folder name. No estimated VRAM buckets are used.

The legacy directories below were moved as follows (all paths are relative to
`hf_safetensors`). The `local` publisher means that the exact source repository
or quantizer could not be established from the existing files; do not treat it
as a Hugging Face organization. Original model-directory names are preserved.

| Previous path | New path |
| --- | --- |
| `coding/16gb/nous-coder-14b` | `NousResearch/nous-coder-14b` |
| `coding/96gb/deepseek-coder-v2-236b-awq` | `local/deepseek-coder-v2-236b-awq` |
| `coding/96gb/qwen2.5-coder-32b` | `Qwen/qwen2.5-coder-32b` |
| `multimodal/8gb/paddleocr-vl` | `local/paddleocr-vl` |
| `multimodal/96gb/intellect-3-awq-4bit` | `local/intellect-3-awq-4bit` |
| `multimodal/96gb/intellect-3-nvfp4` | `local/intellect-3-nvfp4` |
| `multimodal/96gb/internvl2-llama3-76b` | `OpenGVLab/internvl2-llama3-76b` |
| `multimodal/96gb/llava-next-72b` | `local/llava-next-72b` |
| `reasoning/8gb/deepseek-r1-distill-qwen-1.5b` | `deepseek-ai/deepseek-r1-distill-qwen-1.5b` |
| `reasoning/96gb/deepseek-r1-qwen-32b` | `deepseek-ai/deepseek-r1-qwen-32b` |
| `text-only/16gb/qwen3-32b-awq` | `local/qwen3-32b-awq` |
| `text-only/96gb/llada2.0-mini` | `inclusionAI/llada2.0-mini` |
| `text-only/96gb/llama-3.1-405b-awq` | `hugging-quants/llama-3.1-405b-awq` |
| `text-only/96gb/llama-3.1-70b-awq` | `hugging-quants/llama-3.1-70b-awq` |
| `text-only/96gb/mistral-large-2-123b-awq` | `local/mistral-large-2-123b-awq` |
| `text-only/96gb/qwen2.5-72b-awq` | `local/qwen2.5-72b-awq` |

The active Qwen3 checkpoint was moved and its Compose `.env` path updated;
check any other consumers of the old paths before updating them. KV-cache and
total VRAM depend on runtime, quantization, context, concurrency and GPU count;
record measured or explicitly estimated configurations separately instead of
using a model-directory size suffix as a promise of fit.

## `local/` provenance research

The `local` label does not mean these models were created locally. Read-only
comparison of configuration and/or index file Git blob hashes found these
likely source repositories (weight-file checks are separate):

| Directory under `local/` | Hugging Face candidate | Evidence |
| --- | --- | --- |
| `deepseek-coder-v2-236b-awq` | `casperhansen/deepseek-coder-v2-instruct-awq` | config, index, README and first shard match |
| `intellect-3-awq-4bit` | `cyankiwi/INTELLECT-3-AWQ-4bit` | README named it and first shard matched retained download metadata; repository returned HTTP 401 without authentication. **Local directory deleted at user request on 2026-11-22.** |
| `intellect-3-nvfp4` | `Firworks/INTELLECT-3-nvfp4` | local HF download metadata identifies public revision `700247d3d81c7f83f9027e446e30b58ecb1bb78f`; config, index and first shard match |
| `llava-next-72b` | `lmms-lab/llava-next-72b` | config, index, README and first shard match |
| `mistral-large-2-123b-awq` | `casperhansen/mistral-large-instruct-2407-awq` | config, index and first shard match; another repo shares the index but not the first shard |
| `paddleocr-vl` | `PaddlePaddle/PaddleOCR-VL` | config and model weights match public 2025-11-11 revision `466ad1332bab28ff5aec6880864d3e30079bf3ff` |
| `qwen2.5-72b-awq` | `Qwen/Qwen2.5-72B-Instruct-AWQ` | config, index and first shard match |
| `qwen3-32b-awq` | `Qwen/Qwen3-32B-AWQ` | config, index and first shard match |

SHA-256 of the first safetensors shard matched the corresponding Hugging Face
weight for each of the seven publicly accessible repositories above. For the
inaccessible INTELLECT-3 AWQ repository, the first shard matched its retained
Hugging Face download metadata; the README identifies the repository, but its
current contents cannot be checked anonymously. These checks do **not** prove
that every shard or other file is identical. The directories were not moved
again during this research; subsequently the user requested deletion of the
inaccessible INTELLECT-3 AWQ copy. The Qwen3 checkpoint remains the configured
fallback at that time. The later cleanup below supersedes those paths.

## Compatibility audit: 2026-11-22

Five missing upstream files were restored without overwriting existing files:
`modeling_intern_vit.py` and `modeling_internvl_chat.py` in the InternVL2
folder, `merges.txt` in the Qwen2.5-Coder folder, and `LICENSE` and
`README.md` in the DeepSeek-R1-Distill-Qwen-1.5B folder. Their Git blob
hashes were checked against pinned public revisions. Model code was not run.

The newer PaddleOCR-VL checkpoint was separately staged at
`PaddlePaddle/PaddleOCR-VL`, revision `dae2996584399c9fb7eabfeecf8acd2c7cae95b7`,
with repository files and hashes verified. The older `local/paddleocr-vl`
remains for rollback; the new version has not yet been runtime-tested.
Current LLaDA2 source changes attention-mask behavior. The newer version is
staged separately at `inclusionAI/LLaDA2.0-mini-upstream`, revision
`dad945cac317da394b390f82c7b40691d8a881ed`; all 16 files were hash-verified.
It requires runtime testing before replacing the old copy.
Several legacy folders lack complete recorded checksums: matching an index or
file size does not establish that every weight file is current or unmodified.

## Non-AWQ replacements

`JunHowie/Qwen3-32B-GPTQ-Int4` was downloaded separately as a same-base
alternative to `local/qwen3-32b-awq`. Its configuration, five indexed shards
and repository file sizes were checked; the weights have not been independently
hashed or tested on this V620 VM.

### Cleanup: 2026-11-22

The user requested removal of AWQ copies with downloaded alternatives, and of
the 405B outright. The running Qwen3.8 GPTQ settings were saved in Compose before
removing the old Qwen3 AWQ default. Sizes below count safetensors weights only.

| Removed folder | Original weights |
| --- | ---: |
| `cyankiwi/Qwen3.8-27B-AWQ-INT4` | 19.57 GiB |
| `local/qwen3-32b-awq` | 18.00 GiB |
| `QuantTrio/Qwen3.5-35B-A3B-AWQ` | 23.71 GiB |
| `local/qwen2.5-72b-awq` | 38.74 GiB |
| `hugging-quants/llama-3.1-70b-awq` | 37.04 GiB |
| `hugging-quants/llama-3.1-405b-awq` | 204.22 GiB |
| `local/intellect-3-nvfp4` | 57.68 GiB |
| `local/mistral-large-2-123b-awq` | 60.44 GiB |

The replacement INTELLECT-3.1 Q4_K_M GGUF was checksum-verified before removal
of INTELLECT-3 NVFP4. Download verification does not establish runtime fit.
Both replacement Mistral Large 2407 Q4_K_M GGUF shards passed SHA-256
verification before removal of the old AWQ copy.

### Reporting download progress

Report a separate percentage and ETA for each model. Use the expected bytes
of the selected files at the pinned upstream revision, not the entire repo
when fetching one quantization. For active jobs without transfer counters,
estimate from two timed samples of completed and incomplete file sizes and
label the percentage and ETA as approximate. Sparse or preallocated partial
files can make size-based estimates unreliable. Say when no useful rate is
available instead of guessing. At 100%, distinguish transfer complete from
checksum verification complete; the transfer ETA does not include hashing.
