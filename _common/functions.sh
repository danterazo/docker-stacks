#!/bin/bash

# source common aliases
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/utility-aliases.sh" || return 1

# pull Git and Docker registry images, then rebuild and recreate stacks
dpull() {
	# local variables
	local root_dir="/docker"
	local branch
	local app_dir
	local active_services

	# check Git init status
	if [ ! -d "$root_dir/.git" ]; then
		echo "ERROR: .git directory missing from Docker configuration repository!"
		return 1
	fi

	# ensure /docker is trusted by git regardless of ownership context
	git config --global --replace-all safe.directory /docker || true

	# pull latest changes from Git
	cd "$root_dir" || return 1
	branch=$(git branch --show-current) || return 1
	if [ "$branch" != "main" ]; then
		echo "ERROR: Docker updates require the main branch."
		return 1
	fi
	git fetch origin main || return 1
	if ! git merge-base --is-ancestor HEAD FETCH_HEAD; then
		echo "ERROR: Local Docker repository is ahead of or diverged from origin/main."
		return 1
	fi
	git merge --ff-only FETCH_HEAD || return 1

	# iterate over each app directory and run Docker Compose commands
	for app_dir in "$root_dir"/*/; do
		[ -d "$app_dir" ] || continue
		[ -f "$app_dir/compose.yaml" ] || [ -f "$app_dir/compose.yml" ] || continue

		cd "$app_dir" || return 1
		local -a compose_cmd=(docker compose)
		if [[ ${HOSTNAME%%.*} == radeon-vm && ${app_dir%/} == "$root_dir/llama-cpp" ]]; then
			# preserve the VM-specific settings and never start an inactive experiment
			local project=${app_dir%/}
			project=${project##*/}
			if [[ ${DPULL_VM_STACKS+x} ]]; then
				case " ${DPULL_VM_STACKS} " in
					*" $project "*) active_services=$project ;;
					*) continue ;;
				esac
			else
				active_services=$(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.ID}}') || return 1
			fi
			[ -n "$active_services" ] || continue
			[ -f .env.vm.local ] && [ -f compose.vm.yaml ] || { echo "ERROR: VM Compose settings missing in $app_dir" >&2; return 1; }
			compose_cmd=(docker compose --env-file .env.vm.local -f compose.vm.yaml)
		else
			active_services=$("${compose_cmd[@]}" config --services) || return 1
		fi
		[ -n "$active_services" ] || continue
		"${compose_cmd[@]}" pull --ignore-buildable || return 1
		"${compose_cmd[@]}" build --pull --no-cache || return 1
		"${compose_cmd[@]}" up --build -d --remove-orphans || return 1
	done
}

# bootstrap, then pull Git again and Docker registry images via dpull
dbpull() {
	bootstrap && dpull
}

# upgrade packages, then pull Git and Docker registry images via dpull
dupull() {
	upgrade && dpull
}

# upgrade packages, bootstrap, then pull Git again and Docker registry images via dpull
dubpull() {
	upgrade && dbpull
}

# upgrade packages, pull Git and Docker registry images via dpull, then reboot
durpull() {
	dupull && sudo reboot
}

# upgrade packages, bootstrap, pull Git again and Docker registry images via dpull, then reboot
durbpull() {
	dubpull && sudo reboot
}
