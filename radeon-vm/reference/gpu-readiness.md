# Radeon VM GPU Readiness

## Verified Baseline: 2026-10-23

- VM 105, **radeon-vm**, runs on **kex**; **kveikur** reports offline.
- Ubuntu 26.10, kernel and headers `7.3.0-9.9`, Secure Boot enabled,
  stock Canonical `amdgpu`, and `amdgpu.ppfeaturemask=0xffffffff` active.
- No V620 passthrough or `/dev/kfd` yet. Ollama is healthy with zero restarts;
  vLLM is inactive. These are not GPU inference results.
- Root has about 14 GiB free. Models use NAS-backed NFS 4.2 with `nconnect=8`;
  Ollama's Docker-managed model volume is writable.
- Source preparation is not deployment. Keep GPU-less Ollama running until
  passthrough is functional. Do not activate vLLM implicitly.

## Migration Gates

Rediscover VM ownership and destination health before operating. The current
CPU affinity is `0-4,6-10`, with ten vCPUs, ten NIC queues, `cpu: host`, and
24 GiB RAM. Reconcile affinity and CPU compatibility with the destination;
do not blindly carry Kex CPU numbering over. Both VM disks currently use
`rpool-vm`; verify destination storage, bridge, NAS connectivity, and capacity.
Shutdown, migration, passthrough, package installation, and trust changes need
their applicable approvals. Inspect actual cards and IOMMU groups on Kveikur
before assigning devices. Start with the number the PSU and cooling support.

## Reversible ROM Override

Use the [VM-only soft unlock](https://github.com/Tamalero/amd-v620-soft-unlock/tree/eb60c73faac53bfcc691818a59bf4c965ea6c1bd),
not its experimental bare-metal VFCT procedure and not a W6800 cross-flash.

1. Attach available cards normally and prove stock `amdgpu` and ROCm inference
   work before altering the guest-visible ROM. Identify every card by PCI and
   subsystem IDs, not `card0` or an assumed debugfs index.
2. In the guest, map each card's PCI address to its debugfs DRM entry and dump
   that card's own `amdgpu_vbios`. Preserve the original and its SHA-256 hash.
   Never substitute a downloaded ROM or assume all cards have identical ROMs.
3. Review the pinned upstream `make_odcaps_rom.py` before running it offline
   against copies of the dumps. Verify recognized table layout, capability
   changes, checksum, output hashes, and each original-to-output association.
4. On the current Proxmox owner, place each reviewed output in
   `/usr/share/kvm/` with a distinct filename. Preserve each existing
   `hostpciN` option and add only its corresponding `romfile=`. Record the
   original configuration before the approved VM shutdown/start.
5. Verify every card initializes, exposes the expected OverDrive controls,
   retains its compute units, and completes inference without GPU errors.

Nothing is flashed to the physical cards. Nevertheless, this is a community
workaround tested upstream on older software, not validation of this VM's 7.3
kernel. Never write runtime `pp_features` or `pp_table`: upstream reports SMU
wedges requiring a physical host reboot. Do not raise clocks or power limits.

Rollback removes the added `romfile=` options while preserving other PCI
options, followed by an approved cold VM shutdown/start. A wedged card may
still require a separately approved host reboot. ROM files are node-local:
future migrations must provision the matching files on the destination.

## Lower Power Limits Are a Separate Driver Change

The ROM override alone documents a minimum near **232 W**, not 180 W. The
[Ubuntu toolbox](https://github.com/BlivionIaG/v620_toolbox/tree/050d893fa989d606ef91a08d1da17d015f9adf4f/ubuntu_powertuning)
lowers the driver floor to 120 W, but is validated on kernel 7.0, not 7.3.
Earlier exact-source inspection found its patch anchors do not match 7.3;
the minimum-limit calculation moved to `sienna_cichlid_init_ppt_limits`.
Do not run its installer or automatic kernel hook unchanged.

The current non-installing APT simulation resolves only with an explicit
`libbz2-1.0` downgrade from `1.0.8-6ubuntu0.1` to `1.0.8-6build2`:

```bash
apt-get -s --allow-downgrades install \
  libbz2-1.0=1.0.8-6build2 linux-source-7.3.0=7.3.0-9.9 \
  build-essential flex bison libssl-dev libelf-dev dwarves
```

Observed plan: 51 newly installed, one downgraded, zero removed. This is a
dated simulation, not installation approval or proof that the older package
is security-equivalent. Refresh package/security information and review the
complete new plan before approving any downgrade. Preserve a stock fallback
kernel and module. Adapt and compile against exact matching source/headers,
verify the V620-only change and vermagic, and sign the replacement using an
approved guest-local key and MOK enrollment. Keep Secure Boot enabled.
Enrollment and reboot remain separate user actions; never share private keys.

Only after every attached V620 reports a compatible cap range should the
existing installer and service be installed/enabled through approved guest
administration. The installer deliberately does not enable the service:

```bash
cd /docker/radeon-vm
sudo bash bin/install-v620-powercap.sh
sudo /usr/local/sbin/v620-powercap-apply.sh 180
sudo systemctl enable --now v620-powercap.service
```

These are future activation commands, not commands to run before the driver
and hardware gates pass. The helper identifies matching V620 PCI/subsystem
IDs dynamically, applies to all present cards, checks range and readback, and
does not require a fixed card count. Zero GPUs is a successful no-op, not proof
that tuning works. Reverify the driver override and cap after kernel updates;
do not trust an old successful service status after hardware changes.

## Power and Performance Acceptance

Start measurement at **180 W per card** after the lower floor is verified.
This is an efficiency trial, not a promise of zero throughput loss. Compare
stock, 220, 200, and 180 W under the same model, quantization, context, batch,
prompt, warm-up, and cooling conditions. Try 160 W only if measurements support
it. Select the lowest cap meeting the user's acceptable regression, measuring
prefill and decode separately, plus sustained thermals and stability.

| Cards | 180 W Caps Combined | 250 W per Card Before Caps |
| ----- | ------------------- | -------------------------- |
| 1     | 180 W               | 250 W                      |
| 2     | 360 W               | 500 W                      |
| 4     | 720 W               | 1000 W                     |

These are nominal GPU limits, not wall-power or complete PSU sizing figures.
Allow CPU, motherboard, drives, fans, PSU losses, connectors, cabling, startup,
and transient headroom. Caps apply after driver initialization and may reset
or fail; never size an underspecified PSU assuming they are always enforced.
Passive V620 cards require directed server-grade airflow.

## Stack Activation After GPU Validation

Ollama's default remains GPU-less. After hardware and power checks, explicitly
use both files to expose all passed-through GPUs:

```bash
cd /docker/radeon-vm/ollama
docker compose -f compose.yaml -f compose.gpu.yaml config --quiet
docker compose -f compose.yaml -f compose.gpu.yaml up -d
```

Recreation needs approval. Use both files for subsequent Compose management;
plain Compose alone can recreate the service without GPU access. Do not set
host-specific visibility filters globally. Verify actual GPU offload in
Ollama's logs and `ollama ps`, starting with the existing small
`phi4-mini-reasoning:3.8b` model. Model listing alone proves no GPU execution.

vLLM remains opt-in and defaults to tensor parallelism 1 in both Compose and
its public environment. Explicitly set `VLLM_TENSOR_PARALLEL_SIZE=2` or `4`
only after that many devices and the chosen model/quantization are validated.
Its RDNA image and AWQ checkpoint need runtime compatibility testing; do not
interpret Compose parsing as readiness. Existing `NCCL_P2P_DISABLE=1` remains
unchanged until actual multi-GPU topology and stability tests justify tuning.
