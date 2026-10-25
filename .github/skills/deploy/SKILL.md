---
name: deploy
description: "Lite deployment of published Docker-stack changes: push existing committed main changes, then run dupull on selected running Docker guests. Use for routine /deploy requests that need command-success validation only, without healthchecks, APIs, webpages, or log inspection."
argument-hint: "Optional: stack names or guest IDs, for example caddy or 100 200"
user-invocable: true
disable-model-invocation: true
---

# Deploy

This is the lightweight workflow. Use `/deploy-deep` only when the user asks
for full functional, health, log, or visual validation.

## Scope

- With no arguments, target every running Docker guest in `deployments.yaml`.
  `/deploy all` is equivalent. `/deploy <stack or guest IDs>` narrows the set
  to exactly the matching guests; a stack selects each guest that runs it.
- A free-form "deploy this fix" request is not `/deploy all`: target only the
  guests the change actually affects, using evidence (for example, which guests
  have the faulty state). Shared files such as `bootstrap.sh` or `_common/` do
  not make every guest relevant. Ask if the affected set is unclear.
- A `/deploy` request authorizes pushing already-committed changes on local
  `main` to `origin/main`, then running `dupull` on the selected running
  guests. This includes `dupull`'s APT dist-upgrade, package cleanup and
  autoremove, registry pulls, no-cache builds, Compose up/recreation, and
  orphan removal across every top-level stack in each selected guest. These
  stated effects do not require a second confirmation checkpoint.
- Do not create commits, force-push, change branches, start stopped guests,
  run bootstrap, reboot, alter credentials or SSH trust, or widen the selected
  guest scope. Preserve uncommitted local work; tell the user it was not
  pushed. If publishing is blocked by divergence, missing upstream, or a
  non-`main` branch, stop before guest changes and report the condition.
- Use existing SSH and Proxmox access for the requested work; do not ask again
  before read-only discovery. Obey tool approval prompts and never bypass
  host-key checking or access failures.
- Carry an approved deployment through execution and its completion check in
  the same turn. A clarification of the requested check does not cancel the
  deployment or require another go-ahead. Progress updates describe work being
  performed, not suggestions left for the user to request again. Ask only for
  a genuinely new decision, required approval, or user action that blocks work.

## Target And Publish

1. First follow the mandatory pre-deployment refresh in
   `.github/skills/refresh-deployments/SKILL.md`: complete live discovery,
   update local `deployments.yaml`, and validate it before selecting targets,
   publishing commits, or choosing guest SSH/access routes. Stop if the refresh
   cannot complete; never deploy using a stale map. This metadata update is
   included in the deployment request, but must remain uncommitted unless
   separately approved. It does not expand the requested guest scope.
2. Read `.github/copilot-instructions.md` and the refreshed `deployments.yaml`.
   Confirm the local checkout identity and branch. Preserve and exclude staged, unstaged,
   and untracked local files; do not commit them.
   Read the current deployment-blocker notes in `/configs/ai/pending-changes.md`.
   Skip and report a selected guest with a known unresolved service/network
   blocker; do not treat `dupull` success as clearing it. Lite mode does not
   discover new application reachability failures.
3. Fetch `origin/main` and check the local `main` relationship. If local `main`
   has fast-forwardable commits ahead, push them with ordinary `git push` (no
   force). If it is only behind, use the fetched `origin/main` as the target.
   Stop if local `main` and `origin/main` have diverged or the current branch
   is not `main`. Record the resulting published SHA.
4. Resolve selected guest IDs, current owners, state, and networking role tags
   from the refreshed map and the refresh's live inventory. Use only running
   Docker guests; report stopped guests as skipped and never start them. Do not infer ownership from
   cached metadata; recheck ownership and state immediately before guest
   operations. If placement changes, refresh again before continuing.
5. For LXCs, SSH to the current Proxmox owner and use `pct exec`; do not SSH
   directly to the LXC. For VMs, use the existing trusted alias and confirm
   `ssh -G <alias>` resolves to `dante`; confirm `id -un` after connecting.
   Run guest Git, Docker, Compose, and helpers as `dante`, without `sudo`.
6. Batch read-only discovery by owner. Before `dupull`, verify each selected
   guest is the expected hostname, its `/docker` worktree has no local changes,
   its Git operation can fast-forward to the target SHA, and `dante` can reach
   Docker. If a guest has local changes, is divergent, or fails access checks,
   preserve it and stop that guest without pulling or cleaning it. Continue
   independent preflight for other targets.

`dpull` fetches `origin/main`, verifies the guest's current `HEAD` is an
ancestor of `FETCH_HEAD`, then merges with `--ff-only`. It stops on local-ahead
or divergent history and never creates guest-local merge commits. Keep this
guard even though deployment preflight performs the same ancestry check.

### New Stack Sparse Checkout

When adding a new stack directory to an LXC or VM, inspect
`git config --get core.sparseCheckout`,
`git config --get core.sparseCheckoutCone`, `git sparse-checkout list`, and
the sparse-checkout patterns under the actual Git directory as dante in
`/docker`. Compare the selected stack with bootstrap.sh's host profile and
update that source profile when needed. After fetching the published revision,
add the required stack path in the guest's existing cone or non-cone mode,
preserving all existing stack paths and exclusions, then fast-forward and
verify the new Compose files exist before deployment commands.
`git sparse-checkout add` inherits the configured mode; do not pass
`--cone` or `--no-cone` to `add`, which may not support those options.
Review guest
changes and collisions first; never overwrite local work or replace the entire
profile with a guessed list. Do not run full bootstrap solely to change sparse
checkout. This step is for new stack directories, not extra services added to
an existing included stack, and it does not expand deployment scope.

