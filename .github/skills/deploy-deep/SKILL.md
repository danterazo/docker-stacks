---
name: deploy-deep
description: "Perform a deep deployment of published repo changes to Docker guests, including bootstrap, staged dcd -v/dpull rollout, container health, logs, API and pinned Caddy route validation. Use only when explicitly asked for deep deployment validation or /deploy-deep."
argument-hint: "Optional: all, stack names, or guest IDs, for example caddy or 100 200"
user-invocable: true
disable-model-invocation: true
---

# Deep Deploy

Invoke `/deploy-deep` when exhaustive deployment validation is requested.
Creating this skill, editing code, running local tests, or refreshing the
deployment map does not authorize a deployment.

For a metadata-only update of local `deployments.yaml`, use
`/refresh-deployments` instead.

## Refresh Before Targeting

First follow the mandatory pre-deployment refresh in
`.github/skills/refresh-deployments/SKILL.md`: complete live discovery, update
local `deployments.yaml`, and validate it before choosing targets, publishing
commits, or choosing guest SSH/access routes. A deep deployment request includes
this metadata refresh; it does not authorize committing the refresh or deploying
additional guests. Stop if refresh cannot complete; never use a stale map.

Use the refreshed map and the refresh's live inventory for target selection,
owner-batched preflight, and LXC versus VM access routing. Recheck volatile
ownership and state immediately before guest operations; if placement changes,
refresh again before continuing. Do not repeat full discovery unnecessarily.

## Choose Targets

- `/deploy-deep` in a new thread, with no earlier edits, deployments, or named
  guests in the conversation: deploy all pending changes. Fetch published
  `main`, then for each running Docker guest compare its `/docker` HEAD with
  `origin/main` and select it when files in its sparse paths changed. Changes
  to shared paths such as `.common/` or `bootstrap.sh` select every guest.
  Report guests already at `origin/main` as up to date and skip them.
- `/deploy-deep` in an existing thread: target only the guests whose stacks or
  guest IDs were edited, deployed, or explicitly named earlier in that
  thread. Show the derived list with the reason for each guest and proceed
  directly to read-only preflight; do not pause for target confirmation.
- `/deploy-deep all`: every running Docker guest in `docker_guests`, whether or not
  it has pending changes.
- `/deploy-deep <stacks or guest IDs>`: exactly what is named. A stack resolves to
  every guest that runs it; a guest ID selects only that guest.
- In every mode, report the targets, rollout order, and guest-wide scope as
  progress. Complete read-only discovery and preflight before any approval
  checkpoint, and deploy only published commits.
- "Each container" follows the same scoping: all targets for a new-thread
  `/deploy-deep`, only the relevant guests within an existing thread.

## Scope and Approval

- Read `.github/copilot-instructions.md`, `deployments.yaml`, and the relevant
  stack definitions. Confirm the local hostname/account and working directory.
  The local checkout is not a deployment target; never run `dpull` here.
- An explicit `/deploy-deep` request authorizes
  bounded read-only discovery and preflight through the existing configured
  SSH and Proxmox access needed for the selected scope. Do not ask whether to
  use that access or whether to perform those checks. Never create or change
  credentials, host-key trust, permissions, or access methods.
- Derive targets from the request, thread, deployment map, and live discovery.
  Do not pause for confirmation of a resolvable target list or rollout plan;
  report it while continuing preflight. If one target is unreachable, stop
  attempts against that target, record the gap, and continue independent
  read-only work for other candidates. Do not silently exclude it from the
  requested scope or try another method to bypass the access failure.
- Explain the affected guests and the operations before mutation. A request
  to deploy a named stack authorizes discovery for that task using existing
  access. Ask only when target or access scope remains ambiguous after the
  permitted discovery, or a required decision cannot be resolved from these
  instructions and current state. Obey tool approval prompts; never alter
  approval settings, credentials, host-key verification, permissions, or
  trust relationships.
- Per guest, first complete Bootstrap Changes below when applicable, then
  stop every top-level stack with `dcd -v`
  (`dcd` is the `docker compose down` alias in `.common/aliases.sh`), run
  `dpull` from `.common/functions.sh`, then validate startup. Stopping first
  forces a clean recreate, so validation proves the stacks start from the
  new definitions rather than surviving as old containers.
- Use `dpull`, not `dupull`. `dupull` only adds the `upgrade` alias (APT
  dist-upgrade, cache clean, `autoremove --purge`), which is unrelated to
  deploying repo changes. Run `upgrade`/`dupull` only when the user
  explicitly asks for OS upgrades, with separate approval for package
  upgrades and removal.
- Neither step is stack-scoped. Both cover every top-level stack in the
  guest checkout (`/docker/*/compose.y*ml`), including any `include:` children.
  qBittorrent and Soulseek are independent top-level stacks. `dpull` runs plain
  `git pull`, then per stack `docker compose pull --ignore-buildable`,
  `build --pull --no-cache`, and `up --build -d --remove-orphans`, returning
  on the first failure.
