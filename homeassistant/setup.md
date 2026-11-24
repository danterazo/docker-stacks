# Home Assistant and Matter

## Deployment

LXC 124 (`homeassistant`) runs on Cerulean at `192.168.30.124`, with
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
cd /docker/homeassistant
mkdir -p data/homeassistant data/matter
test ! -e data/homeassistant/configuration.yaml &&
  cp reference/configuration.yaml data/homeassistant/configuration.yaml
docker compose config --quiet
docker compose pull
docker compose up -d
```

Do not overwrite an existing configuration. The Matter image writes as
`dante:dante (1000:1000)`; create its data directory as that identity.
Home Assistant uses its image's default user. Back up the entire ignored
`data/` directory, including Home Assistant's `.storage/` and Matter's fabric
keys. Do not commit or publish those files. Losing Matter fabric state can
require sharing every device again.

## Onboarding and sharing a light

1. Open `http://192.168.30.124:8123` and create the Home Assistant owner
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

Kasa can remain installed for energy tracking, and AiDot for firmware
updates. Home Assistant joins its own Matter fabric without replacing
Apple Home. Matter support for energy metrics depends on device firmware;
do not assume every Kasa metric is exposed through Matter.

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

The Home Assistant UI listens only on the LXC's LAN IPv4 address. Matter's
unauthenticated management API listens only on guest loopback and is reachable
by Home Assistant because both containers use host networking. No WAN
forwarding, Caddy route or Tailscale sidecar is configured.

## Checks

```bash
cd /docker/homeassistant
docker compose ps
curl --fail http://192.168.30.124:8123/
docker inspect --format '{{.State.Health.Status}}' matter-server
```

After onboarding, confirm the Matter integration connects and the first
device remains controllable from both Home Assistant and Apple Home.
Container readiness alone does not verify pairing.

References:

- [Home Assistant Container installation](https://www.home-assistant.io/installation/linux/)
- [Home Assistant Matter integration and multi-admin sharing](https://www.home-assistant.io/integrations/matter/)
- [Matter.js Docker configuration](https://github.com/matter-js/matterjs-server/blob/main/docs/docker.md)
