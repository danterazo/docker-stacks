#!/bin/bash

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
	for app_dir in "$root_dir"/*/ "$root_dir"/radeon-vm/*/; do
		[ -d "$app_dir" ] || continue
		[ -f "$app_dir/compose.yaml" ] || [ -f "$app_dir/compose.yml" ] || continue

		cd "$app_dir" || return 1
		active_services=$(docker compose config --services) || return 1
		[ -n "$active_services" ] || continue
		docker compose pull --ignore-buildable || return 1
		docker compose build --pull --no-cache || return 1
		docker compose up --build -d --remove-orphans || return 1
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