## Networking Order

AdGuard Home and Caddy remain staggered even in lite mode:

1. Classify roles from live tags and count running instances. If roles are
   ambiguous or fewer than two instances are running, skip that service type
   and report why; do not guess or start guests.
2. Run one secondary of each selected networking type first, one guest at a
   time. Before each, confirm another instance of that type is running via
   Proxmox state. Continue only after `dupull` exits successfully.
3. Run remaining selected secondaries one at a time, then primaries last,
   each only after the previous command exits successfully.

Do not run DNS, API, healthcheck, webpage, Caddy-route, browser, or container
log probes in this workflow.

## Run

Run `dupull` from `/docker` in a fresh noninteractive Bash session as `dante`.
`dupull`, `upgrade`, and `bootstrap` are functions. Source their definitions
explicitly; alias expansion is not required:

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

For an LXC, run that body through its confirmed Proxmox owner with
`pct exec <id> --keep-env 0 -- runuser -u dante -- /bin/bash --noprofile --norc`.
For a VM, run it through its trusted `dante` SSH alias. Do not run it locally or
on a Proxmox host.

`dupull` runs `upgrade` followed by `dpull`. `upgrade` performs APT update,
dist-upgrade, clean, and autoremove with purge. `dpull` pulls Git, pulls/builds
images, and runs `docker compose up --build -d --remove-orphans` for every
top-level stack in `/docker`; it does not use `down -v`. A named stack selects
guests, but does not make `dupull` stack-scoped.

Capture each invocation's real exit status in the calling shell, print a
guest-specific completion marker (ID and exit code), and preserve that status
as the command's exit code. Do not let a final `printf` mask failure. Retain
explicit Git/package/image/Compose errors even if the helper returns zero.
Use the integrated terminal directly for mutations; delegate only bounded
read-only checks when useful. Do not filter interactive commands through
pipelines or use pagers for status output.

If terminal transcripts are unreliable, save known-noninteractive helper output
and its real exit status in separate per-guest files under `/tmp/ai`, after
checking the directory's type and ownership. Read those records to recover
completion; do not rerun an uncertain update without explicit approval.

## Completion

- Run targets sequentially and keep output bounded. A zero exit status from
  `dupull` is the completion criterion for that guest; its successful Compose
  start commands are the validation. Do not inspect container health, call
  APIs, open webpages, read logs, or run visual checks.
- Do not add mount, NFS, image-user, or filesystem write-access probes as
  deployment gates. Use Git/package/image/Compose command errors, not an
  inability to inspect Docker's private volume directories, to judge the run.
- On a nonzero exit or explicit pull/build/up error, stop the rollout. Report
  the guest, command phase, exit status, and that later guests were skipped.
  Do not retry or roll back automatically.
- Exception: a recreate failing with `tried to kill container, but did not
receive an exit event` can mean the old process is still flushing NFS
  writeback (D state in `nfs_wb_all`). Wait for that process to exit, rerun
  `dupull` on the same guest once, and `docker rename` any leftover
  `<hash>_<name>` container back to its service name.
- Docker never updates an existing named volume's `driver_opts`. When a
  published change edits NFS/virtiofs volume options without renaming the
  volume, `docker compose down` that stack and `docker volume rm` its affected
  volumes before `dupull`; share data is unaffected.
- Missing output or an absent exit code means unknown, not failed or complete.
  Recover the original command result first; if unavailable, use one bounded
  read-only check to establish what is known. A matching Git SHA alone does
  not prove image pulls or Compose succeeded. Do not rerun an uncertain
  mutation automatically, start another mutation while it may still be running,
  or declare unrelated guests failed. Preserve the existing terminal recovery
  and stop-on-error rules; report the exact remaining uncertainty if blocked.
- Report the pushed/current published SHA, selected guest IDs and owners,
  `dupull` result per guest, and skipped or failed targets. Keep the report
  concise. For deep checks, use `/deploy-deep` as a separate request.

## Learn From The Run

Before the final report, briefly review the session's failures, tricky steps,
user corrections, repeated work, and avoidable delays. Do this automatically
on success or when stopping for a blocker, using evidence already collected;
do not add probes, log reads, or a session-history investigation for this step.

- If there is a concrete reusable lesson, make a small targeted update to the
  relevant deployment skill. Update `.github/copilot-instructions.md` only
  when the lesson applies across workflows. Preserve concurrent edits and
  existing approvals, safety gates, and lite-mode limits. This step authorizes
  these narrow documentation edits, not operational changes or scope expansion.
- Record unresolved incidents in the canonical pending ledger with verified
  evidence, target/path, blocker, and next safe action. Keep temporary runtime
  observations and unproven hypotheses out of enduring instructions; never
  record credentials or turn a workaround into a permission exception.
- Validate changed documentation with `git diff --check` and mention the
  lesson/update briefly in the final report. Do not commit or push retrospective
  edits without an explicit request; an earlier deployment push does not cover
  newly written documentation. If there is no new lesson, make no edits.
