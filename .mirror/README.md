# Mirror operations

Files under `.mirror/` and the root GitHub Actions workflows are maintained by
WOOWTECH. The `dnsmasq-dhcp/` directory is replaced from upstream on every
successful mirror sync.

## Data flow

1. `mirror-sync.yml` fetches `f18m/ha-addon-dnsmasq-dhcp` branch `main`.
2. The exact upstream commit is force-updated onto the `upstream` branch.
3. Upstream files are exported into `dnsmasq-dhcp/` on `main`.
4. `patch-image.py` rewrites the add-on image to the WoowTech GHCR namespace
   and records the source/destination pair in `image-map.json`.
5. `image-mirror.yml` copies the versioned image and `latest` manifest with
   `skopeo --all`.
6. `WOOWTECH/Woow_HA_App_Store` imports `dnsmasq-dhcp/` during its daily sync.

## Upstream workflow safety

The upstream `Main CI` workflow is intentionally **disabled** in this mirror.
It is preserved unchanged on the audit branch, but pushing that branch must not
build or publish upstream-owned images from the WoowTech organization. Only the
root `mirror-sync` and `image-mirror` workflows are enabled.

## Manual verification

```bash
gh workflow run mirror-sync.yml -R WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on
gh workflow run image-mirror.yml -R WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on
gh run list -R WOOWTECH/Woow_ha_dnsmasq_dhcp_add_on --limit 5
```

If the upstream repository or registry disappears, the last synchronized code
and image remain available from WoowTech.