- Before the first mutation, explicitly obtain approval for guest-wide
  downtime, the volume removal below, image/build changes, and orphan removal,
  unless the user has already approved those exact impacts in this request or
  thread. A generic request to deploy a config edit is not permission for
  unrelated workloads beyond this disclosed scope. Gather all read-only
  findings first, then make one consolidated approval request covering the
  exact targets, rollout order, guest-wide impact, and any unresolved
  decision. Do not ask separately for SSH, each guest, or each deployment
  phase. Once approved, continue without repeated confirmation.
- Do not commit, push, transfer files, change sparse-checkout rules, install
  tooling, start stopped guests, reboot, or change networking as implicit
  deployment prerequisites. Required bootstrap has the standing authorization
  below; ask for every other needed scope expansion.
- Execute deployment mutations sequentially. Stop rollout on failure and
  report completed, failed, and skipped targets; do not silently roll back
  or retry mutations.
- Run independent read-only discovery, preflight, and service checks
  concurrently in bounded batches to reduce elapsed time. Keep each result
  associated with its guest and owner. Within a guest's validation window,
  run independent checks concurrently, but preserve the full settling window
  and before/after snapshots. Finish validation before mutating the next
  guest; concurrency never bypasses networking waves or failure gates.
- Keep preflight compact and reusable: inventory the cluster once, batch LXC
  reads by owner, fetch published `main` once, and compare each guest's HEAD
  and sparse paths against that SHA. Record one baseline per guest; repeat
  volatile checks immediately before that guest's mutation and take the
  required post-deploy snapshots. Do not repeat conclusive probes unless
  state changed or a required gate calls for a fresh result.
- Keep remote commands simple and shell-safe; avoid deeply nested quoting
  around templates. If output is partial/unknown or a quoting error occurs,
  do not infer success or rerun a mutator. Issue one narrowly scoped
  read-only check for the command's resulting guest state, then continue only
  from confirmed evidence. During a required settling interval, use time for
  independent read-only checks on that guest rather than leaving it idle.

## Subagent Coordination

- Use subagents for independent read-only discovery, guest preflight,
  functional probes, and bounded log review when this reduces elapsed time.
  Limit concurrency to a small batch, normally two to four workers, and
  respect guest/owner load and rate limits. Do not duplicate the same probe
  or create persistent/background agents.
- Give each worker explicit guest IDs, confirmed owners, approved access
  methods, the intended published revision, and the same no-secrets,
  no-installation, no-trust-bypass, and no-remote-staging rules. Delegate
  only within approved access scope; a subagent is not new permission.
- Assign one coordinator as the only deployment writer. Workers must not
  pull into working trees, bootstrap, stop/start stacks, deploy, or repair
  state. The coordinator performs approved mutations sequentially and
  stops on failure; it does not mutate the next guest while the current
  guest's validation is incomplete. Networking waves and settling windows
  remain mandatory.
- Require structured results identifying guest, owner, revision, timestamps,
  endpoint/vantage point, expected/observed response, and command exit status.
  Missing output, errors, and timeouts are gaps, not passes. Join the required
  results before advancing; verify critical results against actual evidence
  rather than relying on a worker's unqualified success summary.
- Local Git subagents may organize explicitly requested multiple commits
  under the repository instructions. Never run competing Git writers;
  respect a request to use no subagents, and do not fold uncommitted local
  edits into a deployment without an explicit publishing request.

## Publish Local Changes

- Select deployment content from published commits, not the local index or
  working tree. Ignore local unstaged and untracked changes for deployment;
  preserve them unchanged and do not let them block the published rollout.
- Alert the user to locally staged changes, but do not commit, unstage, or
  include them in deployment. Staged changes are not a deployment blocker.
  Do not request that uncommitted work be published as a prerequisite.
- Fetch published `main` and confirm the branch, upstream, fast-forward
  relationship, and intended published SHA. Review and validate that revision,
  not uncommitted local files. This includes bootstrap and volume audits.
- Disclose existing unpushed commits. Push committed work only when authorized,
  without force; do not create a branch or resolve divergence implicitly.
  A push request does not authorize committing staged or unstaged changes.
- When the user separately requests a commit, include only the approved edits
  and preserve unrelated staged work. If the same paths contain unrelated
  changes that cannot be safely separated, ask rather than including them.
  That documentation or publishing task need not block an otherwise safe
  deployment of the previously selected published revision.
- Publishing approval does not authorize guest downtime, bootstrap, OS
  upgrades, credential provisioning, or any other deployment prerequisite.

## Bootstrap Changes

For each selected guest, compare its recorded predeploy revision with the
intended published revision. If that incoming diff includes `bootstrap.sh`,
run the guest's `bootstrap` alias before `dcd -v`, `dpull`, or any other
deployment mutation. Read-only preflight and required approvals come first.
Ignore unpublished local bootstrap edits; they neither trigger bootstrap nor
block deploying the selected published revision. Inspect and run that
revision's script when required by the guest's incoming published diff.
Do not expand the selected guest scope.

