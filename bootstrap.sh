#!/bin/bash
if (return 0 2>/dev/null); then
	printf 'Run bootstrap with bash; do not source it\n' >&2
	return 1
fi
## bootstrap PVE Docker LXCs

: 'GLOBAL CONFIG'
HOST_NAME="$(hostname)"
HOME_DIR="/docker"
DOCKER_FALLBACK_SUITE="resolute" # latest LTS

: 'UPGRADE UBUNTU'
# upgrade to stable interim releases, but never to a development release.
sudo sed -i 's/^Prompt=.*/Prompt=normal/' /etc/update-manager/release-upgrades
sudo do-release-upgrade -f DistUpgradeViewNonInteractive

: 'MULTI-TENANT HOSTS'
declare -A HOST_APPS=(
	["nvidia-vm"]='immich plex-video audiomuse'
)

: 'SYSTEM CONFIG'
# enforce Central time on Docker VMs and LXCs
sudo timedatectl set-timezone America/Chicago || exit 1

# modify GRUB_CMDLINE_LINUX_DEFAULT
GRUB_FILE="/etc/default/grub"
CURRENT_GRUB=$(grep -oP '(?<=^GRUB_CMDLINE_LINUX_DEFAULT=")[^"]*' "$GRUB_FILE")
CLEANED_GRUB=$(echo "$CURRENT_GRUB" | sed -E 's/\bquiet\b//g' | xargs) # remove "quiet"

# apply grub changes only when the configuration changed
if [ "${CURRENT_GRUB}" != "${CLEANED_GRUB}" ]; then
	sudo sed -i -E "s|^GRUB_CMDLINE_LINUX_DEFAULT=\".*\"|GRUB_CMDLINE_LINUX_DEFAULT=\"${CLEANED_GRUB}\"|" "$GRUB_FILE" &&
		sudo update-grub || exit 1
fi

: 'INSTALL PACKAGES'
sudo apt-get update &&
	sudo apt-get install -y tree ca-certificates coreutils curl git software-properties-common nfs-common iotop bash-completion lsb-release direnv lrzsz shfmt || exit 1

# remove the obsolete fastfetch PPA if present
if grep -Rqs 'zhangsongcui3371/fastfetch' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
	sudo add-apt-repository --remove ppa:zhangsongcui3371/fastfetch -y || exit 1
fi

# remove any previously installed PPA build before installing from Ubuntu repositories
sudo apt-get remove -y fastfetch || exit 1
sudo apt-get update &&
	sudo apt-get install -y fastfetch || exit 1

: 'INSTALL DOCKER'
# add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg |
	sudo tee /etc/apt/keyrings/docker.asc >/dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc

# docker's repo can lag new ubuntu releases
DOCKER_SUITE="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
if ! curl -fsSI --max-time 15 "https://download.docker.com/linux/ubuntu/dists/${DOCKER_SUITE}/Release" >/dev/null; then
	echo "WARNING: Docker has no '${DOCKER_SUITE}' suite; using '${DOCKER_FALLBACK_SUITE}'"
	DOCKER_SUITE="${DOCKER_FALLBACK_SUITE}"
fi

# add the repository to apt sources
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${DOCKER_SUITE}
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update &&
	sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
		docker-buildx-plugin docker-compose-plugin || exit 1

: 'CONFIGURE DOCKER'
if [ ! -f /etc/docker/daemon.json ]; then
	sudo install -m 0755 -d /etc/docker
	sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
	"log-driver": "json-file",
	"log-opts": {
		"max-size": "20m",
		"max-file": "5"
	}
}
EOF

	# reload if systemd is available
	if command -v systemctl >/dev/null 2>&1; then
		sudo systemctl restart docker || true
	fi
fi

: 'INIT USER'
# create dante group if missing
if ! getent group dante >/dev/null; then
	sudo groupadd -g 1000 dante
fi

# create dante user if missing
if ! id -u dante >/dev/null 2>&1; then
	sudo useradd -u 1000 -g 1000 -m -d /home/dante -s /bin/bash dante
fi

# existing guests may have a root-owned home for dante
sudo chown dante:dante /home/dante

: 'GIT CONFIG'
# run Git as a user from a cwd they can read; /docker is owned by dante
user_git() {
	local user="$1"
	shift
	(cd / && sudo -u "${user}" -H env ${GIT_SSH_COMMAND:+"GIT_SSH_COMMAND=${GIT_SSH_COMMAND}"} git "$@")
}
dante_git() { user_git dante "$@"; }

