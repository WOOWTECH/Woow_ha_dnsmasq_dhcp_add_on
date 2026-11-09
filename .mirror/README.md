# Mirror operations

Files under `.mirror/` and the root GitHub Actions workflows are maintained by
WOOWTECH. The `dnsmasq-dhcp/` directory is replaced from upstream on every
successful mirror sync.

## Data flow

1. `mirror-sync.yml` fetches `f18m/ha-addon-dnsmasq-dhcp` branch `main`.
2. A snapshot of upstream's tree without `.github` is committed on top of the
   `upstream` branch (never force-pushed).
3. Upstream files are exported into `dnsmasq-dhcp/` on `main`.
4. `patch-image.py` rewrites the add-on image to the WoowTech GHCR namespace
   and records the source/destination pair in `image-map.json`.
5. `image-mirror.yml`, called by `mirror-sync` on the pushed commit (it has no
   schedule of its own), copies the versioned image and `latest` manifest with
   `skopeo --all`.
6. The Store's upgrade comparison compares a new version with the latest
   formal Release; only if it passes does the Store's Release workflow create
   the `v<version>` Release.
7. `WOOWTECH/Woow_HA_App_Store` imports `dnsmasq-dhcp/` from that Release.

## Release gating (pipeline #91)

`mirror-sync` runs sync → image copy (`image-mirror`) → the Store's upgrade
comparison → Release. If the comparison fails, the run fails, no Release is
created, and the step summary says which category failed and why. Optional
overlay files in `.mirror/dnsmasq-dhcp/` are copied into `dnsmasq-dhcp/` on
every rebuild: `upgrade-check/` (hooks, settings) and `upgrade-notes.yaml`
(declared breaking changes, with the migration). For an intended upstream
breaking change, add the declaration to `.mirror/dnsmasq-dhcp/upgrade-notes.yaml`,
commit it to `main`, and run `mirror-sync` by hand: it checks the same version
again and, when it passes, creates the Release with the declaration in its
notes.

## Upstream workflow safety

The upstream `Main CI` workflow is intentionally **disabled** in this mirror.
It is preserved unchanged on the audit branch, but pushing that branch must not
build or publish upstream-owned images from the WoowTech organization. Only the
root `mirror-sync` and `image-mirror` workflows are enabled.

## Manual verification

```bash
gh workflow run mirror-sync.yml -R WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on
gh workflow run image-mirror.yml -R WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on  # normally runs only inside mirror-sync
gh run list -R WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on --limit 5
```

If the upstream repository or registry disappears, the last synchronized code
and image remain available from WoowTech.
