SHELL := /bin/bash
EXCLUDES := \( -path './.git' -o -path './.venv' -o -path './venv' -o -path './node_modules' -o -path './.vscode' -o -path './.undeployed' -o -path './tabby/source' \) -prune -o

.PHONY: fix format fix-text fix-shell lint-compose-spacing lint-docker fix-caddy deps clean

# format everything
format: fix-python fix-shell fix-caddy lint-compose-spacing lint-docker

# alias
fix: format

fix-text:
	prettier --write .

lint-compose-spacing:
	python scripts/lint-compose-spacing.py

lint-docker:
	find . \( -path './.git' -o -path './.venv' -o -path './venv' -o -path './node_modules' -o -path './.vscode' -o -path './tabby/source' -o -path './.undeployed/tabby/source' \) -prune -o -type f \( -name 'Dockerfile' -o -name 'Dockerfile.*' \) -print0 \
		| xargs -0 -I {} sh -c 'docker buildx build --check --file "$$1" "$$(dirname "$$1")"' _ {}

fix-caddy:
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