for git_user in root dante; do
	user_git "${git_user}" config --global user.name "Dante Razo"
	user_git "${git_user}" config --global user.email "github.d2brf@simplelogin.fr"
	user_git "${git_user}" config --global pull.rebase false
	user_git "${git_user}" config --global --replace-all safe.directory /docker
	user_git "${git_user}" config --global alias.reset-origin '!git fetch origin && git reset --hard origin/$(git branch --show-current)'
done

: 'INIT CONFIG REPOSITORY'
sudo install -d -o dante -g dante "${HOME_DIR}"

# pre-seed GitHub host keys system-wide; source: https://api.github.com/meta (verified 2026-10-16)
KNOWN_HOSTS="/etc/ssh/ssh_known_hosts"
sudo touch "${KNOWN_HOSTS}"
sudo sed -i '/^github\.com /d' "${KNOWN_HOSTS}"
sudo tee -a "${KNOWN_HOSTS}" >/dev/null <<'EOF'
github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl
github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=
github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=
EOF

# TODO: set up SSH key sharing
# dante runs the /docker Git commands, so it needs the shared key too
if [ ! -f /home/dante/.ssh/id_ed25519 ] && [ -f /root/.ssh/id_ed25519 ] && [ -f /root/.ssh/id_ed25519.pub ]; then
	sudo install -d -m 700 -o dante -g dante /home/dante/.ssh
	sudo install -m 600 -o dante -g dante /root/.ssh/id_ed25519 /home/dante/.ssh/id_ed25519
	sudo install -m 644 -o dante -g dante /root/.ssh/id_ed25519.pub /home/dante/.ssh/id_ed25519.pub
fi

# fix SSH permissions, preferring dante's key over root's
SSH_DIR=""
for path in /home/dante/.ssh /root/.ssh; do
	if [ -f "${path}/id_ed25519" ] && [ -f "${path}/id_ed25519.pub" ]; then
		SSH_DIR="${path}"
		break
	fi
done

if [ -n "${SSH_DIR}" ]; then
	sudo chmod 700 "${SSH_DIR}"
	sudo chmod 600 "${SSH_DIR}/id_ed25519"
	sudo chmod 644 "${SSH_DIR}/id_ed25519.pub"
	export GIT_SSH_COMMAND="ssh -i ${SSH_DIR}/id_ed25519 -o IdentitiesOnly=yes"
fi

# install or update autoenv for both accounts without modifying shell startup files
AUTOENV_URL="git@github.com:hyperupcall/autoenv.git"
for autoenv_user in root dante; do
	autoenv_dir="$(getent passwd "${autoenv_user}" | cut -d: -f6)/.autoenv"
	if user_git "${autoenv_user}" -C "${autoenv_dir}" rev-parse --git-dir >/dev/null 2>&1; then
		if ! user_git "${autoenv_user}" -C "${autoenv_dir}" remote set-url origin "${AUTOENV_URL}"; then
			printf 'WARNING: Could not set the Autoenv remote for %s; continuing bootstrap.\n' "${autoenv_user}" >&2
		elif ! user_git "${autoenv_user}" -C "${autoenv_dir}" pull --ff-only; then
			printf 'WARNING: Could not update Autoenv for %s; continuing bootstrap.\n' "${autoenv_user}" >&2
		fi
	elif sudo -u "${autoenv_user}" test -e "${autoenv_dir}"; then
		printf 'WARNING: Existing Autoenv path is not a Git checkout; leaving it untouched: %s\n' "${autoenv_dir}" >&2
	else
		if ! user_git "${autoenv_user}" clone "${AUTOENV_URL}" "${autoenv_dir}"; then
			printf 'WARNING: Could not clone Autoenv for %s; continuing bootstrap.\n' "${autoenv_user}" >&2
		fi
	fi
done

REPO_URL="git@github.com:danterazo/docker-stacks.git"
REPO_CREATED=0
if [ ! -d "${HOME_DIR}/.git" ]; then
	# first-time setup; clone repository
	if ! dante_git clone "${REPO_URL}" "${HOME_DIR}"; then
		echo "ERROR: Failed to clone repository"
		exit 1
	fi
	REPO_CREATED=1
