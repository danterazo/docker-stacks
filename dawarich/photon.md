# Photon Data

## Storage And Backups

LXC 118 uses `rpool-lxc:subvol-118-rootfs` for Dawarich and its databases.
PVE backs up that root disk; the obsolete database-backup script is removed,
not the existing recovery dumps.

The separate managed volume `rpool-lxc:subvol-118-photon` mounts at
`/docker/dawarich/data/photon`. Its approximately 698 GB quota leaves room
for staged updates without reserving that space. `idmap=passthrough` keeps
data owned by `dante:dante (1000:1000)` on both host and guest.

The Photon volume has `backup=0`, `replicate=0`, and all six
`autobackup:` selectors set to `false`. These exclude PVE backups, PVE
replication and the configured ZFS snapshot scheduler. **Ordinary manual
PVE snapshots can still include the managed volume.** Check snapshots
before deleting old releases or estimating space.

## Updating

[update-photon.py](update-photon.py) discovers the latest dated stable 1.x
planet release from GraphHopper's official listing. It runs as root on the
current PVE owner, never inside the LXC or on the workstation. Run this from
the repository on the workstation while LXC 118 is on Kex:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes root@kex python3 - < dawarich/update-photon.py
```

No arguments are required. The script locks concurrent runs, caches the archive
in `/tank/downloads/photon-db/`, resumes partial downloads with two connections,
checks the published MD5, and extracts using the existing Photon image's
parallel decompressor. Extraction runs unprivileged with no network, rejects
links and unsafe paths, and checks all compressed streams before recording a
completed release. MD5 detects corruption; HTTPS is the source-authentication
boundary.

Extraction uses up to 16 decompression threads, bounded by the owning node's
CPU affinity. Its `dawarich-photon-extract` helper disables the serving image's
healthcheck: it is not a running geocoder. Keep the launching terminal/session
alive throughout the update; an interrupted run can leave an incomplete
staging directory, which must not be activated.

Only after extraction completes does it stop/recreate **Photon alone** and
atomically select `current`. It waits for health and tests reverse geocoding.
The app, PostgreSQL and Redis are not restarted. The wrapper's own updater is
disabled so there is only one index writer. Normal Compose operations remain
opt-in through the `geocoding` profile.

Failed staging directories and previous completed releases are retained, never
automatically deleted. A failed cutover exits nonzero without automatic rollback;
inspect the failure before selecting a retained release and recreating Photon.
A retry with the same selected release does not restart a healthy geocoder.
Review old releases and any snapshots before another full staged update;
the quota is not unlimited retention.

Before migrating to Cerulean, check capacity for **both** managed volumes,
Photon's RAM needs, and access to a durable archive cache. Kex's `/tank` is
not assumed to exist on Cerulean: prepare storage there and use the optional
`--cache-dir` override, or revise the cache arrangement before migration.
Do not silently download a planet archive into the host's OS filesystem.

## Ingestion Workers

The app retains four embedded workers for general processing. A separate
`dawarich-worker` uses the image's standalone Sidekiq entrypoint and the
queue-only [configuration](sidekiq-geocoding.yml) for reverse geocoding.
The entrypoint does not forward command arguments, so queue selection must
come from that mounted configuration rather than a Compose `command`.

The worker has eight threads and ten database connections. Both processes
explicitly set `REVERSE_GEOCODING_CONCURRENCY=4`, giving a shared maximum of
four geocoding jobs instead of the embedded worker's default of one.
The website's request-rate setting is separate and applies per process,
not as a cluster-wide throughput guarantee. The worker's healthcheck
requires a fresh Redis heartbeat from its own container.
A three-minute startup grace allows Rails to cold-boot under storage load.

Benchmark queue drain, database waits and host I/O pressure before raising
these limits. Do not interrupt a full-history enqueue job to tune them:
allow it to finish so a retry does not enqueue the same history again.

## Optional Scheduling

No cron job is installed. `--check` only reports the latest upstream release;
`--download-only` fills the cache without touching the LXC. Prefer one of these
for a future weekly job rather than unattended index cutovers.

Root scheduling must use a reviewed, root-owned host copy, not a script
executed from the guest-writable checkout. Example **after** separately
installing that copy at `/usr/local/libexec/dawarich-update-photon.py`:

```cron
0 3 * * 0 /usr/bin/python3 /usr/local/libexec/dawarich-update-photon.py --download-only
```
