#!/usr/bin/env bash
if (return 0 2>/dev/null); then
	printf 'Do not source run-aider-benchmark.sh; run it as a standalone script.\n' >&2
	return 1
fi
set -euo pipefail

AIDER_COMMIT=${AIDER_COMMIT:-5dc9490bb35f9729ef2c95d00a19ccd30c26339c}
POLYGLOT_COMMIT=${POLYGLOT_COMMIT:-7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f}
WORK_ROOT=${WORK_ROOT:-/tmp/ai/vllm-agent-benchmark}
AIDER_ROOT=$WORK_ROOT/aider
BENCHMARK_ROOT=$AIDER_ROOT/tmp.benchmarks
POLYGLOT_ROOT=$BENCHMARK_ROOT/polyglot-benchmark
IMAGE_NAME=${IMAGE_NAME:-aider-benchmark}
ENDPOINT=${VLLM_OPENAI_BASE_URL:-http://192.168.30.150:8000/v1}
MODEL=${VLLM_BENCHMARK_MODEL:-openai/qwen3.6-35b-a3b}
DEFAULT_THREADS=6
DEFAULT_TESTS=6
DEFAULT_TRIES=2
DEFAULT_NUM_CTX=65536

usage() {
	printf '%s\n' \
		'Usage:' \
		'  run-aider-benchmark.sh setup' \
		'  run-aider-benchmark.sh run [name] [tests] [threads] [languages] [tries]' \
		'  run-aider-benchmark.sh stats [run-directory]' \
		'' \
		'Defaults: name=qwen36-agent, tests=6, threads=6, languages=python, tries=2.' \
		'Override repository pins with AIDER_COMMIT and POLYGLOT_COMMIT.' \
		'Override the API with VLLM_OPENAI_BASE_URL and VLLM_BENCHMARK_MODEL.'
}

require_safe_work_root() {
	if [[ -L $WORK_ROOT || (-e $WORK_ROOT && ! -d $WORK_ROOT) ]]; then
		printf 'Refusing unsafe benchmark root: %s\n' "$WORK_ROOT" >&2
		return 1
	fi
	mkdir -p "$WORK_ROOT"
}

checkout() {
	local path=$1
	local url=$2
	local revision=$3
	if [[ ! -d $path/.git ]]; then
		git clone --filter=blob:none "$url" "$path"
	fi
	git -C "$path" fetch --prune origin
	git -C "$path" cat-file -e "$revision^{commit}"
	git -C "$path" -c advice.detachedHead=false checkout --detach "$revision"
}

setup() {
	require_safe_work_root
	command -v docker >/dev/null
	command -v git >/dev/null
	checkout "$AIDER_ROOT" https://github.com/Aider-AI/aider.git "$AIDER_COMMIT"
	mkdir -p "$BENCHMARK_ROOT"
	checkout "$POLYGLOT_ROOT" https://github.com/Aider-AI/polyglot-benchmark.git "$POLYGLOT_COMMIT"
	docker build --file "$AIDER_ROOT/benchmark/Dockerfile" --tag "$IMAGE_NAME" "$AIDER_ROOT"
}

api_key() {
	local script_dir
	script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
	local secrets=$script_dir/../.secrets
	[[ -r $secrets ]] || {
		printf 'Cannot read %s\n' "$secrets" >&2
		return 1
	}
	awk -F: '
		/^[[:space:]]*VLLM_API_KEY_KVEIKUR[[:space:]]*:/ {
			sub(/^[^:]*:[[:space:]]*/, "")
			gsub(/[[:space:]]/, "")
			print
			found++
		}
		END { if (found != 1) exit 1 }
	' "$secrets"
}

run_benchmark() {
	local name=${1:-qwen36-agent}
	local tests=${2:-$DEFAULT_TESTS}
	local threads=${3:-$DEFAULT_THREADS}
	local languages=${4:-python}
	local tries=${5:-$DEFAULT_TRIES}
	[[ $name =~ ^[a-zA-Z0-9._-]+$ ]] || {
		printf 'Invalid benchmark name: %s\n' "$name" >&2
		return 1
	}
	[[ $tests =~ ^[1-9][0-9]*$ ]] || {
		printf 'tests must be a positive integer\n' >&2
		return 1
	}
	[[ $threads =~ ^[1-9][0-9]*$ ]] || {
		printf 'threads must be a positive integer\n' >&2
		return 1
	}
	[[ $tries =~ ^[1-9][0-9]*$ ]] || {
		printf 'tries must be a positive integer\n' >&2
		return 1
	}
	[[ -d $AIDER_ROOT/.git && -d $POLYGLOT_ROOT/.git ]] || setup
	docker image inspect "$IMAGE_NAME" >/dev/null 2>&1 || setup
	local key
	key=$(api_key)
	[[ ${#key} -eq 64 && $key =~ ^[0-9a-f]+$ ]] || {
		printf 'VLLM_API_KEY_KVEIKUR is not a 64-character hexadecimal key\n' >&2
		return 1
	}
	export OPENAI_API_KEY=$key
	trap 'unset OPENAI_API_KEY' EXIT
	docker run --rm \
		--memory=12g \
		--memory-swap=12g \
		--pids-limit=1024 \
		--add-host=host.docker.internal:host-gateway \
		--mount "type=bind,source=$AIDER_ROOT,target=/aider,readonly" \
		--mount "type=bind,source=$BENCHMARK_ROOT,target=/benchmarks" \
		--env OPENAI_API_KEY \
		--env OPENAI_API_BASE="$ENDPOINT" \
		--env AIDER_DOCKER=1 \
		--env AIDER_BENCHMARK_DIR=/benchmarks \
		"$IMAGE_NAME" \
		./benchmark/benchmark.py "$name" \
		--model "$MODEL" \
		--edit-format whole \
		--threads "$threads" \
		--num-tests "$tests" \
		--languages "$languages" \
		--exercises-dir polyglot-benchmark \
		--tries "$tries" \
		--num-ctx "$DEFAULT_NUM_CTX" \
		--new
	unset OPENAI_API_KEY
}

show_stats() {
	local requested=${1:-}
	[[ -d $AIDER_ROOT/.git ]] || setup
	docker image inspect "$IMAGE_NAME" >/dev/null 2>&1 || setup
	local args=()
	if [[ -n $requested ]]; then
		args=("$requested" --stats)
	else
		args=(--stats)
	fi
	docker run --rm \
		--mount "type=bind,source=$AIDER_ROOT,target=/aider" \
		--mount "type=bind,source=$BENCHMARK_ROOT,target=/benchmarks" \
		--env AIDER_DOCKER=1 \
		--env AIDER_BENCHMARK_DIR=/benchmarks \
		"$IMAGE_NAME" \
		./benchmark/benchmark.py "${args[@]}"
}

case ${1:-} in
setup)
	setup
	;;
run)
	shift
	run_benchmark "${1:-}" "${2:-}" "${3:-}" "${4:-}" "${5:-}"
	;;
stats)
	shift
	show_stats "${1:-}"
	;;
help | --help | -h)
	usage
	;;
*)
	usage >&2
	exit 2
	;;
esac
