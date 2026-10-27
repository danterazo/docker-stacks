SHELL := /bin/bash
EXCLUDES := \( -path './.git' -o -path './.venv' -o -path './venv' -o -path './node_modules' -o -path './.vscode' -o -path './.undeployed' -o -path './tabby/source' \) -prune -o


# deploy local copies of certain apps' workers, s.t. the desktop's GPU can accelerate server workloads
WSL2_COMPOSE := docker compose --project-directory "$(CURDIR)" -f "$(CURDIR)/compose.wsl2.yaml"

.PHONY: wsl2
wsl2: export WSL_NVIDIA_DRIVER_DIR ?= $(shell find /usr/lib/wsl/drivers -maxdepth 2 -name libnvidia-ptxjitcompiler.so.1 -printf '%h\n' 2>/dev/null)
wsl2:
	@[[ "$$(uname -r)" == *microsoft*WSL2* ]] || { echo 'make wsl2 is for WSL2, not server deployment.' >&2; exit 1; }
	@[[ -f audiomuse/.secrets && -f immich/.secrets ]] || { echo 'Sync audiomuse/.secrets and immich/.secrets from the server before make wsl2.' >&2; exit 1; }
	@[[ -f "$(WSL_NVIDIA_DRIVER_DIR)/libnvidia-ptxjitcompiler.so.1" ]] || { echo 'Could not identify one NVIDIA WSL driver directory; set WSL_NVIDIA_DRIVER_DIR explicitly.' >&2; exit 1; }
	$(WSL2_COMPOSE) config --quiet
	$(WSL2_COMPOSE) up -d

.PHONY: logs
logs:
	docker compose --project-directory "$(CURDIR)" -p desktop-workers logs -f $(LOGS_ARGS) $(WORKERS)

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
	uv run python scripts/lint-compose-spacing.py

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
	uv run ruff check --fix .
	uv run ruff format .

fix-shell:
	find . $(EXCLUDES) -type f \( -name '*.sh' -o -name '*.bash' -o -name '.bashrc' -o -name '.profile' \) -print0 \
		| xargs -0 -r shfmt -w -i 0

deps:
	uv lock --upgrade
	uv sync --locked

clean:
	find . -type f ! -path './.git/*' \
		\( -name '*.sync-conflict-*' -o -name 'Zone.Identifier' -o -name '*:Zone.Identifier' \) -print -delete
