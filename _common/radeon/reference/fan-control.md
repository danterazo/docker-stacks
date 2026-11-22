# Radeon Fan Control

## Quiet-First Policy

- Keep `quiet` as the VM boot default. The adaptive profiles use the hottest
  edge, junction, or memory reading across both V620s, not GPU utilization
  or board power. All three start at 5% PWM.
- Prefer Quiet or the last verified setting for ordinary operation on the VM
  and host. Do not treat a brief BMC read timeout or planned service restart
  as evidence that maximum cooling is needed. The VM already holds the last
  setting on a bounded read timeout while checking GPU temperatures.
- Pending: make planned restarts and host-side recovery quiet when cooling
  can be verified. The host watchdog currently sees guest-agent health, not
  GPU temperatures; do not substitute a blind 5% setting on lost telemetry
  or overheating. The host's existing Full Speed fallback remains in place
  until a temperature-aware or separately validated fallback is available.
- Kveikur's `amd-fan-host.service` profile block matches `77a28be`, but the
  unit remains disabled/inactive for the future VM-to-LXC cutover. Keep
  `amd-fan-watchdog.service` active; do not start the host controller alongside
  the VM controller.

## Evidence and Measurement Limits

- Four Wathai 9733 blowers kept spinning at 5% PWM during a visual check;
  cold start at 5% was not verified. At the tested 120 W per GPU cap, the Quiet
  inference run peaked at 74°C memory and requested at most 28% PWM. That is
  not a thermal validation at higher power caps.
- A [VXB listing for a matching-size 9733 blower][vxb] advertises 35.8 CFM,
  2 in H₂O, and 58 dBA without a duty-by-duty curve or stated acoustic test
  conditions. It is not a verified manufacturer data sheet for the installed
  Wathai SKU. Do not infer RPM, airflow, electrical draw, or dBA from PWM.
- The Wathai listing's 12 V × 1.5 A rating implies 18 W per blower or 72 W
  total nominal for four. Neither fan-only power nor dBA was measured during
  tuning. Measure voltage and current on the hub's 12 V feed at fixed duty
  to isolate blower draw; whole-host changes in global BMC mode are not a
  fan-hub-only measurement.

[vxb]: https://vxb.com/products/97mm-by-33mm-brushless-dc-blower-fan-12v-beefy-cfm
