# agent-widget MQTT lab

A local MQTT test service that reproduces the **future production MQTT
environment** of the agent-widget project as closely as a single machine
allows. It is the test bed for [AW-004](../../docs.local/session/plan.md)
(`AgentStatus` v1 delivery over MQTT) and the OTA notification channel
([docs/ota/11-ota-notification-mqtt.md](../../docs/ota/11-ota-notification-mqtt.md)),
which ride the same broker.

Everything is reproducible and self-verifying: one command boots a fleet of
virtual devices and proves delivery, staged rollouts, offline queueing,
retained broadcasts, reconnect, and rollback.

> Status: local test infrastructure for the planned AW-004 work. The JSON
> schemas in `contracts/` are working drafts feeding AW-004, **not** the
> ratified protocol contract (that belongs in `protocols/` once AW-004 lands).

---

## 1. What the future environment looks like

```
 Agent / adapter ──HTTP API──▶ fleet server ──MQTT──▶ broker ──MQTT──▶ ESP32-S3 device
                                                    (TLS + auth)        (subscribes)
     OTA release ──GitHub Releases──▶ metadata ──MQTT──▶ ota/announce, ota/{deviceId},
                                    (version/url/sha256/signature/min_version)
                                    firmware binary stays on HTTPS
```

Production properties this lab reproduces:

| Property | Future environment | This lab |
|---|---|---|
| Broker | mosquitto-class broker | `eclipse-mosquitto:2` in Docker |
| TLS | listener with real CA | self-signed local CA on port 8883 (server-auth) |
| Auth | per-role / per-device credentials | `server` operator + one user per device (username == deviceId) |
| Authorization | topic ACLs (per-device cohort, generated) | `broker/state/acl.conf` from `acl.template.conf` + `gen-acl.sh` |
| Status contract | `AgentStatus` v1 (state codes, language-independent) | `contracts/agent-status-v1.schema.json`, validated on publish and receive |
| OTA trigger | metadata only over MQTT | `contracts/ota-announce-v1.schema.json` (same fields as the design doc) |
| Delivery | QoS 1, retained broadcast | QoS 1 everywhere; `ota/announce` retained, targeted/group non-retained |
| Offline behavior | persistent sessions queue QoS1 | persistent sessions (`clean_session=False`) + broker persistence |
| LWT | device offline telemetry | retained Last-Will on `device/{id}/telemetry` |
| Reconnect | backoff loop | automatic backoff reconnect |
| Rollout | canary / cohort / per-device / recall | `sims/ota_pub.py` implements all four |
| Rollback | self-test failure → rollback | `--fail-self-test` drill |

## 2. Quickstart

Requirements: Docker (daemon running), Python 3.10+, `openssl`, `nc`.

```bash
# 1. one-time setup (venv + paho-mqtt + jsonschema)
bash scripts/setup.sh

# 2. start the broker (generates TLS certs, provisions users, starts container)
bash scripts/start-broker.sh

# 3. run the self-verifying end-to-end scenario (≈90 s)
.venv/bin/python sims/demo.py
#    ... --fast for a shorter run

# 4. watch all traffic live (separate terminal)
.venv/bin/python sims/tail.py
```

Stop / reset:

```bash
bash scripts/stop-broker.sh      # stop, keep state
bash scripts/reset-broker.sh     # wipe users/sessions/queues entirely
bash scripts/add-device-user.sh esp32s3-cafebabe   # register a new device id
```

## 3. Manual exploration

```bash
# Publish an agent status (retained, so new devices see it immediately)
.venv/bin/python sims/server_pub.py --once --agents claude-01,deepseek-02

# Continuous status walk
.venv/bin/python sims/server_pub.py --loop --interval 5 --steps 40

# Run a virtual device (persistent session, LWT, reconnect)
.venv/bin/python sims/device.py --device-id esp32s3-a1b2c3
.venv/bin/python sims/device.py --device-id esp32s3-778899 --fail-self-test   # rollback drill
.venv/bin/python sims/device.py --device-id esp32s3-112233 --offline-start 15 # late joiner
.venv/bin/python sims/device.py --tls --ca broker/certs/ca.crt               # TLS path

# OTA rollouts (see sims/ota_pub.py --help)
.venv/bin/python sims/ota_pub.py --target broadcast --version 3.3.0
.venv/bin/python sims/ota_pub.py --target canary   --percent 40 --version 3.1.0
.venv/bin/python sims/ota_pub.py --target group    --group stable --version 3.1.0
.venv/bin/python sims/ota_pub.py --target device   --device-id esp32s3-112233 --version 3.2.0
# recall guards:
.venv/bin/python sims/ota_pub.py --target broadcast --version 3.0.0 --min-version 3.3.0
```

Any standard MQTT client can also join: `tcp://127.0.0.1:1883`,
`ssl://127.0.0.1:8883` (trust `broker/certs/ca.crt`), or
`ws://127.0.0.1:9001` for browser tools such as MQTTX.

## 4. Topics and payloads