else
	# repo already exists; preserve its sparse-checkout configuration
	echo "WARNING: Repository already exists at ${HOME_DIR}; preserving checkout settings..."
	sudo chown dante:dante "${HOME_DIR}" || exit 1
	if [[ -d "${HOME_DIR}/.git" && ! -L "${HOME_DIR}/.git" ]]; then
		sudo chown -R dante:dante "${HOME_DIR}/.git" || exit 1
	elif [[ -f "${HOME_DIR}/.git" ]]; then
		sudo chown dante:dante "${HOME_DIR}/.git" || exit 1
	else
		echo "ERROR: Git metadata not found at ${HOME_DIR}/.git"
		exit 1
	fi
fi

# move to root-level repo directory
cd "${HOME_DIR}" || exit 1
if [ "${REPO_CREATED}" = "0" ]; then
	dante_git -C "${HOME_DIR}" remote set-url origin "${REPO_URL}" &&
		dante_git -C "${HOME_DIR}" pull --ff-only || exit 1
fi

# host-specific sparse profiles
read -r -a host_apps <<<"${HOST_APPS[${HOST_NAME}]:-${HOST_NAME}}"
sparse_paths=('/_common/' '/bootstrap.sh' '/.gitignore')
for app in "${host_apps[@]}"; do
	sparse_paths+=("/${app}/")
done
if [ "${REPO_CREATED}" = "0" ] && [ "$(dante_git -C "${HOME_DIR}" config --get core.sparseCheckout)" = "true" ]; then
	if [ "$(dante_git -C "${HOME_DIR}" config --get core.sparseCheckoutCone)" = "true" ]; then
		existing_paths="$(dante_git -C "${HOME_DIR}" sparse-checkout list)" || exit 1
		while IFS= read -r existing_path; do
			[ -n "${existing_path}" ] || continue
			[ "${existing_path}" = "+common" ] && existing_path="_common"
			[ "${existing_path}" = ".common" ] && existing_path="_common"
			sparse_paths+=("/${existing_path}/")
		done <<<"${existing_paths}"
	else
		existing_patterns="$(dante_git -C "${HOME_DIR}" rev-parse --git-path info/sparse-checkout)" || exit 1
		while IFS= read -r existing_pattern || [ -n "${existing_pattern}" ]; do
			existing_pattern="${existing_pattern//.common/_common}"
			sparse_paths+=("${existing_pattern//+common/_common}")
		done <"${existing_patterns}"
	fi
fi
declare -A seen_sparse_paths=()
unique_sparse_paths=()
for sparse_path in "${sparse_paths[@]}"; do
	[ -n "${sparse_path}" ] && [ "${sparse_path}" != '!/_common/radeon/' ] || continue
	[ -z "${seen_sparse_paths[${sparse_path}]+set}" ] || continue
	seen_sparse_paths["${sparse_path}"]=1
	unique_sparse_paths+=("${sparse_path}")
done
unique_sparse_paths+=('!/_common/radeon/')
dante_git -C "${HOME_DIR}" sparse-checkout set --no-cone "${unique_sparse_paths[@]}" || exit 1

# move to app dir if the host contains only a single stack
if [ -d "${HOME_DIR}/${HOST_NAME}" ]; then
	# should exist in single-stack hosts
	cd "${HOME_DIR}/${HOST_NAME}"
else
	# should exist in both single-stack and multi-stack hosts
	cd "${HOME_DIR}"
fi

: 'INIT PROFILE'
# clean up old profile.d symlinks
sudo find /etc/profile.d -maxdepth 1 -type l -name "00-*.sh" -delete 2>/dev/null || true

# remove community-scripts details loader
sudo rm -f /etc/profile.d/00_lxc-details.sh || true

# remove stale bash profile overrides
sudo rm -f /root/.bash_profile /home/dante/.bash_profile || true

# link login scripts into /etc/profile.d; executable helpers belong in _common/bin
for base in aliases.sh auto-cd.sh fastfetch.sh functions.sh; do
	script="${HOME_DIR}/_common/${base}"
	[ -e "$script" ] || continue
	sudo ln -sf "$script" "/etc/profile.d/00-${base}"
done

# link the shared fastfetch config to both root and dante users
FASTFETCH_CONFIG="${HOME_DIR}/_common/configs/fastfetch.jsonc"
if [ -f "${FASTFETCH_CONFIG}" ]; then
	for user_home in /home/dante /root; do
		sudo install -d -o "$(basename "${user_home}")" -g "$(basename "${user_home}")" "${user_home}/.config/fastfetch"
		sudo ln -sf "${FASTFETCH_CONFIG}" "${user_home}/.config/fastfetch/config.jsonc"
	done