1. Inspect the deployed alias and the incoming published script before
   execution. The current alias pulls Git as `dante`, then sources
   `/docker/bootstrap.sh` in the invoking shell. Its `git pull || true`
   masks pull failures: explicitly fast-forward as `dante` and verify the
   intended revision before invoking the alias; check HEAD again afterward.
   Preserve the old Compose definitions and active-project snapshot before
  this pull. If changed definitions cannot safely tear down the old projects,
  block mutation for that guest, record the required targeted teardown, and
  continue independent read-only preflight. Include the decision in the
  consolidated approval checkpoint; never silently omit the old projects.
2. The user has given standing approval to run required bootstrap on selected
  deployment guests without reconfirmation. Report which guests require it
  and inspect the incoming script first. This approval covers the script's
  Ubuntu release upgrade, package installation, possible Docker restart,
  ownership/permission/group/sudo changes, and SSH key/authentication/trust
  changes. These actions outside `bootstrap.sh` still need their own approval.
  Do not suppress bootstrap failures or silently skip phases. Never reboot
  implicitly, run bootstrap locally or on a Proxmox owner, or bypass failed
  SSH verification to reach a guest.
  Before bootstrap, enumerate Compose bind mounts whose host sources are
  inside `/docker` and inspect their existing numeric owner/group and modes.
  Bootstrap ownership repair may change the `/docker` root and `.git`
  metadata only. Never recursively chown the worktree, because ignored
  application data can contain database datadirs. If Git cannot update a
  tracked path as `dante`, stop and inspect that exact repository path; do not
  broaden the repair to app data. Never recursively chown application data
  merely to clear a health failure.
3. The current alias uses `runuser`, requiring a guest administrative shell;
  the standing bootstrap approval includes that shell through the existing
  approved access method, not new remote access or trust configuration.
  It cannot simply be invoked as unprivileged `dante`. Inspect
   and load the deployed alias explicitly in noninteractive Bash, enabling
   alias expansion before parsing its invocation (for example, invoke the
   reviewed alias using `eval 'bootstrap'` after sourcing its definition).
  Set `HOME=/root` in that administrative shell before sourcing or invoking
  the alias. `pct exec` may otherwise provide `/` as `HOME`, causing the
  script's `$HOME/.autoenv` setup to create `/.autoenv`.
   Do not substitute `bash bootstrap.sh`: the alias sources the script.
4. Check output from every bootstrap phase, not only its final status;
   neither the alias nor script guarantees all earlier failures propagate.
   Stop on failure before teardown. Open a fresh `dante` session afterward,
   recheck repository identity, revision, helper definitions, Docker access,
   and service availability, then proceed with `dcd -v` and `dpull`.

For AdGuard Home and Caddy, bootstrap belongs to that guest's rollout wave,
not a fleet-wide preliminary pass: validate the secondary completely before
bootstrapping another instance or a primary. Bootstrap itself may interrupt
Docker, so confirm the serving peer before bootstrap as well as before down.

## Volume Removal (`dcd -v`)

`docker compose down -v` removes the stack's non-external named volumes and
anonymous volumes (image `VOLUME` paths not covered by a mount). Bind mounts
and `external: true` volumes are untouched. Removing a local-driver NFS
volume only unmounts it and deletes Docker's definition; server data stays.
A static audit of the published stacks on 2026-10-16 found `-v` safe for all:

| Stack                             | Removed by `-v`                                                                                                       | Effect                                                                                            |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| adguardhome                       | nothing; state and configs are bind mounts                                                                            | none                                                                                              |
| caddy                             | anonymous `/config` and `/data` outside the `./data` bind at `/data/caddy`                                            | autosave regenerates from the Caddyfile; certificates and ACME accounts persist in `./data`       |
| gluetun (+ qbittorrent, soulseek) | `qbittorrent_nfs`, `soulseek_nfs` definitions; qBittorrent anonymous `/config` outside the `/config/qBittorrent` bind | NFS data persists; qBittorrent loses only `$HOME/.cache`                                          |
| immich                            | NFS volume definitions                                                                                                | NFS data persists; Postgres and Valkey `/data` are bind mounts; Valkey uses append-only persistence |
| plex-music, plex-video            | NFS volume definitions                                                                                                | NFS data persists; Plex and Tautulli config are bind mounts                                       |
| pocket-id, spoolman               | nothing; data is a bind mount                                                                                         | none                                                                                              |
| common-dockge-agent (undeployed)  | nothing; its volume is external                                                                                       | none                                                                                              |

