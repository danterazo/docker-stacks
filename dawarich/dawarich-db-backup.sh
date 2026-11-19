#!/bin/bash

if (return 0 2>/dev/null); then
	printf 'Run the backup with bash; do not source it\n' >&2
	return 1
fi

set -euo pipefail

stack_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
backup_dir="$stack_dir/backups"
mkdir -p -- "$backup_dir"
backup_file="$backup_dir/dawarich-$(date +%Y-%m-%d_%H-%M-%S-%N).dump"
temporary_file="$(mktemp "$backup_dir/.dawarich.XXXXXX")"
trap 'rm -f -- "$temporary_file"' EXIT

docker compose --project-directory "$stack_dir" -f "$stack_dir/compose.yaml" exec -T dawarich-db \
	sh -c 'exec pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' >"$temporary_file"

if [[ ! -s $temporary_file ]]; then
	printf 'Database backup is empty; not publishing %s\n' "$backup_file" >&2
	exit 1
fi

mv -- "$temporary_file" "$backup_file"
printf 'Database backup saved to %s\n' "$backup_file"
