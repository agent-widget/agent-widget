# Device Registration and Device UUID Design

> Date: 2026-08-31
> Status: design proposal — user-approved on 2026-08-31; implementation gated on AW-004 (MQTT broker + AgentStatus transport)
> Scope: how a device obtains an immutable identity, registers itself to the MQTT broker after first boot, and how the fleet operator addresses and manages it afterwards.

---

## 1. Motivation

Every device in the fleet must be addressable so the operator can push targeted
messages to it (status subscriptions, OTA notifications, generic commands).
Two requirements shape this design:

1. **One firmware image for every device.** Flashing must not require a
   per-device build or per-device image; the factory and field workflows stay
   identical for all units.
2. **Immutable, manageable identity.** The operator must be able to locate a
   physical unit, address it, and track its lifecycle — which requires a
   stable device UUID that survives re-flashing, OTA, and even flash cloning.

The design that satisfies both is: **all devices flash the same image; the
device identity is derived from chip hardware and needs no per-unit flashing;
per-unit credentials are issued dynamically by a registration service at first
network boot.**

---

## 2. Identity model: three layers

| Layer | Content | Lifetime | Storage |
|---|---|---|---|
| **Device identity** | `UUID = aw-` + lowercase hex of the eFuse base MAC (e.g. `aw-f0f5bd7a91c3`) | Permanent, never changes | eFuse (MAC) + derived at runtime; not persisted to NVS |
| **Bootstrap credential** | Shared fleet bootstrap account + MAC allowlist admission | Used once at first registration | Firmware / shared NVS image |
| **Per-device credential** | Random secret issued by the registration service | Long-lived, rotatable | Device NVS (`device.credential`) |

Layers are deliberately separate: the identity answers **"who is this unit"**,
the bootstrap credential answers **"may this unit ask for a credential"**, and
the per-device credential is what the device actually authenticates with for
its operational lifetime.

---

## 3. Device UUID derivation

ESP32-S3 has no dedicated serial-number register. The hardware-level unique
identifier is the **base MAC burned into eFuse BLK0**:

```c
uint8_t mac[6];
esp_efuse_mac_get_default(mac);        // always returns the factory MAC
// or esp_read_mac(mac, ESP_MAC_BASE); // same value; be explicit about BASE
```

Why this is the right identity source:

