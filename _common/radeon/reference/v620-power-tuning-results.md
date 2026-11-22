# V620 Power-Tuning Results — 2026-11-22

## Outcome and current state

**200 W per card is the provisional balanced choice; 220 W is the more
conservative performance choice.** Do not treat either as fully validated for
sustained or concurrent workloads. At the user's request, testing stopped after
a BMC cooling-control failure and both cards were restored to 120 W. Later, the
user selected **200 W**, which is now applied and configured at boot.

The completed dataset is the `v620-validated-short` sweep: two passes over every
cap from 250 to 120 W. The longer-prompt sweep completed only its first 250 W
request. Dynamic-cap and deliberate concurrency tests **did not run to
completion and have no results**. Their benchmark helpers are prepared, but
their existence does not establish measured performance.

Raw data, logs, and earlier partial/interrupted attempts were copied to:

`/home/dante/gpu-benchmarks/v620-20261122/`

## Completed short-prompt benchmark

- Model: `qwen3.8-27b-gptq`, two V620s at tensor parallelism 2.
- Approximately 3,884–3,891 uncached prompt tokens; 192 fixed output tokens.
- One active sequence; no intentional concurrency. Second pass reverses cap order.
- Nonces prevent prefix reuse. Power/temperature samples every 0.5 seconds.
- Means of two requests per cap; temperatures are maxima across cards/passes.
- Adaptive `quiet` fan profile. Reported fan duty ranged from 5% to 68% in
  the completed sweep; starting temperature and airflow were not fixed.
- Prefill tokens/s means prompt tokens / time to first nonempty streamed text,
  including overhead and the first decode step. Decode tokens/s excludes the
  first streamed token interval. These are synthetic text completions, not
  tool-calling, chat-quality, or long-context accuracy tests.

### Performance

| Cap/card | Prefill tokens/s | vs 250 W | Decode tokens/s | vs 250 W | First token, s | Total, s | Total latency change |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 250 W | 710.1 | baseline | 25.67 | baseline | 5.47 | 12.92 | baseline |
| 220 W | 697.5 | −1.8% | 26.66 | +3.9% | 5.58 | 12.74 | −1.4% |
| 210 W | 698.2 | −1.7% | 26.12 | +1.8% | 5.57 | 12.88 | −0.3% |
| 200 W | 684.8 | −3.6% | 26.14 | +1.9% | 5.68 | 12.99 | +0.5% |
| 180 W | 653.4 | −8.0% | 25.92 | +1.0% | 5.95 | 13.33 | +3.1% |
| 160 W | 616.3 | −13.2% | 26.03 | +1.4% | 6.31 | 13.65 | +5.7% |
| 140 W | 512.7 | −27.8% | 25.93 | +1.0% | 7.62 | 14.99 | +16.0% |
| 120 W | 429.5 | −39.5% | 24.96 | −2.8% | 9.05 | 16.71 | +29.3% |

**Apparent decode improvements at lower caps are run variability, not proof
that a lower cap increases performance.** Only two repeats were made. Earlier
partial sweeps commonly measured about 750–762 prefill tokens/s at 250 W and
700–707 at 200 W (approximately 6–8% lower), illustrating uncertainty in the
completed sweep's unusually weak stock baseline. A strict ≤5% prefill-regression
claim is therefore not established for 200 W; 220 W is the safer candidate for
that target. Small differences between 210 and 220 W are inconclusive.

### Power, temperatures, and four-card budget

Measured power below is **both installed GPUs combined**, not per-card power
and not whole-host wall power. Phase means include transition samples. The
four-card figures are arithmetic based on caps, not actual measured four-card
consumption. Nominal remaining PSU capacity refers to its 1600 W DC output
rating; CPU, motherboard, storage, fans, and transients must fit within it.

| Cap/card | Measured prefill GPU W (2 cards) | Measured decode GPU W (2 cards) | Max junction °C | 4-card nominal cap | Remaining PSU capacity |
|---:|---:|---:|---:|---:|---:|
| 250 W | 447 | 316 | 81 | 1000 W | 600 W |
| 220 W | 399 | 321 | 77 | 880 W | 720 W |
| 210 W | 383 | 321 | 77 | 840 W | 760 W |
| 200 W | 366 | 321 | 75 | 800 W | 800 W |
| 180 W | 332 | 321 | 75 | 720 W | 880 W |
| 160 W | 296 | 317 | 71 | 640 W | 960 W |
| 140 W | 247 | 279 | 68 | 560 W | 1040 W |
| 120 W | 227 | 238 | 66 | 480 W | 1120 W |

At 200 W, measured combined prefill power fell about **18%** from stock in the
completed sweep. At 180 W it fell about **26%**. Decode was already consuming
roughly 160 W per card with higher caps, so 180–250 W caps made little difference
to decode consumption. At 120 W, measured decode power was about **25% lower**,
but prompt processing was substantially slower.

No PSU/cabling or TP4 validation was performed. Four cards can draw factory
power before runtime caps apply or if caps reset/fail; still budget for stock
demand and transients. A 1600 W rating alone does not certify physical suitability.

## Supplemental longer-load observation

The sole completed approximately **15,409-token prompt**, with 256 output
tokens at 250 W, measured:

| Prefill tokens/s | Decode tokens/s | First token, s | Total, s | Combined prefill GPU W | Combined decode GPU W | Max edge/junction/memory °C |
|---:|---:|---:|---:|---:|---:|---:|
| 600.7 | 23.90 | 25.65 | 36.32 | 475 | 335 | 67 / 85 / 66 |

The adaptive fan controller reported 9–84% duty during that request. It is
supplemental evidence, not a comparable multi-cap long-prompt benchmark. The
next 220 W request was aborted when fan monitoring failed; its recorded maximum
junction temperature was 79 °C before abort. The fault was a BMC HTTP 502,
**not** the benchmark's 90 °C thermal cutoff or a demonstrated GPU instability.

Earlier interrupted/competing-load samples remain archived as supplemental
thermal observations. They should not be pooled into controlled performance
averages or attributed to one request's energy consumption.

## Dynamic capping and concurrency

Dynamic prefill → decode switching is a plausible follow-up, **not a measured
recommendation from this session**. The expected candidate is about 200–220 W
for prefill and 140–160 W for decode. Testing 120 W decode is also worthwhile:
fixed-cap results suggest a power benefit, but neither switching overhead nor
dynamic throughput was measured.

For overlapping agents, global GPU caps must account for mixed prefill/decode
work. A switch triggered by one request's first token can reduce power while
another request still needs prefill throughput. Favor a fixed cap until a
server-aware policy is measured. GPU utilization alone does not identify the
phase reliably.

The deployed vLLM setting remained **one sequence**, so simultaneous requests
queue. The planned temporary four-sequence deployment never ran; no concurrent
tokens/s figures are available. Do not estimate or present them as measurements.

## Fan recommendations and unresolved fault

After these tests, `bin/amd-fan.py` was updated at the user's request to recover
from temporary BMC failures rather than exit. Login, read, and write transport
errors and HTTP 408/500/502/503/504 select `quiet`, keep sampling GPU temperatures,
mark control unverified, and retry/reconnect. On recovery the quiet duty is
explicitly applied and read back before control is reported healthy. An
uncertain write is not checked against a stale expected setting. Long/hot
outages generate critical warnings but do not kill the retry loop. Sensor loss,
invalid configuration/readback, and explicit shutdown retain fail-high behavior.

The patch does not make unreachable hardware controllable: the BMC may retain
its last applied setting during an outage. It also does not remove the emergency
fallback for actual sensor faults. Unit tests cover startup/read/write blips,
recovery, prolonged outages, and sensor loss. The renamed `amd-fan.service` and
host `amd-fan-watchdog.service` were subsequently started and verified; no new
inference tests were run after the patch.

- The user prefers `quiet`; **keep `quiet` for any follow-up comparisons** so
  they represent daily use. It was adequate for the short completed tests, but
  the longer stock test reached an 85 °C junction hotspot. If sustained
  200–220 W tests also approach that temperature, consider an earlier/stronger
  under-load ramp in `quiet`, or optionally `balanced`. These are conditional
  suggestions, not a requirement to change the daily profile. No profile was
  changed by the power-tuning tests.
- Keeping the user-validated 5% idle floor does not require keeping a gentle
  under-load ramp; the current balanced/performance profiles ramp earlier while
  retaining the same idle floor.
- Fix the BMC communication reliability first. The fan controller received repeated
  HTTP 502 errors, stopped, and could not initially confirm emergency full-speed
  cooling. A separate emergency attempt also failed at BMC login with
  HTTP 502. **Do not resume sustained inference until fan control or fixed
  physical airflow is independently verified.**
- Full speed was attempted only as an emergency fallback after fan control
  stopped, not as a required benchmark condition or daily profile. All completed
  measurements used adaptive `quiet` cooling.
- The fan controller expects exactly two V620s. When four are installed, update
  and validate that expectation and retest every card's temperatures/airflow.

## Provisional settings and permissions

- **200 W:** balanced static candidate; nominal 800 W for four GPUs.
- **220 W:** conservative performance candidate; nominal 880 W for four GPUs.
- **180 W:** efficiency option if roughly 8–12% less prefill throughput is
  acceptable; decode remains close to the higher-cap runs.
- **120–140 W:** lower power/heat, but substantial fixed-cap prompt-processing
  slowdown. Not the recommended general-purpose static choice for long agent
  prompts.
- Use one shared cap for two and four cards initially; the measurements do not
  justify card-count-based switching rules. Revalidate after adding the cards.

Both cards and the enabled boot-service override are set to **200 W**. The
shared cap helper detects all matching cards rather than assuming a fixed card
count. The per-card cap was not revalidated on four GPUs.

The temporary direct-write access is no longer needed. Restore ownership:

```bash
sudo chown root:root /sys/class/hwmon/hwmon{0,1}/power1_cap
```

`amd-cap` still works: displaying caps requires no sudo, changing caps invokes
sudo, and the boot service already runs as root. Sysfs ownership resets on
reboot/driver recreation; permanent user ownership is unnecessary.

Benchmark helpers and report-generation code have unit tests; these tests
validate software behavior, not GPU thermal or hardware safety. See
[`powercap-benchmark.md`](powercap-benchmark.md) for reproducible follow-up runs.
