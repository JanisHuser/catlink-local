# CATLINK Local — Home Assistant add-on repository

A local, cloud-free (or transparent-proxy) integration for **CATLINK** devices,
packaged as a Home Assistant add-on. It bundles a DNS redirect for
`*.catlinks.cn`, a proxy to the real cloud (so the vendor app keeps working),
and MQTT discovery so your devices show up as native HA entities — food-in-bowl,
feeding, and a feed button.

## Install (Add-on Store)

1. In Home Assistant: **Settings → Add-ons → Add-on Store**.
2. Top-right **⋮ → Repositories**, paste:

   ```
   https://github.com/JanisHuser/catlink-local
   ```

3. Close the dialog; **CATLINK Local** now appears in the store. Open it →
   **Install**.
4. Make sure the **Mosquitto broker** add-on is installed and the **MQTT**
   integration is set up, then **Start** CATLINK Local.
5. Point your router's (or the devices') DNS at your Home Assistant box.

Full configuration and troubleshooting: **[catlink_local/DOCS.md](catlink_local/DOCS.md)**.

> HACS can't install this — HACS is for custom *integrations*, cards, and
> themes. This is a Supervisor **add-on**, so it installs from the Add-on Store
> via the custom-repository step above.

## What's in here

```
repository.yaml          <- makes this a HA add-on repository
catlink_local/           <- the add-on
  config.yaml            <- add-on manifest
  Dockerfile, run.sh     <- builds/starts DNS (dnsmasq) + the server
  build.yaml
  DOCS.md                <- add-on documentation (shown in the UI)
  catlink_local/         <- the Python package (server, dashboard, devices, MQTT)
  tests/                 <- unit tests (protocol, feeder decode, MQTT bridge)
  tools/                 <- capture_proxy.py for reverse engineering
  README.md              <- developer/standalone docs
```

The add-on also runs standalone (outside HA) — see
[catlink_local/README.md](catlink_local/README.md).