- **Unique per chip**: every ESP32-S3 ships with a factory-burned unique base MAC.
- **Immutable**: stored in eFuse, not flash — survives re-flashing, OTA,
  factory reset, and even full-flash cloning (a cloned flash still has the
  target chip's own MAC, so clones never collide).
- **Zero provisioning**: the same firmware derives a different UUID on every
  board automatically; nothing per-unit is written at flash time.

MQTT representation: `UUID = "aw-" + lowercase-hex(base MAC)`, e.g.
`aw-f0f5bd7a91c3`. It is short, MQTT-topic-safe, and human-readable. The UUID
is used as the MQTT client ID, the per-device broker username, the
`{deviceId}` in topic names, and the registry primary key.

> Optional management convenience: an RFC 4122 **UUIDv5** (fixed namespace +
> MAC) can be derived for integration with management systems; it is
> deterministic from the same MAC and always consistent with the short form.

Rules:

- Always read `ESP_MAC_BASE` / `esp_efuse_mac_get_default`, never the
  interface default MAC (which could be overridden by MAC-override config).
- Do not use NVS-persisted random UUIDs as identity: they change on NVS wipe /
  flash replacement and duplicate under flash cloning.

---

## 4. Topics

Reuses and extends the mqtt-lab topic layout (see
`experiments/mqtt-lab/broker/mosquitto.conf`).

```
Device -> server
  device/{uuid}/register            QoS1, non-retained   registration request (incl. self-test)
  device/{uuid}/telemetry           QoS1, retained       online/heartbeat (existing)
  device/{uuid}/events              QoS1                 lifecycle log (existing)
  device/{uuid}/ota/result          QoS1, retained       last OTA outcome (existing)
Server -> device
  device/{uuid}/register/response   QoS1, one-shot      issued credential
  device/{uuid}/cmd                 QoS1                 generic commands (new: reboot/query)
  ota/{uuid}  ota/group/{g}  ota/announce               OTA notifications (existing, docs/ota/11)
```

---

## 5. Registration protocol

### 5.1 Request — `device/{uuid}/register`

```json
{
  "v": 1,
  "uuid": "aw-f0f5bd7a91c3",
  "fw": "3.1.0",
  "hw": "esp32s3-waveshare-3.5b",
  "selfTest": {
    "display": true,
    "touch": true,
    "wifi": true,
    "otaTask": true,
    "ts": 1780000000
  },
  "ts": 1780000000
}
```

- `selfTest` carries the result of the boot-time health check
  (`boot_health`): display, touch, Wi-Fi, and the OTA transport task.
  A failing self-test means the device is not healthy enough to be a
  registered fleet member.

### 5.2 Response — `device/{uuid}/register/response`

```json
{ "v": 1, "uuid": "aw-f0f5bd7a91c3", "ok": true,
  "credential": "<random per-device secret>", "expires": 0, "ts": 1780000000 }
```

Failure responses:

| Condition | Response |
|---|---|
| Self-test failed | `ok:false, reason:"self_test_failed"` — no credential issued; device retries with exponential backoff |
| UUID not in MAC allowlist | `ok:false, reason:"not_allowlisted"` — no credential issued |
| UUID already registered (re-registration) | re-issue with a fresh credential (rotation) and record in the audit log |

Delivery semantics: QoS1. The device subscribes to
`device/{uuid}/register/response` before publishing the request and keeps a
persistent session, so the response is not lost if the link drops mid-flow.

---

## 6. Device-side flow (firmware)

```
Power on -> read eFuse base MAC -> derive UUID -> init (boot_health self-test)
  |- no per-device credential (NVS empty):
  |      connect with bootstrap identity (client_id = UUID)
  |      publish device/{uuid}/register (incl. self-test)
  |      await device/{uuid}/register/response
  |      store credential in NVS -> reconnect with per-device identity
  '- has per-device credential: connect directly with per-device identity

After every connect: publish retained device/{uuid}/telemetry (online/heartbeat)
```

- The UUID itself is never stored: it is re-derived from eFuse at every boot.
- Only the issued credential is persisted (NVS key `device.credential`), and
  OTA never touches it.
- Registration retries use bounded exponential backoff; a failed self-test is
  retried after a backoff, not treated as a hard brick.

---

## 7. Registration service

1. Subscribes to `device/+/register`; validates `uuid` against the **MAC
   allowlist** and the self-test result.
2. Creates a per-device broker user (username == UUID) with a random secret and
   per-device ACL — the same contract the mqtt-lab provisions via
   `scripts/add-device-user.sh`, now invoked dynamically by the service.
3. Publishes the credential on `device/{uuid}/register/response`.
4. Revokes the bootstrap channel for that UUID (the bootstrap account must no
   longer be able to register it again).
5. Maintains the **fleet registry** (see §8) and an audit log of registrations,
   re-registrations, and rotations.

The service is deliberately thin: it only validates, issues, and records. It
does not touch firmware download, OTA policy, or status rendering.

---

## 8. Fleet registry (server-side inventory)

| Field | Example |
|---|---|
| uuid | `aw-f0f5bd7a91c3` |
| mac | `f0:f5:bd:7a:91:c3` |
| credential hash | sha256 of the issued secret (never store the plaintext) |
| fw | `3.1.0` |
| group / batch | `stable`, `canary-2` (from UUID hash bucket) |
| last online | ISO timestamp |
| last self-test | result + ts |
| registered at / rotated at | ISO timestamps |

This registry is what makes devices "locatable and manageable": the operator
lists devices, sees online state from retained telemetry, targets a single
unit or a cohort, and audits credential lifecycle.

---

## 9. Security boundary

- **Bootstrap phase is a weak secret by design**: the base MAC is visible in
  Wi-Fi frames and is not a secret. Admission control comes from the operator
  knowing the allowlist. This is acceptable because the bootstrap credential is
  single-use: after registration the device switches to a strong per-device
  secret, and the bootstrap channel is revoked.
- Per-device credentials are stored in NVS; before Flash Encryption is enabled
  they are plaintext in flash — a recorded, accepted risk for this stage
  (governed by the future Secure Boot / Flash Encryption plan).
- All MQTT traffic uses TLS (reusing the mqtt-lab 8883 path).
- Credential rotation = service re-issues + device re-stores; the old secret is
  invalidated at the broker and recorded in the audit log.
- The broker must not accept a client whose client_id/username pair is
  inconsistent with its ACL (mosquitto does not bind client_id by default; the
  production broker needs the mTLS/plugin hardening noted in the mqtt-lab
  lessons).

---

## 10. Scale-out (500 units)

Flashing and credentialing are decoupled so neither becomes a bottleneck:

1. **One image for all units**: `esptool merge_bin` combines bootloader +
   partition table + app + shared NVS into a single `fleet-all.bin`; every unit
   flashes the identical file (parallel USB hubs / `xargs -P`), then
   `verify_flash` validates the write.
2. **MAC captured during flashing**: right after `write_flash` the device is
   still in download mode — `esptool read_mac` returns the base MAC, and the
   flash script appends `uuid,mac,timestamp` to the allowlist CSV. Flashing
   500 units produces a 500-row allowlist with zero manual transcription.
   Optional: print a QR label (containing the UUID) to attach to the enclosure.
3. **Credentials are issued at runtime**: the registration service loads the
   allowlist CSV, so per-unit secrets never participate in flashing.
4. **Controlled admission**: the service can admit batches/cohorts gradually
   and audit repeated registration attempts.

Estimated first-flash time: ~10–20 s per unit over native USB at 921600 baud
(~1.5–2 MB total), so a 10-port hub completes 500 units in well under an hour
including manual insertion/removal. Exact numbers must be measured on real
hardware during AW-002/003.

> **SD-card flashing was considered and rejected.** ESP32 ROM cannot boot from
> SD, so SD-based "insert card, power on, auto-flash" only works for boards
> that already have a bootstrap firmware — which is exactly the population
> that can be OTA-updated instead. Since first flashing is fast and parallel
> and everything after it is OTA, the SD path adds no value. (The 3.5B board
> does have a TF slot; it stays available for future storage needs.)

---

## 11. Relation to existing assets

| Asset | Relationship |
|---|---|
| **AW-004** (MQTT broker + AgentStatus) | Registration rides the same broker and connection; no new infrastructure |
| **mqtt-lab** (`experiments/mqtt-lab/`) | `add-device-user.sh` evolves from manual provisioning to dynamic issuance by the registration service; schemas graduate from `contracts/` to `protocols/` |
| **boot_health** (firmware) | Self-test results are reported inside the registration request; failure blocks registration |
| **docs/ota/11** (MQTT OTA notification) | `deviceId` is finalized as this design's UUID; `ota/{uuid}` and `ota/group/{g}` address devices directly |
| **docs/ota/02 / 04** | OTA remains the only update channel after first flash; registration adds no update path |

---

## 12. Status / follow-up

- Decisions confirmed by the user on 2026-08-31: single-image flashing, MAC
  allowlist bootstrap, dynamic per-device credential issuance, UUID from eFuse
  base MAC, no SD-card upgrade path.
- Implementation is blocked on AW-004 (broker + AgentStatus in firmware).
  When AW-004 lands: add the registration client state machine to the firmware
  MQTT task, graduate the schemas into `protocols/`, and implement the
  registration service against the mqtt-lab broker first, then against the
  production broker.
- Firmware behavior and schema versions (v1 above) are ratified at AW-004.
