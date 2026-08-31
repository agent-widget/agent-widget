# 11-OTA notification channel — MQTT push + HTTPS download

> Date: 2026-08-30
> Status: design proposal (pending implementation — blocked on AW-004 MQTT broker)
> Scope: how firmware-update notifications are delivered to devices, and how per-device / staged rollout is controlled.

---

## 1. Motivation

The current OTA client (`ota-sim/sketch_gh_ota.ino`) discovers updates by **polling** GitHub on a timer
(default every 1 hour). Polling has two structural limits:

1. Every device sees the same "latest" version — there is no way to hold some devices back.
2. Update timing is bounded by the poll interval — no immediate push.

This document defines a **push** channel over MQTT so that the fleet operator can:

- Decide **which devices** upgrade and which do not.
- Run **staged / canary rollouts** (a percentage, a named group, a specific device).
- Trigger an update **immediately**, without waiting for the next poll.

---

## 2. Channel split: MQTT carries metadata, HTTPS carries firmware

A common mistake is to push firmware bytes over MQTT. We do **not**:

```
MQTT   →  small JSON notification (version, url, sha256, signature, min_version)
HTTPS  →  the actual ~1 MB firmware binary, from GitHub Releases (or raw CDN)
```

Reasons: MQTT messages should stay small (broker + RAM friendly); firmware is already
distributed and verified through the existing GitHub Releases + `esp_https_ota` path with
sha256 + RSA signature integrity checks. MQTT only adds the *trigger*.

The notification payload reuses the exact metadata already in `firmware/manifest.json`, so the
device's existing download → verify → flash → self-test → rollback pipeline is unchanged.

---

## 3. Topics

| Topic | Purpose |
|---|---|
| `ota/announce` | Broadcast: all devices consider upgrading to the announced version |
| `ota/{deviceId}` | Targeted: one specific device |
| `ota/group/{group}` | Staged rollout: a named cohort (e.g. `canary`, `stable`, `beta`) |

`{deviceId}` is a stable per-device identifier (a burned-in or MAC-derived id, same one used by the
`AgentStatus` channel). Devices subscribe to `ota/announce`, their own `ota/{deviceId}`, and any
`ota/group/{group}` they belong to. The operator's server publishes to the narrowest topic that
describes the intended audience.

---

## 4. Message schema

```json
{
  "version": "3.1.0",
  "url": "https://github.com/agent-widget/agent-widget/releases/download/v3.1.0/firmware-v3.1.0.bin",
  "sha256": "…64 hex…",
  "signature": "…base64 RSA-2048 PKCS#1v1.5 over the firmware sha256…",
  "min_version": "2.0.0",
  "id": "ota-2026-08-30-a"
}
```

- `min_version`: device refuses the update if its current version is below this (anti-rollback guard).
- `id`: optional notification id for dedupe / diagnostics.
- Payload is **display-language independent** (version numbers and hashes only; the UI renders the
  "update available" prompt from a message key, matching the `AgentStatus` state-code convention).

Delivery semantics: QoS 1, retained for the *broadcast* topic (so a device that joins late still
sees the current announcement); non-retained for targeted/group topics.

---

## 5. Device-side flow (reuses the existing state machine)

```
MQTT message received (ota/announce | ota/{id} | ota/group/{g})
  → validate: version > current AND current >= min_version
  → show "update available" prompt on the UpdatePanel + self-test screen
  → wait for user confirmation (touch / key)
  → download over HTTPS → sha256 → RSA verify → flash → reboot → self-test → valid/rollback
```

The only new code on the device is the **trigger source**: subscribing to MQTT topics and feeding
the received payload into the same "discover new version" entry point that the poller already uses.
sha256 + signature + rollback remain the last line of defense — even if a device is mis-targeted,
it cannot install an invalid binary.

---

## 6. Rollout strategies (server-side policy)

| Strategy | How |
|---|---|
| Hold-back | simply do not publish to that device's topics |
| Canary (percentage) | hash `deviceId` into buckets, publish to `ota/group/canary-N` for the chosen bucket |
| Named cohort | `ota/group/beta`, `ota/group/internal`, etc. |
| Per-device | `ota/{deviceId}` |
| Kill-switch / recall | publish `ota/announce` with `min_version` that matches the pinned good version, or a targeted rollback notice |

---

## 7. Relationship to polling (complementary, not either/or)

- **MQTT push** = primary, immediate, targeted, staged.
- **Poll (1 h)** = fallback for: device offline when the message was sent, broker unreachable,
  first boot / re-provisioning, and a safety net for the MQTT path itself.
- A received MQTT notification does not cancel the poll; both feed the same `check_update()` entry point.

---

## 8. Broker reuse (AW-004)

The broker is **not** new infrastructure. AW-004 already plans an MQTT broker for `AgentStatus`
delivery (server publishes agent status, the ESP32 subscribes). OTA notifications ride the same
broker and the same device connection, differing only in topic prefix (`ota/` vs the status topic).

Implementation ordering:

1. AW-004 lands the MQTT broker + device subscription + `AgentStatus` contract.
2. AW-006 adds the `ota/` topics, the notification schema above, and the device trigger-source glue.
3. The server-side publisher (who decides cohorts/percentages) is a thin service or a scheduled
   action that reads the release metadata and publishes to the intended topics.

---

## 9. Security notes

- The MQTT channel authenticates and TLS-encrypts the same as the `AgentStatus` channel.
- The notification itself is **not** trusted for integrity: the firmware is still verified against
  the embedded RSA public key and its sha256. A forged notification can at most annoy, never brick.
- `min_version` guards against accidental downgrade pushes.
- Production signing keys (the RSA private key) remain on the release side (GitHub secret
  `OTA_SIGNING_KEY`), never on devices or in MQTT.

---

## 10. Status / follow-up

- Current simulation (AW-006 PoC) implements the **polling** path end-to-end; the MQTT trigger is a
  design reserved for after AW-004.
- When implemented, the poll stays as the fallback channel.
