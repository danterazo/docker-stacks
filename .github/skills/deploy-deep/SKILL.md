---
name: deploy-deep
description: "Perform a deep deployment of published repo changes to Docker guests, including bootstrap, staged dcd -v/dpull rollout, container health, logs, API and pinned Caddy route validation. Use only when explicitly asked for deep deployment validation or /deploy-deep."
argument-hint: "Optional: all, stack names, or guest IDs, for example caddy or 100 200"
user-invocable: true
disable-model-invocation: true
---

# Deep Deploy

Exhaustive deployment: bootstrap when required, staged `dcd -v` and `dpull`
rollout, then health, log, API, browser and pinned Caddy validation. Run only
on explicit request; editing code, running tests or refreshing the map never
authorizes a deployment. The `/deploy` skill's rules for access, publishing,
new-stack sparse checkout, NFS recreate failures, volume `driver_opts` and
uncertain results also apply unless overridden here.

## Refresh and Targets

- First run the mandatory refresh in
  `.github/skills/refresh-deployments/SKILL.md`; stop if it cannot complete.
  Use its inventory for targets, owner-batched preflight and LXC/VM routing,
  and recheck volatile owner and state before each guest.
- New thread with no prior edits, deployments or named guests: fetch `main`
  and select running Docker guests whose `/docker` HEAD differs from
  `origin/main` in their sparse paths. Changes to `_common/` or
  `bootstrap.sh` select every guest. Report up-to-date guests as skipped.
- Existing thread: only guests whose stacks or IDs were edited, deployed or
  named in the thread. Show the list with reasons and continue to preflight.
- `all`: every running Docker guest. `<stacks or IDs>`: exactly those; a
  stack resolves to all of its guests.
- Report targets, rollout order and guest-wide scope as progress; do not
  pause to confirm a resolvable target list.

## Authorization

- The request authorizes bounded read-only discovery and preflight through
  existing SSH and Proxmox access; do not ask. Never change credentials,
  host keys, permissions or access methods; obey tool prompts. An unreachable
  target is a recorded gap, never silently dropped or bypassed.
- Gather all read-only findings first. Before the first mutation, make one
  consolidated approval request covering
  exact targets, rollout order, guest-wide downtime, `-v` volume removal,
  image/build changes, orphan removal and open decisions, unless those exact
  impacts were already approved in this thread. Then continue without
  further confirmation. A generic request to deploy a config edit does not
  cover workloads beyond the disclosed scope.
- Use `dpull`, not `dupull`. Run `upgrade` only on an explicit OS-upgrade
  request, with separate approval for package upgrades and removals.
- Never implicit: commits, pushes beyond authorized existing commits, file
  transfers, installs, starting stopped guests, reboots or networking
  changes. Standing approval covers required bootstrap (below) and the
  new-stack sparse-checkout addition.
- Mutate sequentially and stop on failure. Report completed, failed and
  skipped targets; never silently retry or roll back.

## Publishing

Deploy published commits only. Ignore and preserve unstaged and untracked
local work; alert the user to staged changes without committing, unstaging or
blocking on them. Fetch `main`, confirm branch, upstream, fast-forward and
the intended SHA, and review that revision (including bootstrap and volume
audits) rather than local files. Disclose unpushed commits and push only
when authorized, never with force. Publishing approval does not cover
downtime, bootstrap, upgrades or credentials.

## Subagents

Unless the user asks for no subagents, use two to four bounded read-only
workers for discovery, preflight,
functional probes and log review. Give each explicit guest IDs, owners,
access methods, the target SHA and the same no-secrets, no-install and
no-trust-bypass rules; a subagent is not new permission. The coordinator is
the only writer: it mutates sequentially and does not touch the next guest
until the current validation is complete. Require structured results
(guest, owner, revision, time, endpoint and vantage point, expected and
observed result, exit status). Missing output and timeouts are gaps; verify
critical results against actual evidence.

## Preflight

Inventory the cluster once, batch LXC reads by owner and fetch `main` once.
Record one baseline per guest and repeat only volatile checks right before
its mutation. Keep remote commands simple and shell-safe; after partial
output or a quoting error, make one narrow read-only state check instead of
rerunning a mutator.