For a deployment that introduces or changes the Immich Valkey or AudioMuse
plugin bind mounts, first inspect the existing mounts through approved
read-only guest access. Preserve existing data before any `down -v`; an empty
new bind does not recover old anonymous-volume data. Migration needs explicit
approval. The current Immich Valkey image replaces Redis while retaining the
same AOF bind mount, so preserve `immich/redis-data` and verify AOF recovery;
no export/import step is indicated by the release Compose template. Immich's
Postgres image remains version `14-vectorchord0.4.3-pgvectors0.2.0` and is now
pinned to digest `sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23`;
the digest pin alone does not change the database schema.
For Dawarich, also verify the existing Photon index layout and compatibility;
automatic index downloads and updates are disabled. See the README storage audit.

Re-audit statically before deploying
when the published diff adds a stack or changes `volumes:`, mount targets,
or images. A new non-external named volume, or an unmounted image `VOLUME`,
holding data that cannot be regenerated is a blocker: stop and report.

## Networking Rollout Order (AdGuard Home and Caddy)

AdGuard Home (200, 201, 202 at last refresh) and Caddy (203, 204, 205) run
duplicate instances behind keepalived. Never let a deployment take every
instance of a type down at once. This applies in every target mode,
including threads scoped only to AdGuard Home or Caddy.

1. Classify each instance as primary or secondary (secondary, tertiary,
   and so on) by its PVE role tags in `deployments.yaml`, rechecked live.
   If duplicate instances lack distinguishing role tags, do not guess from
   IDs or nodes. Record the unresolved role, continue independent read-only
   preflight, and request the role decision at the consolidated checkpoint.
2. Count running instances per type. Skip stopped ones; never start them.
   If fewer than two are running for an affected type, do not deploy that
   type. Record the blocker and continue preflight for unrelated targets;
   request a decision at the consolidated checkpoint before including it.
3. Wave 1 (canary): one running secondary per affected type, that is one
   AdGuard Home and one Caddy. If the primary is down, any running instance
   may be the canary as long as another remains running. Before stopping a
   canary, confirm another instance of that type is running and serving.
4. Validate each canary fully (see Verify). On failure, stop the rollout of
   all remaining networking guests and report; leave the others untouched.
5. Wave 2: remaining secondaries, one at a time, each validated.
6. Wave 3: primaries last, one at a time, each validated.

Non-networking guests may share the batch in any position, but primaries
start only after every targeted secondary has passed validation.

Before stopping a networking guest, confirm its own resolver
(`/etc/resolv.conf`) does not depend on its local AdGuard Home: `dpull`
needs DNS for Git and image pulls after the stacks are down. Disclose that
Caddy's outage includes a `--no-cache` rebuild that downloads Caddy from
caddyserver.com while the guest's Caddy is stopped.

## Resolve Targets and Preflight

1. Resolve changed stack paths through `docker_guests`, using hostname matches
   and the documented exceptions. Caddy and AdGuard Home each resolve to all
   three of their LXCs; order them per Networking Rollout Order. Recheck
   live ownership, state, and tags through approved cluster discovery
   before using recorded observations.
   Confirm each owner, guest ID/type, and in-guest hostname; `pct` is for LXCs,
   never VMs. Do not start stopped guests; report skipped deployments.
  Read `/ai/pending-changes.md` for unresolved target-specific service or
  network blockers. Do not bootstrap, stop, or update a blocked guest until
  its failing baseline has been rechecked and passes; a container-local
  healthcheck or successful deployment helper does not clear the blocker.
2. NVIDIA VM 101 hosts the `immich` and `plex-video` repo directories. Tautulli
   is a service inside the Plex Compose definitions on VM 101 and LXCs 108
   and 120, not a separate required sparse-checkout stack. Inspect actual
   Compose references before inferring additional repo paths.
3. Inspect local changes and relevant tests. Identify the intended published
  commit and branch. Alert the user to staged local changes; preserve and
  exclude all uncommitted local work without blocking deployment. Follow
  Publish Local Changes for authorized pushes of existing commits. `dpull`
  retrieves published commits, not local staged or working-tree edits.
4. Confirm the guest checkout location, repository identity, branch/upstream,
  current revision, tracked worktree, untracked files, sparse paths, and the
   upstream revision that Git pull would retrieve. Inspect relevant ownership
   first, applying only the standing scoped repair approval in
   `.github/copilot-instructions.md` when needed, and run Git as `dante`.
   Do not probe Git as root or add `safe.directory` exceptions. `/docker` is
  expected, but verify it before use. Report untracked files and preserve them
  during upgrades; they do not block deployment unless they collide with
  incoming paths or prevent safe operation. Leave cleanup for manual review
  or a follow-up request. Preserve tracked remote changes; do not reset, stash,
  clean, force-pull, or bypass Git ownership checks. Do not print credentials
   or environment files. Stop on divergence or unrelated upstream changes
   unless their inclusion is explicitly approved. `dpull` uses plain
   `git pull`, so confirm after `git fetch` that it would fast-forward.
   Record the predeploy SHA.
5. Review the deployed `dcd` alias and `dpull` definition before running
   them; they may differ from this checkout. If they no longer match the
   behavior described here, stop and report. Confirm the expected top-level
  workloads and disclose that all of them will be stopped and recreated.
  Run `docker compose ls` from `/docker` as `dante`; the wrong working
  directory can make Compose search `/root/.env` and emit irrelevant
  permission warnings.
