SHELL := /bin/bash
EXCLUDES := \( -path './.git' -o -path './.venv' -o -path './venv' -o -path './node_modules' -o -path './.vscode' -o -path './.undeployed' -o -path './tabby/source' \) -prune -o

WSL2_COMPOSE := docker compose --project-directory "$(CURDIR)" -f "$(CURDIR)/compose.wsl2.yaml"

.PHONY: wsl2
wsl2:
	@[[ "$$(uname -r)" == *microsoft*WSL2* ]] || { echo 'make wsl2 is for WSL2, not server deployment.' >&2; exit 1; }
	@[[ -f audiomuse/.env.local && -f audiomuse/local.secrets ]] || { echo 'Configure audiomuse/.env.local and audiomuse/local.secrets using audiomuse/reference/local.*.example first.' >&2; exit 1; }
	@if docker container inspect immich-ml >/dev/null 2>&1; then echo 'The existing immich-ml container must be migrated before make wsl2 can publish port 3003. No containers were changed.' >&2; exit 1; fi
	$(WSL2_COMPOSE) config --quiet
	$(WSL2_COMPOSE) up -d --no-deps immich-ml audiomuse-worker

.PHONY: fix format fix-text fix-shell fix-javascript lint-compose-spacing lint-docker lint-docker-inner fix-caddy fix-caddy-inner deps clean

# format everything
format: fix-python fix-shell fix-javascript fix-caddy lint-compose-spacing lint-docker

.PHONY: test-shell-helpers
test-shell-helpers:
	bash scripts/test-shell-helpers.sh

# alias
fix: format

fix-text:
	prettier --write .

fix-javascript:
	git ls-files -z --cached --others --exclude-standard -- '*.js' '*.mjs' '*.cjs' \
		| xargs -0 -r prettier --write

lint-compose-spacing:
	python scripts/lint-compose-spacing.py

lint-docker:
	newgrp docker -c '$(MAKE) --no-print-directory lint-docker-inner'

lint-docker-inner:
	find . \( -path './.git' -o -path './.venv' -o -path './venv' -o -path './node_modules' -o -path './.vscode' -o -path './tabby/source' -o -path './.undeployed/tabby/source' \) -prune -o -type f \( -name 'Dockerfile' -o -name 'Dockerfile.*' \) -print0 \
		| xargs -0 -I {} sh -c 'docker buildx build --check --file "$$1" "$$(dirname "$$1")"' _ {}

fix-caddy:
	newgrp docker -c '$(MAKE) --no-print-directory fix-caddy-inner'

fix-caddy-inner:
	find caddy/configs -type f \( -name 'Caddyfile*' -o -name '*.conf' \) -printf '%P\0' \
		| xargs -0 -r -I {} docker run --rm \
			--user "$$(id -u):$$(id -g)" \
			--mount "type=bind,source=$(CURDIR)/caddy/configs,target=/etc/caddy" \
			caddy:alpine caddy fmt --overwrite "/etc/caddy/{}"

fix-python:
	ruff check --fix .
	ruff format .

fix-shell:
	find . $(EXCLUDES) -type f \( -name '*.sh' -o -name '*.bash' -o -name '.bashrc' -o -name '.profile' \) -print0 \
		| xargs -0 -r shfmt -w -i 0

deps:
	poetry lock
	poetry update
	poetry install

clean:
	find . -type f ! -path './.git/*' \
		\( -name '*.sync-conflict-*' -o -name 'Zone.Identifier' -o -name '*:Zone.Identifier' \) -print -delete
