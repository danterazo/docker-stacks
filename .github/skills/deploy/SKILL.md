---
name: deploy
description: "Lite deployment of published Docker-stack changes: push existing committed main changes, then run dupull on selected running Docker guests. Use for routine /deploy requests that need command-success validation only, without healthchecks, APIs, webpages, or log inspection."
argument-hint: "Optional: stack names or guest IDs, for example caddy or 100 200"
user-invocable: true
disable-model-invocation: true
---

# Deploy

Lightweight workflow: push committed `main`, then run `dupull` on the
selected running Docker guests. Use `/deploy-deep` only when full health,
log, API or visual validation is requested. A plain "deploy" request means
this skill, not a Make target.

## Scope and Authorization

- No argument or `all`: every running Docker guest in `deployments.yaml`.
  `/deploy <stacks or guest IDs>`: exactly those; a stack selects every guest
  that runs it.
- A free-form "deploy this fix" targets only the guests the change actually
  affects, by evidence. Shared files such as `bootstrap.sh` or `_common/` do
  not make every guest relevant; ask if the set is unclear.
- "Deploy recent changes to X" means deploying the current published branch,
  with all intervening commits, to X's guests. Do not review history to pick
  commits; the fast-forward checks still apply.
- The request authorizes an ordinary push of committed local `main` and
  `dupull` on the selected running guests, including its APT dist-upgrade,
  clean and `autoremove --purge`, image pulls, no-cache builds, Compose
  recreation and orphan removal across every top-level stack in each guest.
  No second confirmation is needed.
- Not authorized: creating commits, force-pushing, changing branches,
  starting stopped guests, bootstrap, reboots, credential or SSH-trust
  changes, or widening the guest scope. Preserve uncommitted local work and
  say it was not pushed; alert the user to staged changes.
- Use existing SSH and Proxmox access without asking again. Obey tool
  prompts; never bypass host-key or access failures.
- Carry an approved deployment through completion in the same turn. Ask only
  for a genuinely new decision or a blocking user action. A user pause stops
  push, refresh and deployment until explicitly resumed.

## Preflight

1. Run the mandatory refresh in `.github/skills/refresh-deployments/SKILL.md`,
   including its separate metadata commit when there is drift. Stop if it
   cannot complete.
2. Confirm the local checkout identity and branch. Check TickTick (Projects >
   Homelab) for unresolved blockers on selected guests; skip and report
   those, since `dupull` success does not clear them.
3. Fetch `origin/main`. Push fast-forwardable local commits with plain
   `git push`; if local `main` is only behind, target `origin/main`. Stop if
   they diverged or the branch is not `main`. Record the published SHA.
4. Resolve selected guests, owners, state and role tags from the refresh.
   Use only running Docker guests; report stopped ones as skipped. Recheck
   owner and state immediately before operating on each guest.
5. Reach LXCs through their owning node with `pct exec`; reach VMs through
   their trusted alias after confirming `ssh -G` resolves to `dante` and
   `id -un` matches. Run guest Git, Docker and helpers as `dante`, no `sudo`.
6. Batch read-only checks by owner. For each guest confirm: the expected
   hostname; no tracked changes in `/docker`; a fast-forward to the target
   SHA is possible; `dante` reaches Docker; and no container is unhealthy,
   restarting or exited (state from `docker ps` only). A failing guest is
   preserved and skipped without pulling or cleaning; continue preflight for
   the others. Report untracked files and leave them unless they collide
   with incoming paths.
7. New stack directory on a guest: as `dante` in `/docker`, inspect
   `core.sparseCheckout`, `core.sparseCheckoutCone` and
   `git sparse-checkout list`, and compare with the host profile in
   `bootstrap.sh` (update that profile if needed). After fetching, run
   `git sparse-checkout add <stack>` in the existing mode (do not pass
   `--cone` or `--no-cone`), preserving existing paths and exclusions, and
   confirm the Compose files exist. Never run full bootstrap for this. New
   services in an already-included stack do not need this step.

## Networking Order

AdGuard Home and Caddy stay staggered even in lite mode:

1. Classify roles from live tags. If roles are ambiguous or fewer than two
   instances are running, skip that type and report why.
2. Run one secondary of each type first, one guest at a time, after
   confirming in Proxmox that another instance of that type is running.
3. Then the remaining secondaries, then primaries last, each only after the
   previous `dupull` exits successfully.

Do not run DNS, API, healthcheck, webpage, browser, Caddy-route or log probes
in this workflow.

## Run

Run in a fresh noninteractive Bash as `dante`. `dupull` and `upgrade` are
functions, so source them explicitly:

```bash
set -e
test "$(id -un)" = dante
cd /docker
source /docker/_common/aliases.sh
source /docker/_common/utility-aliases.sh
source /docker/_common/functions.sh
declare -F dupull >/dev/null
declare -F upgrade >/dev/null
dupull
```

For an LXC, run it on the confirmed owner through
`pct exec <id> --keep-env 0 -- runuser -u dante -- /bin/bash --noprofile --norc`.
For a VM, use its trusted `dante` alias. Never run it locally or on a
Proxmox host.

`dupull` runs `upgrade` (APT update, dist-upgrade, clean, autoremove with
purge), then `dpull`: fetch `origin/main`, verify `HEAD` is an ancestor of
`FETCH_HEAD`, `merge --ff-only`, then for every top-level stack pull/build
images and run `docker compose up --build -d --remove-orphans` (never
`down -v`). A named stack selects guests; `dupull` is not stack-scoped.

Capture each invocation's real exit status and print a per-guest marker (ID
and exit code) without masking it. If terminal transcripts are unreliable,
write helper output and exit status to separate per-guest files under
`/tmp/ai` (check its type and owner first) and read them back. Run mutations
in the integrated terminal; delegate only bounded read-only checks. Do not
pipe interactive commands or use pagers.

## Completion

- Run targets sequentially with bounded output. Exit status 0 from `dupull`
  completes a guest. No health, API, web, log or visual checks, and no mount,
  NFS or write-access probes as gates.
- On a nonzero exit or an explicit Git, package, image or Compose error, stop
  the rollout and report the guest, phase, exit status and skipped guests. No
  automatic retry or rollback.
- Exception: a recreate failing with `tried to kill container, but did not
receive an exit event` can mean NFS writeback is still flushing (process in
  D state, `nfs_wb_all`). Wait for it to exit, rerun `dupull` once on that
  guest, and `docker rename` any leftover `<hash>_<name>` container back to
  its service name.
- Docker never updates an existing named volume's `driver_opts`. When a
  published change edits NFS or virtiofs volume options without renaming the
  volume, `docker compose down` that stack and `docker volume rm` the
  affected volumes before `dupull`; share data is unaffected.
- Missing output or exit status means unknown, not passed or failed. Recover
  the original result or run one bounded read-only check; a matching SHA
  alone does not prove pulls or Compose succeeded. Never rerun an uncertain
  mutation or start another while it may still be running.
- Report the published SHA, guests and owners, per-guest `dupull` results,
  and skipped or failed targets. Lite success confirms `dupull` only, not
  application reachability.

## Learn From The Run

Before the final report, review failures, user corrections, repeated work and
delays using evidence already collected; add no probes for this. Put a
concrete reusable lesson in the relevant deployment skill (the repo's
`.github/copilot-instructions.md` only for cross-workflow lessons) without
weakening approvals, gates or lite limits. Track unresolved incidents in
TickTick with evidence, target, blocker and next safe action; keep
credentials and unproven hypotheses out of instructions. Check edits with
`git diff --check` and do not commit them without an explicit request.
