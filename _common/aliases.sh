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

# system state
bootstrap() {
	cd /docker || return 1
	if [[ ${EUID} -eq 0 ]]; then
		runuser -u dante -- git pull --ff-only || return 1
	else
		git pull --ff-only || return 1
	fi
	bash -O extglob /docker/bootstrap.sh
}
