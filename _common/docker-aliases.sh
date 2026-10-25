#!/bin/bash

: 'Docker Compose'
alias dcd="docker compose down"
alias dcu="docker compose up -d"
alias dcb="docker compose up -d --build"
alias dcr="docker compose down && docker compose up -d" # docker compose refresh
alias dprune="docker system prune --all --force"
alias dxi="docker exec -t" # run command inside container

: 'Application Backups & Maintenance'
alias immich-bkp='sudo docker exec -t immich_postgres pg_dumpall --clean --if-exists --username=postgres | gzip > /mnt/hdd-pool/app-data/immich/backups/manual/immich_backup_$(date -I).sql.gz'
alias dawarich-bkp='sudo docker exec -t dawarich-db pg_dumpall --clean --if-exists --username=postgres | gzip > /mnt/hdd-pool/app-data/dawarich/backups/dawarich_backup_$(date -I).sql.gz'
alias caddy-rf="sudo docker exec -t caddy sh -c 'caddy fmt --overwrite /etc/caddy/Caddyfile && caddy reload --config /etc/caddy/Caddyfile'"
