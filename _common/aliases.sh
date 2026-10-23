#!/bin/bash

# docker-compose-v2 syntax
alias dcp="docker compose pull"
alias dcd="docker compose down"
alias dcu="docker compose up -d"
alias dcr="docker compose restart"
alias dcl="docker compose logs -f"
alias logs="docker compose logs -f"

# list commands
alias dimg="docker image ls"
alias dnet="docker network ls"
alias dvol="docker volume ls"

# compose with project name inferred from folder
alias dcuu="docker compose up -d --remove-orphans"
alias dcpb="docker compose build --pull"

# package management
alias upgrade='sudo apt-get update && sudo apt-get dist-upgrade -y && sudo apt-get clean && sudo apt-get autoremove -y --purge'

# system state
alias bootstrap='cd /docker && { if [[ ${EUID} -eq 0 ]]; then runuser -u dante -- git pull --ff-only; else git pull --ff-only; fi; } && bash -O extglob /docker/bootstrap.sh'