6. Confirm `dante` can reach the Docker daemon, then snapshot each running
   container's name, state, health, and restart count, plus the active
   Compose projects. Stacks remain down if a later step fails, so this
   snapshot is the reference for both validation and failure reports.
    Treat this as a hard pre-mutation health gate: before bootstrap, teardown,
    or image changes, every in-scope container must be running and every
    configured healthcheck must be healthy. If a container is unhealthy,
    restarting, or exited, stop that guest's rollout immediately and report
    the pre-existing failure. If a container is nominally running but its
    restart history or functional probe suggests instability, compare two
    read-only container snapshots at least 60 seconds apart; any restart-count
    increase blocks that guest's rollout. Do not use a weaker probe such as
    `pg_isready` to override an unhealthy database healthcheck. Resolve and
    validate pre-existing failures separately before deployment; do not
    restart, repair permissions, or otherwise mutate them implicitly. For
    containers without healthchecks, require their documented functional
    baseline probe before proceeding.
   On both LXCs and Docker VMs (including `nvidia-vm`/101), run Git,
   `docker`, Compose, and deployment helpers as `dante` without `sudo`.
   Historical sudo requirements are not current requirements: verify using
   a read-only `docker info` in that user's fresh session. If access fails,
   stop and report; do not retry as root, add sudo, or change groups/socket
   permissions. Bootstrap administration is the separate exception above.
7. Determine service validation commands from the actual Compose runtime and
  mounted configuration. Inventory each app's actual IP, exposed port,
  protocol, and webpage/API/health path across every stack that will be
  recreated, including nested stacks. Resolve published host ports versus
  container ports, host/shared networking, and configured bind addresses;
  never use a wildcard bind address as a destination or assume default
  ports. Use current guest addresses, not stale map entries. Do not print
  secrets or entire resolved Compose configurations. Record which endpoints
  are intentionally internal-only and choose an appropriate in-guest probe
  for those rather than exposing them. For Caddy, plan config validation in
  its actual image/context and the reverse-proxy checks below. A check
  against old deployed files is not validation of unpublished local changes.

## Execute Through the Correct Owner

Use noninteractive SSH with existing aliases, bounded connection timeouts,
and strict host-key checking. Reconfirm the owner identity on each connection.
Run commands directly in the integrated terminal; do not create VS Code task
definitions just to execute deployment or preflight commands. If terminal
execution is unavailable, stop and report the blocker rather than switching
execution methods or bypassing approval prompts.
QEMU VMs, including `nvidia-vm`/VM 101, are accessed directly over SSH using
their trusted guest aliases. LXCs are not directly SSH-accessible: SSH to the
confirmed owning PVE node, then use `pct exec`. Thus, "SSH into caddy" means
connect to caddy's owner and execute inside its LXC.
For VM aliases, check the effective username with `ssh -G <alias>` and
confirm `id -un` after connecting; do not run Git, Docker, or Compose unless
the session is `dante`. OpenSSH uses the first configured value, so put
host-specific `User dante` entries before broad `Host *` defaults. If the
effective user is wrong, correct the intended config ordering before using
the alias; do not retry as root or bypass host-key/authentication checks.
For recovery snippets intended to be pasted into an already-interactive SSH
shell, do not use `set -e`; guard each phase with `if`/`return` so a failed
check leaves the user's remote shell open. The deployment body below runs in
a deliberately noninteractive shell, where fail-fast behavior is intentional.
For an LXC, run `pct exec <id> --keep-env 0 -- ...` on that owner. Do not use
interactive `pct enter`, and do not substitute a local or host command if
guest access fails. For a VM, use approved configured SSH access or an available
QEMU guest agent, not `pct`.

Run the repository shell inside the guest as `dante`, using
`pct exec <id> --keep-env 0 -- runuser -u dante -- /bin/bash --noprofile --norc`
for LXCs. For VMs, prefer an existing trusted `dante` SSH alias. Do not switch
execution methods to bypass failed SSH host-key verification. Root is for
approved administrative actions, not Git; do not run the Docker helper body
as root. This applies to every Docker VM, not only VM 101. An approved root
guest session may select `dante` via `runuser`; it must not execute Docker
or Git as root. Never infer a need for sudo from the guest being a VM.

`dpull` is a Bash function and `dcd` is an alias. Do not assume a
noninteractive shell reads the interactive `.bashrc`, which returns early
without a prompt, or expands aliases. After reviewing the deployed files
and completing any required Bootstrap Changes phase, the guest-side command
body below applies when the checked-out definitions can tear down the old
projects safely:

```bash
set -e
test "$(id -un)" = dante
cd /docker
source /docker/.common/functions.sh
declare -F dpull >/dev/null
# dcd -v in every stack dpull will bring up, using the pre-pull definitions
for app_dir in /docker/*/; do
	[ -f "${app_dir}compose.yaml" ] || [ -f "${app_dir}compose.yml" ] || continue
	echo "== down: ${app_dir}"
	(cd "$app_dir" && docker compose down -v)
done
dpull
```

Execute this body in noninteractive Bash inside the selected guest, with no
interactive startup files. The loop mirrors `dpull`'s stack discovery and
runs before its `git pull` in the normal path, so containers stop using the
definitions that created them. The bootstrap path has already pulled;
use the teardown plan established before that pull instead if necessary.
It spells out the `dcd` alias definition because aliases are
not expanded noninteractively; confirm the deployed alias matches. Use safe
argument passing/quoting across SSH, the owner shell, and `pct exec`; do not
interpolate untrusted discovery output into shell commands. Never source the
helpers or run this command body in the local checkout or on the PVE host.

Keep output bounded, but do not pipe interactive prompts through filters. If
elevated access is required but not already approved, stop. Secrets must be
entered directly by the user, never requested through chat or tools.

Do not write logs, staging files, or scratch folders on Proxmox nodes or in
guests; read remote output through the command result, bounded with `tail`
or `grep`. Any log that must be kept locally goes under
`/tmp/lxc-deploy-logs/` in this WSL2 instance; it is tmpfs and cleared on
boot, so it needs no cleanup. Do not use other local log locations. Local
logs are only a convenience: judge success from server-side evidence such
as guest Git HEAD, Compose state, container logs, and service checks.

## Functional Service Checks

Validate what each service does, not merely its running state. Discover the
actual endpoint, port, network namespace, version, and expected response
before deployment. Prefer existing Compose/image healthchecks and documented
read-only APIs. Use bounded timeouts, parse JSON/XML responses with a parser,
and report only the assertion result, not secret-bearing response bodies.
Capture a baseline before mutation and repeat after the settling window.

Choose one HTTP validation route per app before the first mutation:

- Normally use its configured proxied hostname, not both hostname and direct
  IP/port. If there is no active proxy route, use the published backend.
- If ANY Caddy instance is selected for an upgrade or requires deployment,
  validate ALL other apps through the backend IP, port, and protocol that
  Caddy actually proxies, for the entire rollout, including baselines and
  browser checks. Keep this choice even while other Caddy peers are online or
  after a Caddy instance recovers. Do not change Caddy's configuration.
- A direct-backend check must not follow a redirect through Caddy or Pocket
  ID and count that as backend success. For OAuth apps, use a documented
  unauthenticated backend endpoint; mark the UI/auth handoff as deferred to
  proxy recovery rather than changing callback registration or logging in.
  Preserve TLS verification; report an unsupported direct TLS/UI check as a
  gap, never bypass trust or force the check through Caddy.
- Caddy's OWN recovery validation is the exception: after each Caddy instance
  returns, use its normal representative proxied URLs, pinned to that instance
  with the correct hostname/SNI, and the normal-DNS browser check. These
  checks establish proxy recovery, not the other apps' independent baseline.
- DNS and other non-HTTP protocols still use their actual service endpoints.
  Add a second route only for a changed network path or a concrete failure,
  not as routine duplicate coverage. A proxy-only pass does not establish
  direct-IP reachability or clear an existing direct-endpoint blocker.

| Service | Functional check |
| --- | --- |
| AdGuard Home | Query a benign public name such as `example.com` against each guest's actual IP, not only the VIP. Use `dig +time=3 +tries=1 @<guest-ip> example.com A` or a standard DNS resolver API with an explicit server and timeout. Require a successful response with valid expected records, not merely an open port. Test UDP and TCP where both are configured. Confirm a serving peer before disrupting any instance. |
| qBittorrent | Run the deployed container healthcheck. The current check calls `/api/v2/transfer/info` from inside the container and requires `connection_status == "connected"`; recheck that contract against the deployed version. Do not require an external-client API request; the API may reject requests from outside its trusted context. Account for the shared Gluetun network namespace. Check its published WebUI as a separate optional reachability check. Do not start downloads, change settings, or log in implicitly. |
| Gluetun and Soulseek | Run the image's existing read-only healthcheck where present, and test each exposed app's actual health endpoint or expected UI. Gluetun's VPN health does not prove qBittorrent or Soulseek is accessible. Discover rather than invent a Soulseek health endpoint. |
| Spoolman | Request `/api/v1/health` via the selected route, parse the healthy result, and check the UI via that same route. Use `spools.samskeyti.net` normally, or Caddy's backend IP/port during a Caddy rollout. |
| Pocket ID | Run `/app/pocket-id healthcheck` inside its container and verify the sign-in page via the selected route: `id.samskeyti.net` normally, or its backend IP/port during a Caddy rollout. Do not perform a sign-in. |
| Immich, Plex, and Tautulli | Use one documented unauthenticated ping/identity endpoint where needed and verify the UI via the selected route, not duplicate proxy/direct routes. During a Caddy rollout, use backend IP/port and defer proxy-dependent OAuth UI handoffs. Plex's localhost healthcheck does not establish external reachability. Report authentication limits without retrieving credentials or logging in. |
| Internal dependencies | Use existing read-only native probes from the dependency's own guest/container context. For Immich PostgreSQL, check the Compose healthcheck and inspect bind-mount ownership against the database process UID/GID; `pg_isready` alone is insufficient. For Immich Valkey with AOF enabled, require `PING`, `aof_last_write_status:ok` (strip `\r` first; `INFO` uses CRLF), and write access as the actual Valkey process UID to its data bind mount. The Compose healthcheck stays Immich's Redis-compatible `PING` check. Keep internal ports internal. These checks do not replace the owning app's external probe. |

