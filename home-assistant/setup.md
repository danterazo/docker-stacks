# Home Assistant and Matter

## Deployment

LXC 124 (`home-assistant`) runs on Cerulean at `192.168.30.124`, with
4 GiB RAM, a 32 GiB root filesystem and automatic startup. Its unprivileged
Ubuntu/Docker baseline comes from LXC 100. The hostname-based bootstrap
profile includes this stack automatically; no bootstrap change is required.

Home Assistant Container has no managed apps/add-ons. The separate
[Matter.js Server](https://github.com/matter-js/matterjs-server) provides
the Matter integration's WebSocket API. Home Assistant officially recommends
HAOS with its Matter app; standalone Docker Matter deployments are
self-managed and unsupported.

Both containers use the LXC's host network, not Docker bridge networking.
No USB radio, Bluetooth passthrough or privileged Docker container is needed
for sharing existing Matter-over-Wi-Fi devices through the iPhone app.

For first installation only, as `dante`:

```bash
cd /docker/home-assistant
mkdir -p data/homeassistant data/matter
test ! -e data/homeassistant/configuration.yaml &&
  cp reference/configuration.yaml data/homeassistant/configuration.yaml
docker compose config --quiet
docker compose pull
docker compose up -d
```

Home Assistant 2026.8 and newer manages HTTP settings under
**Settings > System > Network**. Do not add an `http:` block to
`configuration.yaml`; doing so imports deprecated YAML settings and raises a
repair. Set the following values in the Network UI before relying on the
Caddy hostname:

- server host: `192.168.30.124`;
- trust X-Forwarded-For: enabled;
- trusted proxies: `192.168.30.203/32`, `192.168.30.204/32` and
  `192.168.30.205/32`.

Do not overwrite an existing configuration. The Matter image writes as
`dante:dante (1000:1000)`; create its data directory as that identity.
Home Assistant uses its image's default user. Back up the entire ignored
`data/` directory, including Home Assistant's `.storage/` and Matter's fabric
keys. Do not commit or publish those files. Losing Matter fabric state can
require sharing every device again.

## Onboarding and sharing a light

1. Open `https://home.samskeyti.net` and create the Home Assistant owner
   account yourself. Install the Home Assistant Companion app on your iPhone
   and connect it to that instance.
2. In Home Assistant, add the **Matter** integration under
   **Settings > Devices & services**. Deselect the managed Matter app option
   and enter `ws://127.0.0.1:5580/ws`.
3. In Apple Home, open one light's accessory settings and choose
   **Turn On Pairing Mode**. Use the newly generated sharing code, not the
   original packaging code. Do not reset or remove the accessory.
4. In the iPhone Home Assistant app, find **Matter** under
   **Settings > Connectivity**. Select **Add device**, choose the
   existing-device/Apple Home option and enter the sharing code. Keep it private.
5. Name the device and assign its room. Verify its state and, when ready,
   test one on/off operation and brightness/color if it is an actual bulb.
   Verify Apple Home still controls it before adding the remaining lights.

Home Assistant joins its own Matter fabric without replacing Apple Home.
TP-Link states that KP125M firmware 1.4.1 enables Matter 1.3 real-time power
and historical energy data and that Home Assistant supports this capability.
Update older plugs before removing Kasa; the Matter fabric should then
provide both control and metering.

## Energy tracking

As of 2026-11-24, the live Energy dashboard tracks all eight commissioned
KP125M plugs: `Desk Lamp`, `Lights`, `Kex`, `Kveikur`, `Óveður`,
`NerdQAxe++`, `Varðeldur` and `Xfinity XB10`. Each uses its cumulative
Matter energy sensor plus its live power sensor. The `Left Lamp` and
`Right Lamp` Matter bulbs are control-only and are not energy sources.

After pairing, open each KP125M device in Home Assistant and confirm it has:

- a current-power sensor in watts;
- a cumulative energy sensor in watt-hours or kilowatt-hours;
- increasing energy values while the connected appliance uses power.

Use the cumulative energy sensor in the Energy dashboard under
**Settings > Dashboards > Energy**. Current power alone is not an Energy
dashboard source. Add each measured plug as an individual device so its load
can be identified separately. The equipment plugs at `.103` through `.107`
are the useful metering targets; light plugs at `.100` through `.102` matter
less unless their consumption is useful to track.

Home Assistant cannot infer cumulative energy from a switch-only Matter
endpoint. If a paired KP125M exposes no energy entity, confirm current firmware
and compare its Matter diagnostic clusters before treating it as an
integration fault. Control and metering do not require a Kasa cloud login.
Kasa may still be needed for a firmware update on an older device.

## Xcel Energy rates

The Home Assistant **Opower** integration does not list Xcel Energy as a
supported utility, so a direct Xcel account login is not currently supported.
Do not enter Xcel credentials into a different utility entry. Xcel's Minnesota
portal provides customer data access through Green Button or manual export,
but that is not an automatic Home Assistant account integration.

Electric cost must follow the actual Xcel plan and service territory. It can
change by season and rate riders, and optional Time-of-Day or Time-of-Use
plans have on- and off-peak periods. Confirm the plan and current tariff on
the Xcel bill before assigning a Home Assistant price; a public average or
web-page rate can materially misstate the cost. Once confirmed, configure
the Energy dashboard with a fixed price for a flat plan or a scheduled
dynamic-price entity for a time-varying plan.

Official starting points:

- [Xcel Minnesota rate books](https://www.xcelenergy.com/company/rates_and_regulations/rates/rate_books)
- [Xcel customer data access](https://mn.my.xcelenergy.com/s/privacy/data-access)
- [Home Assistant Opower support](https://www.home-assistant.io/integrations/opower/)

## Model Context Protocol

Home Assistant's **Model Context Protocol** integration is enabled for
`https://home.samskeyti.net/api/mcp`. The main endpoint exposes all current and
future Home Assistant AI tool sets, requires an administrator account and is
not read-only. Home Assistant stores its OAuth grants per client; do not copy
tokens between machines.

The Home Assistant base URLs are:

- external: `https://home.samskeyti.net`;
- internal: `http://192.168.30.124:8123`.

OpenCode is registered as `home-assistant` with the shared Linux/WSL
configuration in `/configs/ai/opencode/opencode.json` and with the separate
native Windows OpenCode configuration. Copilot uses the node-local
`~/.copilot/mcp-config.json` on WSL2/Linux or
`C:\Users\dante\.copilot\mcp-config.json` on Windows. VS Code discovers the
Copilot-global registration.

After copying or synchronizing a client configuration, authenticate each
runtime separately:

```bash
opencode mcp auth home-assistant
opencode mcp list
```

Complete the Home Assistant sign-in in a browser and approve only the actions
you understand. A displayed registration is not a completed sign-in. A
connected server can inspect and control Home Assistant because the main URL
is not read-only.

## Initial device inventory

Samskeyti's leases and Matter advertisements were checked on 2026-11-24.
Dynamic addresses must be rechecked before use.

| Device                         | IoT IPv4 address                      | Role                                                                        |
| ------------------------------ | ------------------------------------- | --------------------------------------------------------------------------- |
| `kp125m-desktop-lamp`          | `172.16.10.100`                       | Kasa Matter plug; on/off only                                               |
| `kp125m-bedroom-lights`        | `172.16.10.101`                       | Kasa Matter plug; on/off only                                               |
| `kp125m-living-room-lights`    | `172.16.10.102`                       | Kasa Matter plug; on/off only                                               |
| AiDot / unnamed Matter devices | `172.16.10.112`, `.83`, `.203`, `.52` | User identifies the bulbs as Linkind A21 E26, 1600 lm; room mapping pending |

Other KP125M plugs at `.103` through `.107` power equipment and are excluded
from initial light-control tests. A Govee lamp reservation at `.210` did not
have an active lease or appear in the observed Matter advertisements.

## Network caveat

The initial deployment leaves Samskeyti unchanged. `SSK-IoT` is a separate,
Wi-Fi-only bridge (`172.16.10.0/24`, IPv6 `fdda:beef:2::/64`), while this LXC
is on wired LAN. The router already reflects IPv4/IPv6 mDNS and allows
LAN-to-IoT forwarding, but reflected discovery alone does not establish
Matter control or reliable IPv6 reachability. The existing IoT-to-LAN rule
allows ports 5540/5641; Matter controllers can use ephemeral UDP ports, so
that rule is not sufficient evidence of a working Matter path.

The [Matter server networking requirements](https://github.com/matter-js/matterjs-server/blob/main/docs/os_requirements.md)
recommend the controller, devices, commissioning phone and any Thread
border router share a network segment, without mDNS reflectors. If sharing
fails or operation is unreliable, design and approve a direct IoT attachment
before changing router bridges, VLANs or firewall policy. Do not flatten
the network or broadly open IoT-to-LAN access as a shortcut.

During commissioning, keep Bluetooth and the Companion app's local-network
permission enabled. Follow the platform's same-network requirements;
joining `SSK-IoT` alone does not put the LAN-hosted controller on that segment.
Wi-Fi Matter bulbs do not require a Thread border router.

The Home Assistant UI is reverse-proxied as `https://home.samskeyti.net`.
The route is committed for every Caddy node; Caddy 203 and 204 are currently
verified, while 205 is tracked for catch-up when Kveikur SSH access returns.
Direct LAN access remains available at `http://192.168.30.124:8123`.
Caddy source addresses are explicitly trusted for forwarded client addresses.
Matter's
unauthenticated management API listens only on guest loopback and is reachable
by Home Assistant because both containers use host networking. No WAN
forwarding or Tailscale sidecar is configured.

## Checks

```bash
cd /docker/home-assistant
docker compose ps
curl --fail http://192.168.30.124:8123/
curl --fail https://home.samskeyti.net/
docker inspect --format '{{.State.Health.Status}}' matter-server
```

After onboarding, confirm the Matter integration connects and the first
device remains controllable from both Home Assistant and Apple Home.
Container readiness alone does not verify pairing.

References:

- [Home Assistant Container installation](https://www.home-assistant.io/installation/linux/)
- [Home Assistant Matter integration and multi-admin sharing](https://www.home-assistant.io/integrations/matter/)
- [Matter.js Docker configuration](https://github.com/matter-js/matterjs-server/blob/main/docs/docker.md)
- [KP125M firmware and Matter energy support](https://www.tp-link.com/us/support/download/kp125m/)