1. Confirm owner, guest ID and type, and in-guest hostname. Check TickTick
   for unresolved blockers; leave a blocked guest untouched until its failing
   baseline passes again. A container healthcheck or helper success does not
   clear a blocker.
2. Repository, as `dante` after checking ownership (scoped repair per the
   repo instructions; never Git as root or `safe.directory`): verify `/docker`,
   identity, branch and upstream, HEAD (record the predeploy SHA), tracked
   changes, untracked files, sparse paths, and that `git pull` would
   fast-forward after fetch. Preserve tracked guest changes: no reset, clean
   or force-pull; stop on divergence or unexpected upstream changes.
   Untracked files block only on collision. A temporary stash is allowed only
   for exact paths an approved update needs: record existing stashes and the
   new stash ID, verify it, restore and compare afterward, and drop only that
   stash. On conflict keep the stash and stop.
3. Review the deployed `dcd` alias and `dpull` definition against this skill;
   stop if behavior differs. Run `docker compose ls` from `/docker` as
   `dante` (another cwd can trigger `/root/.env` warnings) and disclose every
   top-level workload that will be stopped and recreated.
4. Docker access: read-only `docker info` as `dante` in a fresh session on
   LXCs and VMs alike, without `sudo`. On failure stop; never retry as root
   or change groups or socket permissions.
5. Hard health gate: snapshot every container's name, state, health and
   restart count plus the active Compose projects. Every in-scope container
   must be running, and every healthcheck healthy; unhealthy, restarting or
   exited blocks that guest. If restart history looks unstable, take a second
   snapshot at least 60 seconds later and block on any increase. `pg_isready`
   never overrides a failing database healthcheck. Containers without
   healthchecks need their functional baseline. Do not repair pre-existing
   failures implicitly.
6. Plan checks from the actual runtime: each app's IP, published versus
   container port, protocol, network mode, bind address and health/API/UI
   path across every stack to be recreated, including nested stacks. Never
   use wildcard bind addresses as destinations, assume default ports, or use
   stale map addresses. Mark internal-only endpoints for in-guest probes and
   plan Caddy config validation in its actual image. Do not print secrets or
   full resolved configs.
7. Before stopping a networking guest, confirm its `/etc/resolv.conf` does
   not depend on its own AdGuard Home; `dpull` needs DNS after the stacks are
   down.

## Volume Removal (`dcd -v`)

`docker compose down -v` removes non-external named and anonymous volumes.
Bind mounts and `external: true` volumes stay; removing an NFS or virtiofs
volume only drops Docker's definition. Static audit from 2026-10-16:

| Stack                                     | Removed by `-v`                                                            | Effect                                                                   |
| ----------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| adguardhome                               | nothing; state and configs are bind mounts                                 | none                                                                     |
| caddy                                     | anonymous `/config` and `/data` outside the `./data` bind at `/data/caddy` | autosave regenerates; certificates and ACME accounts persist in `./data` |
| qbittorrent, soulseek (each with Gluetun) | qBittorrent anonymous `/config` outside the `/config/qBittorrent` bind     | only `$HOME/.cache` is lost; downloads are LXC bind mounts               |
| immich                                    | virtiofs volume definitions                                                | data persists; Postgres and Valkey `/data` are bind mounts (Valkey AOF)  |
| plex-music, plex-video                    | plex-video virtiofs definitions; plex-music nothing                        | data persists; Plex and Tautulli config are bind mounts                  |
| pocket-id, spoolman                       | nothing; data is a bind mount                                              | none                                                                     |
| common-dockge-agent (undeployed)          | nothing; its volume is external                                            | none                                                                     |

- Re-audit statically when the published diff adds a stack or changes
  `volumes:`, mount targets or images; stacks missing from this table need
  the same audit. A new non-external named volume, or an unmounted image
  `VOLUME`, holding non-regenerable data is a blocker: stop and report.
