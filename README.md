# WOOWTECH Dnsmasq-DHCP Add-on Mirror

This repository is a **defensive mirror** of
[`f18m/ha-addon-dnsmasq-dhcp`](https://github.com/f18m/ha-addon-dnsmasq-dhcp),
limited to the stable (`main`) channel. It is packaged as a Home Assistant
add-on repository and is also distributed through
[`WOOWTECH/Woow_HA_App_Store`](https://github.com/WOOWTECH/Woow_HA_App_Store).

Upstream functionality, name, UI, slug, and license are retained. Do not develop
against `main`: automated synchronization replaces the mirrored add-on files.

## Install

Add either repository URL to Home Assistant:

- Single add-on mirror: `https://github.com/WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on`
- Unified WoowTech store: `https://github.com/WOOWTECH/Woow_HA_App_Store`

In Home Assistant, open **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.

## Mirror layout

| Path / branch | Purpose |
|---|---|
| `dnsmasq-dhcp/` | Stable add-on source copied from upstream |
| `main` | HA repository plus WoowTech automation and GHCR image rewrite |
| `upstream` | Unmodified mirror of upstream `main` for audit and recovery |
| `.mirror/` | Mirror configuration, image mapping, and synchronization metadata |

## Automation

| Workflow | Schedule (UTC) | Purpose |
|---|---:|---|
| `mirror-sync` | daily at 03:17 | Sync source/tags, rebuild `main`, and rewrite the image URL |
| `image-mirror` | daily at 04:47 | Copy the current upstream image to WoowTech GHCR |

The add-on image is served from:

`ghcr.io/woowtech/ha-mirror-ghcr-io-f18m-addon-dnsmasq-dhcp`

The unified App Store performs its own daily sync from this repository.

## Attribution and license

Dnsmasq-DHCP is maintained upstream by Francesco Montorsi (`f18m`) and is
licensed under the MIT License. The complete upstream license is preserved at
[`dnsmasq-dhcp/LICENSE`](dnsmasq-dhcp/LICENSE).