For PostgreSQL, a successful `pg_isready` only proves that the server socket
accepts connections; it does not supersede a failing Compose healthcheck or
prove queries can read the database files. When the healthcheck reports a
permission error, compare the bind-mounted datadir's host ownership/modes with
the database process UID/GID and inspect the specific denied path read-only.
Do not assume the correct UID, run `chown`/`chmod`, delete files, or recreate
the database until the owner mismatch is confirmed and a recovery plan is
approved. For Immich on VM 101, the Compose bind source is
`/docker/immich/data/immich`; also check whether bootstrap changed its
ownership. Immich's current database process uses UID/GID `999:999`; its bind
source must be writable by that identity. The AOF source is
`/docker/immich/redis-data`; verify the Valkey process UID/GID from the running
image and confirm that identity can write there. Do not assume the previous
Redis image's UID/GID remains correct after the image change. Verify both
identities and paths from the running images rather than assuming them after
an image update. Compose `user:` sets the process identity inside
the container; it does not translate host UID/GID values. For bind mounts,
either set host ownership to the verified container identity or separately
design and validate an idmapped mount. Do not enable daemon-wide
`userns-remap` to solve one service's ownership mismatch.

Record endpoint, guest, client vantage point, expected and observed response,
and probe time. An unexpected response, failed query, unreachable healthcheck,
or unavailable/unauthorized probe is a failure or explicit validation gap,
not a pass. Do not install tooling, weaken authentication/TLS, or change
networking to make a probe succeed without the applicable approval.

## Verify and Report

1. Check the exit status and bounded output from each phase. The body
   exits on the first failed down, Git pull, image pull, build, or up. A
   failure leaves that stack and every later stack down: report exactly
   which stacks are down against the snapshot and stop the rollout. Do not
   retry, roll back, or fix helper semantics without approval.
2. Verify guest HEAD matches the intended published revision; account for a
   branch advancing during rollout.