- When a deployment introduces or changes the Immich Valkey or AudioMuse
  plugin bind mounts, inspect existing mounts read-only first and preserve
  data before any `down -v`; an empty new bind does not recover old
  anonymous-volume data, and migration needs approval. Valkey reuses the
  `immich/redis-data` AOF bind; verify AOF recovery. Immich Postgres stays
  `14-vectorchord0.4.3-pgvectors0.2.0`, pinned to
  `sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23`
  (no schema change).
- Dawarich (undeployed): verify the existing Photon index layout; automatic
  index downloads and updates are disabled.

## Bootstrap Changes

If a guest's incoming published diff (predeploy SHA to target SHA) touches
`bootstrap.sh`, run its `bootstrap` helper before `dcd -v` or `dpull`, after
preflight and approvals. Unpublished local bootstrap edits neither trigger
nor block it.

- Standing approval, reporting which guests need it: the script's Ubuntu
  release upgrade, package installs, possible Docker restart,
  ownership/permission/group/sudo changes, SSH key/authentication/trust
  changes, and the guest administrative shell through existing access. The
  same actions outside `bootstrap.sh` need their own approval. Never reboot,
  run it locally or on a Proxmox node, suppress failures, skip phases, or
  bypass SSH verification.
- Before running: review the deployed helper and incoming script. Save the
  old Compose definitions and active projects; if the new definitions cannot
  safely tear down the old projects, block that guest, plan a targeted
  teardown and include it in the approval request. Audit Compose bind mounts
  under `/docker` (owner, group, modes): bootstrap may change only the
  `/docker` root and `.git`. Never recursively chown the worktree or app data
  such as database datadirs; if Git cannot update a tracked path, inspect that
  path only.
- Run: fast-forward as `dante` and verify the SHA. In a fresh noninteractive
  administrative Bash with `HOME=/root` (`pct exec` may set `/`, creating
  `/.autoenv`), source `/docker/_common/aliases.sh` and call `bootstrap`. It
  pulls with `--ff-only` and runs `bash -O extglob /docker/bootstrap.sh` in a
  child shell; never source the script. Check HEAD afterward.
- Check every phase's output, not only the final status, and stop on failure
  before teardown. Then, in a fresh `dante` session, recheck identity,
  revision, helper definitions, Docker access and services.
- For Caddy and AdGuard Home, bootstrap belongs to that guest's rollout wave;
  confirm a serving peer before bootstrap too.

## Networking Rollout (AdGuard Home and Caddy)

Never take every instance of a type down at once, in any target mode.

1. Classify primary and secondary instances from live PVE tags; never guess
   from IDs or nodes. Unresolved roles go to the consolidated checkpoint.
2. Count running instances and skip stopped ones (never start them). With
   fewer than two running, do not deploy that type; ask at the checkpoint.
3. Wave 1 canary: one running secondary per type (any instance if the
   primary is down, provided another stays running). Confirm another instance
   is running and serving first.
4. Validate the canary fully. On failure, stop all remaining networking
   guests and report.
5. Wave 2: remaining secondaries one at a time. Wave 3: primaries last, one
   at a time.

Non-networking guests may go in any position, but primaries wait for every
targeted secondary. Disclose that Caddy's outage includes a `--no-cache`
rebuild that downloads Caddy from caddyserver.com while it is stopped.

## Execute

SSH noninteractively with existing aliases, bounded timeouts and strict
host-key checking, reconfirming the owner on each connection. Use the
integrated terminal (no VS Code tasks); if it is unavailable, stop. LXCs: SSH
to the owner, then
`pct exec <id> --keep-env 0 -- runuser -u dante -- /bin/bash --noprofile --norc`
(no `pct enter`). VMs: trusted `dante` alias, checked with `ssh -G` and
`id -un`; fix SSH config ordering rather than retrying as root. Root is only
for approved administrative actions, never Git or Docker.

Aliases do not expand noninteractively, so `dcd -v` is spelled out below;
confirm it matches the deployed alias:

```bash
set -e
test "$(id -un)" = dante
cd /docker
source /docker/_common/functions.sh
declare -F dpull >/dev/null
# dcd -v in every stack dpull will bring up, using the pre-pull definitions
for app_dir in /docker/*/ /docker/radeon-vm/*/; do
	[ -f "${app_dir}compose.yaml" ] || [ -f "${app_dir}compose.yml" ] || continue
	echo "== down: ${app_dir}"
	(cd "$app_dir" && docker compose down -v)
done
dpull
```

- The down loop mirrors `dpull`'s stack discovery and runs before its pull,
  so containers stop with the definitions that created them. After a
  bootstrap pull, use the pre-pull teardown plan instead.
- `dpull` runs `git pull`, then per stack `pull --ignore-buildable`,
  `build --pull --no-cache` and `up --build -d --remove-orphans`, stopping at
  the first failure. Neither step is stack-scoped.
- Pass arguments safely through SSH, the owner shell and `pct exec`; never
  interpolate discovery output. Never run the body locally or on a Proxmox
  host. If elevated access is required but not already approved, stop.
  Snippets pasted into an interactive SSH shell must avoid `set -e` and
  guard phases with `if`/`return` instead.
- Read remote output through bounded command results (`tail`, `grep`); write
  no logs, staging or scratch files on Proxmox nodes or guests. Local logs go
  only under `/tmp/lxc-deploy-logs/` (tmpfs); judge success from guest
  evidence. Secrets are entered by the user directly, never through chat.

## Validation Routes

Choose one HTTP route per app before the first mutation:

- Normally the app's configured proxied hostname, or its published backend
  when no proxy route exists.
- If ANY Caddy instance is in the rollout, use Caddy's actual backend IP,
  port and protocol for ALL other apps for the whole rollout, including
  baselines and browser checks, even after Caddy recovers. A redirect through
  Caddy or Pocket ID is not backend success; for OAuth apps use an
  unauthenticated backend endpoint and defer the UI handoff. Keep TLS
  verification and report unsupported direct TLS or UI checks as gaps.
- Caddy's own recovery checks use its representative proxied URLs pinned to
  that instance, plus a normal-DNS browser check.
- DNS and other protocols use their actual endpoints. Add a second route only
  for a changed network path or a concrete failure; a proxy pass does not
  clear a direct-endpoint blocker.

## Functional Checks

Use existing healthchecks and documented read-only APIs with bounded
timeouts; parse JSON or XML and report assertions, not response bodies. Take
a baseline before mutation and repeat after settling.

| Service                | Check                                                                                                                                                                                                                                                                                                                       |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AdGuard Home           | `dig +time=3 +tries=1 @<guest-ip> example.com A` against each guest IP, not only the VIP, over UDP and TCP where configured; require valid records. Check keepalived state. Confirm a serving peer before disrupting any instance.                                                                                          |
| qBittorrent            | The in-container healthcheck: `/api/v2/transfer/info` must report `connection_status == "connected"` (recheck the contract). Shares Gluetun's network namespace. No external API requirement; WebUI reachability is optional. No downloads, settings changes or logins.                                                     |
| Gluetun, Soulseek      | Existing healthchecks plus each exposed app's real endpoint or UI; VPN health does not prove app access. Discover, do not invent, Soulseek's endpoint.                                                                                                                                                                      |
| Spoolman               | `/api/v1/health` and the UI via the selected route (`spools.samskeyti.net`, or the backend during a Caddy rollout).                                                                                                                                                                                                         |
| Pocket ID              | `/app/pocket-id healthcheck` in the container and the sign-in page via the selected route (`id.samskeyti.net`, or the backend). Never sign in.                                                                                                                                                                              |
| Immich, Plex, Tautulli | One unauthenticated ping or identity endpoint plus the UI via the selected route. Plex's localhost healthcheck does not prove reachability. If Plex video returns an empty reply over plain HTTP, `secureConnections` may be Required: probe `curl -k https://<ip>:32400/identity`.                                         |
| Internal dependencies  | In-guest native probes. Immich Postgres: Compose healthcheck plus datadir bind ownership against the process UID/GID (`999:999`, source `/docker/immich/data/immich`). Valkey: `PING`, `aof_last_write_status:ok` (strip `\r`), and write access to `/docker/immich/redis-data` as the UID verified from the running image. |

