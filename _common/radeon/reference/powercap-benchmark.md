# V620 Power-Cap Benchmark

`../bin/benchmark-powercaps.py` compares the running vLLM model with unchanged
tensor parallelism and server settings. It does not change clocks, voltages,
drivers, fan profiles, or the boot service.

## Running

Reserve an exclusive inference window and finish any fan-control changes first.
The benchmark requires healthy `amd-fan` monitoring and write access to the
detected V620s' `power1_cap` controls. On kveikur, `amd-cap` reports caps
without writes; setting caps requires root. Permanent user ownership of sysfs
controls is unnecessary.

```bash
cd /docker/_common/radeon
python3 bin/benchmark-powercaps.py \
  --wait-ready 900 \
  --caps 250 220 210 200 180 160 140 120 \
  --rounds 2 \
  --output /tmp/opencode/v620-sweep-UNIQUE-NAME
```

Use an unused output directory. `--wait-ready` waits for 30 continuous seconds
of an idle inference server and healthy fan status. It does not lock out other
clients; do not submit other requests during the test.

The script saves the original caps and restores each on normal exit, request
failure, thermal cutoff, SIGINT, or SIGTERM. SIGKILL, a host failure, or loss of
write access can prevent restoration; independently verify with `amd-cap` after
an interrupted test. Caps and permissions can reset after driver reload/reboot.

## Measurement

- Warm up the model at the starting cap.
- Run caps in descending order, then reverse order on the second pass.
- Place a unique nonce at the beginning of every prompt and verify no new
  prefix-cache hits. Compare the same filler workload and fixed output length.
- Measure approximate prefill throughput as prompt tokens / time to first
  nonempty streamed text. This includes request overhead and the first decode
  step; it is not an isolated kernel measurement.
- Measure decode throughput as (output tokens - 1) / time between first and last
  streamed text. Check chunk counts when interpreting the measurement.
- Sample power, utilization, clocks, edge/junction/memory temperatures, and
  reported fan settings every half second.
- Stop at 90 °C on any GPU temperature sensor, changed cap, missing required
  sensors, or unhealthy/stale fan monitoring. A fan-service restart invalidates
  the active run even if it temporarily sets full-speed cooling.

Outputs include `metadata.json`, `results.json`, individual request summaries,
and `*.sensors.json` raw samples. Failed requests retain sensor samples but do
not enter `results.json`. Power averages include phase transitions and should
not be confused with peak board demand or measured wall power. Brief sensor
readings may exceed the nominal cap.

For a longer-prompt confirmation, increase `--prompt-repeats` (the default 160
is about 3.9K tokens on the currently served Qwen tokenizer) and test stock plus
the candidate caps. A short sweep alone is not sustained thermal validation.

`--decode-cap 140` switches from each tested prefill cap to 140 W after the first
output text arrives. The request summary records `cap_switch_ms` and the decode
cap; sensor samples record the requested cap. This is a controlled
single-request experiment, not a production scheduling policy. Concurrent
prefill and decode cannot safely be classified by watching only one stream.

`../bin/benchmark-concurrency.py --output /tmp/opencode/UNIQUE-NAME` temporarily
recreates vLLM with `--max-num-seqs 4`, warms four workers, and measures
synchronized cohorts of 1, 2, and 4 requests. It preserves the original deployed
command in the output directory and recreates the original command on exit.
This requires explicit approval to restart inference. It does not restart or
change fan control. Model reloads may take several minutes. SIGKILL or a host
failure can prevent deployment restoration; retain `restore-command.json` for
manual recovery. Do not change the Compose configuration during this test.

Concurrent results report per-request decode tokens/s, mean/max first-token
latency, the sum of overlapping decode rates, and cohort output tokens / total
elapsed seconds. The latter includes prefill, so it is distinct from steady
decode throughput. Homogeneous synchronized cohorts do not represent every
mixed-length agent workload or continuous arrival pattern.

## Four-Card Planning

Four GPUs at the factory 250 W cap total 1000 W, leaving a nominal 600 W of a
1600 W PSU's rated DC output for the host and margin. At a cap of C watts,
nominal remaining capacity is `1600 - 4*C` watts. This is budget arithmetic,
not a physical validation of the PSU, rail/connector limits, cabling, or cooling.
PSU efficiency affects AC input, not the PSU's rated DC output capacity.

Account for the host CPU, motherboard, drives, fans, and transients. Size for
stock GPU demand too: runtime caps may reset, fail, or not yet apply at startup.
The existing power-cap helper targets all detected matching V620s dynamically;
verify new cards' supported ranges and readback before loading all four.

The fan controller currently expects exactly two V620s. Update and validate that
expectation when four cards are installed; do not simply assume its current
two-card configuration will continue adaptive control. Repeat performance and
thermal validation at TP4; TP2 results do not predict TP4 performance exactly.