else
	echo "ERROR: ${FASTFETCH_CONFIG} not found. Sparse-checkout may have failed."
	exit 1
fi

# link the shared direnv config to both root and dante users
DIRENV_CONFIG="${HOME_DIR}/_common/configs/direnv.toml"
if [ -f "${DIRENV_CONFIG}" ]; then
	for user_home in /home/dante /root; do
		sudo install -d -o "$(basename "${user_home}")" -g "$(basename "${user_home}")" "${user_home}/.config/direnv" || exit 1
		sudo ln -sf "${DIRENV_CONFIG}" "${user_home}/.config/direnv/direnv.toml" || exit 1
	done
else
	echo "ERROR: ${DIRENV_CONFIG} not found. Sparse-checkout may have failed."
	exit 1
fi

AUTOENV_CONFIG="${HOME_DIR}/_common/configs/autoenv.sh"
if [ -f "${AUTOENV_CONFIG}" ]; then
	for user_home in /home/dante /root; do
		sudo install -d -o "$(basename "${user_home}")" -g "$(basename "${user_home}")" "${user_home}/.config/autoenv" || exit 1
		sudo ln -sf "${AUTOENV_CONFIG}" "${user_home}/.config/autoenv/autoenv.sh" || exit 1
	done
else
	echo "ERROR: ${AUTOENV_CONFIG} not found. Sparse-checkout may have failed."
	exit 1
fi

: 'VM SHARED REPOSITORIES'
# LXCs skip this; VMs get /configs and /scripts plus a scheduled fast-forward
if systemd-detect-virt --vm --quiet; then
	sudo apt-get install -y starship || exit 1

	for repository in configs scripts; do
		if [ ! -d "/${repository}/.git" ]; then
			sudo install -d -o dante -g dante "/${repository}" || exit 1
			dante_git clone "git@github.com:danterazo/${repository}.git" "/${repository}" || exit 1
		fi
	done

	SYNC_JOB='*/15 * * * * [ -x /scripts/utils/pull-shared-repos.sh ] && /scripts/utils/pull-shared-repos.sh'
	{
		sudo crontab -u dante -l 2>/dev/null | grep -vF 'pull-shared-repos'
		printf '%s\n' "${SYNC_JOB}"
	} | sudo crontab -u dante - || exit 1
fi

# use canonical's suggested marker files
sudo touch /var/lib/update-notifier/hide-esm-in-motd
sudo touch /var/lib/ubuntu-advantage/hide-esm-in-motd
sudo pro config set apt_news=false

# delete every update-motd.d file, with some exceptions
shopt -s extglob
sudo rm -fv /etc/update-motd.d/!(85-fwupd.dpkg-dist|98-reboot-required)
shopt -u extglob

# disable SSH login message
sudo sed -i 's/^#\?PrintLastLog.*/PrintLastLog no/' /etc/ssh/sshd_config

: 'INIT PERMISSIONS'
# enable GPU access
sudo groupadd -f video
sudo groupadd -f render
sudo usermod -aG video,render,docker root || true
sudo usermod -aG video,render,docker dante || true

# grant dante passwordless reboot/poweroff/shutdown/apt
sudo tee /etc/sudoers.d/dante >/dev/null <<'EOF'
dante ALL=(root) NOPASSWD: /usr/sbin/reboot, /usr/sbin/poweroff, /usr/sbin/shutdown, /usr/bin/apt-get update, /usr/bin/apt-get upgrade, /usr/bin/apt-get dist-upgrade, /usr/bin/apt-get dist-upgrade -y, /usr/bin/apt-get clean, /usr/bin/apt-get autoremove, /usr/bin/apt-get autoremove -y --purge
EOF
sudo chmod 0440 /etc/sudoers.d/dante
sudo visudo -c # validate sudoer file syntax

: 'BASH CONFIG'
# share one bashrc entrypoint across accounts
if [ ! -f /docker/_common/bashrc.sh ]; then
	echo "ERROR: /docker/_common/bashrc.sh not found. Sparse-checkout may have failed."
	exit 1
fi

# create symlinks
sudo mkdir -p /home/dante
sudo ln -sf /docker/_common/bashrc.sh /root/.bashrc
sudo ln -sf /docker/_common/bashrc.sh /home/dante/.bashrc

: 'REMINDERS FOR USER'
echo -e "\nDouble-check IP in PVE UI before proceeding! \n\n"