| Topic | Direction | QoS / retained | Payload schema |
|---|---|---|---|
| `agents/{agentId}/status` | server → device | QoS1, retained | `agent-status-v1` |
| `ota/announce` | server → device | QoS1, retained | `ota-announce-v1` |
| `ota/{deviceId}` | server → device | QoS1 | `ota-announce-v1` |
| `ota/group/{group}` | server → device | QoS1 | `ota-announce-v1` |
| `device/{deviceId}/telemetry` | device → server | QoS1, retained | `device-telemetry-v1` |
| `device/{deviceId}/events` | device → server | QoS1 | `device-event-v1` |
| `device/{deviceId}/ota/result` | device → server | QoS1, retained | `device-ota-result-v1` |

Canary cohort: `hash(deviceId) % 5` → `canary-0..canary-4`. A device
subscribes to its own bucket plus the `stable` group; the operator publishes
to the `ceil(buckets × percent / 100)` lowest-numbered buckets covering the
desired percentage. Actual device coverage depends on the hash distribution
and is reported by `ota_pub.py`.

Credentials (LOCAL TEST ONLY — never reuse): the operator uses
`server` / `srv-dev-pass`; every device gets its OWN random secret, generated
by `scripts/start-broker.sh` and stored in `broker/state/device-creds.env`
(gitignored). The device sim reads its secret from there automatically.
Add a new device with `scripts/add-device-user.sh <deviceId> [extra-groups...]`.

Authorization: `scripts/gen-acl.sh` renders `broker/state/acl.conf` from
`broker/acl.template.conf` (global patterns: own-targeted OTA, own telemetry,
agent statuses, broadcast) plus one `user <deviceId>` block per device listing
exactly the cohort topics that device may subscribe to. Devices are NOT given
generic `ota/group/+` access — cohort membership is enumerated per device.

## 5. What `demo.py` verifies

1. fleet boots and reports online (telemetry + retained)
2. `AgentStatus` v1 statuses delivered and rendered (retained, language-independent)
3. canary rollout: only the hashed-bucket devices upgrade
4. group rollout (`stable`) upgrades the remaining fleet
5. offline device: broker fires LWT; a targeted announce is queued by the
   persistent session and installed on reconnect (SIGSTOP/SIGCONT injection)
6. retained broadcast: a late-joining device installs the announced version
   and renders the retained statuses; with a fresh session it misses
   non-retained canary/group/targeted (its own subscribed cohorts may queue
   legitimately via a persistent session)
7. recall guards: an older announce is rejected by EVERY device
   (anti-downgrade), an upgrade above a `min_version` wall is rejected by
   EVERY device (anti-rollback floor)
8. rollback drill: a device with failing self-test rolls back and keeps its
   firmware version
9. ACL negative probes: a device credential cannot write another device's
   telemetry or subscribe to another device's targeted/cohort topics

Exit code 0 = all checks passed. Device logs land in `logs/<deviceId>.log`.

`demo.py` starts by clearing the lab-owned retained topics (default agents +
fleet + the broadcast topic) with zero-length retained publishes, after the
collector's subscriptions are acked, so each run is judged against a fresh
broker state and never against leftovers.

Note on persistent sessions: a device that was online in an earlier run keeps
its persistent session on the broker, so QoS1 announces published to its own
cohort while it is offline may be queued and delivered on reconnect — that is
the intended offline-queueing behavior, not leakage. To start completely
clean (no queued messages from prior runs), run `bash scripts/reset-broker.sh`
then `bash scripts/start-broker.sh` before `demo.py`.

## 6. Layout

```
mqtt-lab/
├── broker/
│   ├── mosquitto.conf       # production-like broker config
│   ├── acl.template.conf   # ACL template; rendered per-device by gen-acl.sh
│   ├── docker-compose.yml   # eclipse-mosquitto container
│   └── scripts/gen-certs.sh # local CA + broker cert for 8883
├── contracts/               # JSON Schemas (drafts feeding AW-004)
├── sims/
│   ├── common.py            # topics, credentials, canary math, payloads
│   ├── device.py            # virtual ESP32-S3 device
│   ├── server_pub.py        # AgentStatus publisher
│   ├── ota_pub.py           # OTA rollout publisher
│   ├── tail.py              # traffic watcher
│   └── demo.py              # self-verifying end-to-end scenario
└── scripts/                 # setup / start / stop / reset / add-device
```

Generated artifacts (`broker/certs/`, `broker/state/`, `.venv/`, `logs/`) are
gitignored and stay local.

## 7. Limitations

- Devices are Python processes, not ESP32 firmware; timing is not
  representative of the real MCU.
- Certificates are a self-signed local CA (server-auth only, no client
  certs) — the same topology, not the same trust anchor, as production.
- `url`/`sha256`/`signature` in OTA announces are structurally valid
  placeholders; the firmware download is simulated (opt-in `--check-url`
  does a HEAD against the real GitHub URL).
- MQTT 3.1.1 Last Will is fixed at connect time: the LWT telemetry `version`
  can be stale after an OTA install. The retained online telemetry is always
  refreshed on install, so fleet-visible state stays correct; the LWT payload
  is only a crash signal.
- `mosquitto` does not bind client_id to the authenticated user by default;
  production should bind device identity to client ID (mutual TLS or an auth
  plugin) — the lab ACLs are username-based.
- This is local test infrastructure: the schemas here are inputs to AW-004,
  and AW-004 owns the ratified `AgentStatus` contract in `protocols/`.