3. Validate startup for every stack in the guest, not only changed ones:
   - Every container in the predeploy snapshot is running again, and
     healthchecked services report `healthy`, and each was created after
     the deploy started. Account for profiles such as `adguardhome-sync`:
     a profiled container not recreated was skipped by down/up. Flag any
     container missing, stale, or newly present.
   - Observe a settling window of at least 60 seconds, longer than the
     largest healthcheck `start_period` involved (Gluetun's is 2 minutes).
     Compare state and restart counts at its start and end; any increase,
     `restarting`, `exited`, or `unhealthy` is a failure.
   - Review logs since the deploy start, bounded per stack, for example
     `docker compose logs --since <start> --no-color --tail 200`, scanning
     for errors, panics, permission denials, mount failures, and crash
     loops. Distinguish benign startup noise; do not dump environment
     values or resolved secret-bearing configs.
   - Run service checks after the settling window, since probes can race
     startup. For each app, probe its selected proxy or backend route from
     an approved client vantage point, not only localhost inside its
     container. Do not hit every declared port: add another port only when it
     serves an independent app or protocol. For HTTP(S), use one
     application-specific API/identity/health response to verify the backend;
     a listening socket or redirect alone is not sufficient. Follow expected
     redirects with bounded hops and verify the final destination. Treat an
     authentication response as expected only when confirmed for that app;
     never read credentials or log in implicitly. For user-facing web apps,
    use one browser visit to that selected route as the primary UI check;
     do not duplicate it with curl requests made only to scrape a title. Use
     protocol-appropriate checks for non-HTTP services, including AdGuard DNS
     over both configured UDP/TCP and keepalived state. Internal-only
     dependencies use the planned in-guest checks.
   - If a local healthcheck passes but the guest-IP request fails or closes
     without an HTTP response, compare the same safe endpoint from container
     loopback, the container bridge IP, the guest's published IP, and an
     independent client. Inspect read-only network mode, actual port bindings,
     bridge address, and listener address. A bridge-IP failure localizes the
     issue inside the container/network namespace; a working bridge endpoint
     with a failing published IP points toward host forwarding. For Plex,
     compare only network-related preference values with the working server;
     redact tokens and never dump `Preferences.xml`. Do not change ports,
     firewall rules, preferences, or network mode during diagnosis. A passing
     localhost healthcheck never overrides a failing published endpoint.
   - Run the applicable Functional Service Checks above; an inherited Docker
     healthcheck alone does not establish external app accessibility.
   - For each deployed Caddy instance, run `caddy validate` and pin checks
     with `curl --resolve <hostname>:443:<guest-ip>`, preserving SNI and
     normal TLS verification. Always check specifically changed routes. For
     global Caddy changes without a specific route, check one external-backend
     route (`pve.samskeyti.net`) and one Docker-backed route (`spools` or
     `id`) per instance; do not sweep all representative routes by default.
     Verify application-specific responses, not only DNS/TLS/status; proxy
     502/503/504 responses fail. A shared VIP cannot prove an individual
     instance serves a route. These checks supplement, not multiply, the
    selected app endpoint check above. Run these proxied checks only as
    Caddy's recovery validation, not as a dependency of other app checks
    during a Caddy rollout.
   - For each changed/recreated web app, use the built-in browser on its
    selected route to verify the expected rendered UI or login page and
     capture one non-sensitive screenshot. Visual validation is the primary
     UI assertion; use one request to a separate API/identity endpoint only
     when needed to prove the backend independently. Exercise safe read-only
     navigation only; do not log in, submit forms, or change settings. Keep
     credentials and sensitive page content out of reports and screenshots.
     For apps using Pocket ID OAuth2, including Immich, a handoff to
     `https://id.samskeyti.net` is expected. Capture the app's initial
     sign-in/handoff page promptly; a later identity-provider interaction
    page is not evidence that the app page failed. In normal proxy mode,
    use the configured hostname and do not add a duplicate direct-IP probe.
    In Caddy-rollout backend mode, verify an unauthenticated backend endpoint
    instead and defer the proxy-dependent UI handoff; a direct-IP callback
    may be unregistered. Do not continue authentication.
   - Prefer reusing an already shared browser page or supported background
     navigation that leaves the user's active tab unchanged. If the built-in
     browser tools expose no hidden/background-tab control, tell the user;
     do not claim that agent-started tabs are hidden or change browser settings
     to hide them. Browser visibility limitations do not authorize replacing
     visual checks with HTTP-only checks.
   - Preserve normal TLS verification and expected hostname/SNI in browser
     checks. A normal-DNS browser visit does not prove each Caddy instance;
     retain the per-instance pinned checks. Do not browse an HTTPS IP if it
     causes a certificate mismatch or alter trust, DNS, or browser security
     to make a check pass. Record the browser endpoint, vantage point, visual
     result, and remaining per-instance or backend gaps. Browser checks do not
     replace container/config validation, DNS probes, or internal dependencies.
    If the browser cannot reach or validate the expected page, report the
    gap and stop the rollout rather than declaring the service healthy,
    except for explicitly deferred proxy-dependent OAuth UI checks in backend
    mode; report those separately from the verified backend result.
   - Use bounded connection/request timeouts and certificate verification;
     never bypass TLS or access controls to make a probe pass. Record the
     endpoint, probe vantage point, expected/observed result, and any blocked
     or untestable checks without credentials or sensitive response bodies.
     Missing tools, network reachability, or authorization are validation
     gaps, not passes; stop and report rather than installing tools, changing
     networking, or expanding remote access without approval. A running
     container is not proof of application accessibility.
4. AdGuard Home and Caddy follow Networking Rollout Order; a guest's
   validation must pass before the next wave begins. Do not claim full
   success if a target was stopped, unreachable, failed, or skipped.
5. Report guest ID, owner, role tag, before/after revision, helper result,
  validation result, selected route and Caddy recovery probe results, and any
  browser visual-validation results when used, failures, validation gaps,
  or skipped targets. Record important
   observations in the repo only as authorized; keep secrets and runtime
   status out of `deployments.yaml`. Do not promise automatic rollback of
   mutable image tags, and never reboot as part of this skill.

## Learn From The Run

Before the final report, briefly review the session's failures, tricky steps,
user corrections, repeated work, and avoidable delays. Do this automatically
on success or when stopping for a blocker, using evidence already collected;
do not add probes, log reads, or a session-history investigation for this step.

- If there is a concrete reusable lesson, make a small targeted update to the
  relevant deployment skill. Update `.github/copilot-instructions.md` only
  when the lesson applies across workflows. Preserve concurrent edits and
  existing approvals and safety gates. This step authorizes these narrow
  documentation edits, not operational changes or scope expansion.
- Record unresolved incidents in the canonical pending ledger with verified
  evidence, target/path, blocker, and next safe action. Keep temporary runtime
  observations and unproven hypotheses out of enduring instructions; never
  record credentials or turn a workaround into a permission exception.
- Validate changed documentation with `git diff --check` and mention the
  lesson/update briefly in the final report. Do not commit or push retrospective
  edits without an explicit request; an earlier deployment push does not cover
  newly written documentation. If there is no new lesson, make no edits.