- For permission errors, compare bind ownership and modes with the process
  UID/GID and inspect the specific denied path read-only; also check whether
  bootstrap changed that ownership. No chown, chmod, deletion or database
  recreation until the mismatch is confirmed and a recovery plan approved;
  authorized ownership repairs may then address the verified cause. Compose
  `user:`
  sets in-container identity and does not map host IDs: fix host ownership or
  design an idmapped mount, never daemon-wide `userns-remap`.
- An unexpected response or a failed, unreachable or unauthorized probe is a
  failure or an explicit gap, never a pass. Do not install tools, weaken
  authentication or TLS, or change networking to make a probe pass.

## Verify and Report

1. Check each phase's exit status and bounded output. A failure leaves that
   stack and every later stack down: report which, against the snapshot, and
   stop. No retry, rollback or helper changes without approval.
2. Confirm guest HEAD equals the target SHA, accounting for branch movement.
3. Validate every stack in the guest, not just changed ones:
   - Every snapshot container is running, healthy where healthchecked, and
     created after the deploy started. Account for profiles such as
     `adguardhome-sync`; flag missing, stale or new containers.
   - Settle at least 60 seconds and longer than the largest healthcheck
     `start_period` (Gluetun's is 2 minutes). Compare state and restart
     counts at the start and end; any increase, `restarting`, `exited` or
     `unhealthy` fails. Use the wait for independent read-only checks.
   - Review logs since the deploy start per stack, for example
     `docker compose logs --since <start> --no-color --tail 200`, for errors,
     panics, permission denials, mount failures and crash loops, without
     dumping environment or secret-bearing config.
   - After settling, probe each app's selected route from an approved client
     vantage point with one app-specific response. Bound and verify
     redirects; accept authentication responses only where confirmed as
     expected. Use protocol checks for non-HTTP services and in-guest checks
     for internal dependencies. Do not hit every declared port.
   - If a local healthcheck passes but the guest-IP request fails, compare
     container loopback, bridge IP, published IP and an independent client,
     and inspect network mode, port bindings and listener read-only. A bridge
     failure points inside the container; a working bridge with a failing
     published IP points to host forwarding. For Plex, compare only
     network-related preferences with a working server, redacting tokens and
     never dumping `Preferences.xml`. Change nothing during diagnosis.
   - Caddy, per deployed instance: `caddy validate`, then
     `curl --resolve <hostname>:443:<guest-ip>` with normal TLS and SNI.
     Check specifically changed routes; for global changes check one
     external-backend route (`pve.samskeyti.net`) and one Docker-backed route
     (`spools` or `id`). Proxy 502/503/504 responses fail, and a VIP cannot
     prove an individual instance.
   - Browser: one visit per changed web app on its selected route, verifying
     the expected UI or login page with one non-sensitive screenshot; this is
     the primary UI assertion. Navigate read-only; never log in or submit
     forms. A handoff to `https://id.samskeyti.net` is expected for Pocket ID
     OAuth apps such as Immich; capture the app's initial page promptly. In
     backend mode, defer the handoff. Prefer shared or background pages and
     disclose if tabs cannot be hidden; never change browser, TLS, DNS or
     trust settings, and never browse an HTTPS IP that causes a certificate
     mismatch. A normal-DNS visit does not replace per-instance Caddy
     checks. If the browser cannot validate a page, report the gap and stop,
     except for deferred OAuth handoffs in backend mode.
4. Advance networking waves only after the guest passes. Never claim full
   success with stopped, unreachable, failed or skipped targets.
5. Report per guest: ID, owner, role, before and after SHA, helper result,
   validation results (route, Caddy probes, browser), failures, gaps and
   skipped targets. Keep secrets and runtime status out of `deployments.yaml`,
   do not promise rollback of mutable tags, and never reboot.

## Learn From The Run

Follow the `/deploy` skill's retrospective: use collected evidence only,
record a concrete lesson in the relevant skill, track unresolved incidents in
TickTick, check with `git diff --check`, and do not commit without a request.
