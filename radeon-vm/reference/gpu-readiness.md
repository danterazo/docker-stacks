# Radeon VM GPU Readiness

## Boot Safety and Host Staging: 2026-11-22

- After an earlier assistant incorrectly instructed installation of an
  unsigned override under Secure Boot, both that override and the separately
  signed `updates/amdgpu.ko.zst` were preserved in
  `/var/lib/v620-driver-preserved-20261122.T5NoOP`, together with the prior
  initramfs. The custom signer's key was not enrolled and no import was pending.
  Preserve these files until separately approved cleanup.
- After the stock fallback was restored, the user reinstalled the unsigned
  `7.3.0-11-generic` override and regenerated the initramfs without rebooting.
  Secure Boot remains enabled; the unsigned module will be rejected if module
  signature enforcement remains active at the next boot. Resolve signing or
  disable guest Secure Boot before reboot, or restore the stock fallback.
  The loaded stock driver still reports 250–250 W on both cards. The enabled
  powercap service has an override targeting 120 W and its last run failed
  against the stock 250 W minimum; no 120 W cap has been verified.
- In VM 105, `amd-cap` is a Bash function in the shared shell aliases and in
  `/home/dante/.bash_aliases`: without arguments it displays caps; with a
  wattage it invokes `/scripts/hardware/amd-cap.sh` via sudo. The old
  `radeon-cap.sh` path is
  retained as a compatibility wrapper for the installed powercap service.
  The shared script currently matches V620 PCI/subsystem IDs only. Its source
  changes have not been published or verified on kveikur.
- `amd-cap 120` attempts every detected V620 and reports success or failure
  per card. A failure does not stop other cards, so a failed run may have
  changed some cards. To select cards, append their full current PCI addresses
  or use `1`–`4` as shorthand for `0000:01:00.0`–`0000:04:00.0`, for example
  `amd-cap 120 1 2` or `amd-cap 250 0000:01:00.0`. Numbers are PCI bus
  addresses, not detected-card positions; unmatched targets are rejected.
  250 W is the observed factory cap, not an unlimited setting. Check addresses
  after hardware or VM changes.
  Individual changes are temporary: the enabled guest boot service currently
  attempts 120 W on every detected V620 at startup, overriding per-card choices.
- On kveikur, `/var/lib/v620-builds/7.3.5-1-pve` contains the exact packaged
  Proxmox headers, upstream Linux 7.3.5 source and a staged 120 W patch. The
  candidate `linux-7.3.5/drivers/gpu/drm/amd/amdgpu/amdgpu.ko` compiled with
  `7.3.5-1-pve` vermagic and contains the powerfix log string; its SHA-256 is
  `7023b47984c0ce2da2f22c8001cf8a543e628d50c05dd584661f306158b0e271`.
  The Proxmox-specific source provenance and runtime behavior are not yet
  validated; do not install the candidate merely because it compiles. The
  active host driver remains stock and both V620s remain assigned to VM 105.
- Host build dependencies `m4`, `flex`, `bison`, `libzstd-dev` and `libelf-dev`
  were installed. Headers were extracted into the staging directory, not
  installed as a package; the existing Zenpower DKMS auto-install was avoided.

## vLLM Update: 2026-11-21

Two V620s are now passed through. The vLLM smoke test has run on both GPUs;
see [`../vllm/README.md`](../vllm/README.md) for the tested configuration,
limitations and current power-cap observations. The baseline below is historical.

## Observed Guest Baseline: 2026-11-21

- `radeon-vm` is a KVM guest running Ubuntu 26.10, kernel
  `7.3.0-11-generic`, with Secure Boot enabled and
  `amdgpu.ppfeaturemask=0xffffffff` on the kernel command line.
- Two V620s, guest PCI addresses `0000:01:00.0` and `0000:02:00.0`, are
  bound to `amdgpu`. `/dev/kfd` and two render nodes are present. Both cards
  report a 250 W cap and a 250–250 W range.
- The loaded `amdgpu` source version matches the stock module selected by
  `modinfo`; no 180 W powercap service is installed. There is no evidence
  that the lower-floor patch is active.
- Ollama is healthy, but its running container has no GPU device mappings.
  vLLM is restart-looping; its log showed `getpwuid(): uid not found: 1000`.
  Neither observation establishes working GPU inference.
- Root had about 17 GiB free. The running Ollama container mounts its
  Docker-managed NFS model volume at `/models`.

## Observed Host Baseline: 2026-11-21

- `kveikur` is the Proxmox VE 9.2 node hosting VM 105, running
  `7.3.5-1-pve`; host Secure Boot is disabled. The guest Secure Boot setting
  is separate. A stock 7.0.14-30-pve kernel is also present in both configured
  EFI boot partitions; verify recovery access before changing boot state.
- Host PCI devices `0000:30:00.0` and `0000:43:00.0` are the two V620s,
  both bound to `vfio-pci` and assigned to VM 105 through a PCI mapping. The
  stock `amdgpu` module is installed and loaded but does not own those cards.
- The host has a Threadripper Pro 3945WX, 32 GiB RAM, two Samsung 980 500 GB
  NVMe drives in a ZFS mirror, and an ASPEED display controller. Other power
  consumers, PSU cabling, and cooling need physical verification.
- Matching Proxmox 7.3 headers and source were not installed. An APT
  simulation for headers and build tools proposed ten new packages and no
  upgrades or removals; nothing was installed.

These are dated observations; refresh them before making changes.

## Migration Gates

Rediscover VM ownership, physical hardware, and destination health before
operating. Verify CPU compatibility, affinity, storage, bridge, NAS
connectivity, and capacity rather than carrying node-specific settings over.
Inspect actual cards, IOMMU groups, PSU cabling, and cooling before assigning
or adding devices. Account for stock power before any runtime caps apply.

## Reversible ROM Override

The [VM-only soft unlock](https://github.com/Tamalero/amd-v620-soft-unlock/tree/eb60c73faac53bfcc691818a59bf4c965ea6c1bd)
is optional for OverDrive controls; it is not a replacement for the
lower-floor driver patch. Prefer the toolbox patch for power-capped inference,
and test whether it is sufficient before considering the ROM override. Do not
use the experimental bare-metal VFCT procedure or a W6800 cross-flash.

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

The old APT simulation targeted a different guest kernel and is no longer a
deployment plan. Recheck exact source, headers, dependencies, and security
updates for the kernel being patched. Preserve a stock fallback kernel and
module. Adapt and compile against exact matching source/headers,
verify the V620-only change and vermagic, and sign the replacement using an
appropriate local key if Secure Boot requires it. Enrollment and reboot need
separate review; never share private keys.

For host inference or LXC, the host owns the GPU and needs the host-kernel
patch; a guest driver patch does not change the host driver. The documented
Ubuntu and Fedora toolbox builds do not establish compatibility with the
Proxmox host kernel; the Ubuntu rebuild script deliberately skips non-generic
kernels. Obtaining matching Proxmox source, adapting the patch for 7.3, and
testing a host build are separate work. Verify source, headers, recovery, and
hardware ownership first. Host changes can affect other guests, and a host
patch cannot be tested on these cards while VM 105 owns them.

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

## Inference Validation

vLLM has completed a two-V620 smoke test; validate the currently selected
model, quantization and tensor parallelism before treating other configurations
as ready. Review the current Compose and environment files rather than relying
on old defaults. Model listing alone does not prove GPU execution. Keep
conservative P2P settings until actual topology and stability tests justify
tuning.
