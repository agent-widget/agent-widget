# 11-OTA 通知通道 — MQTT 推送 + HTTPS 下载

> 日期：2026-08-30
> 状态：设计提案（待实现，阻塞于 AW-004 MQTT broker）
> 范围：固件更新通知如何送达设备，以及如何控制单设备/分批/灰度升级。

---

## 1. 动机

当前 OTA 客户端（`ota-sim/sketch_gh_ota.ino`）靠**定时轮询** GitHub 发现更新（默认每 1 小时）。轮询有两个结构性局限：

1. 所有设备看到的是同一份「最新版」——无法让部分设备暂不升级。
2. 升级时机受轮询间隔约束——无法即时推送。

本文定义一个基于 MQTT 的**推送**通道，让设备管理方能：

- 决定**哪些设备**升级、哪些不升级。
- 做**分批 / 金丝雀（canary）灰度**（按百分比、按命名分组、按单设备）。
- **即时**触发升级，不用等下一轮轮询。

---

## 2. 通道分工：MQTT 传元数据，HTTPS 传固件

常见误区是把固件字节经 MQTT 推送。我们**不这么做**：

```
MQTT   →  小体积 JSON 通知（version、url、sha256、signature、min_version）
HTTPS  →  实际的 ~1MB 固件二进制，来自 GitHub Releases（或 raw CDN）
```

原因：MQTT 消息应保持小（broker + RAM 友好）；固件已经通过现有的 GitHub Releases +
`esp_https_ota` 路径分发并做 sha256 + RSA 签名完整性校验。MQTT 只增加「触发器」这一环。

通知负载复用了 `firmware/manifest.json` 里已有的元数据，因此设备现有的
下载 → 校验 → 写 flash → 自检 → 回滚 管道完全不变。

---

## 3. Topic 约定

| Topic | 用途 |
|---|---|
| `ota/announce` | 广播：所有设备都考虑升级到通告版本 |
| `ota/{deviceId}` | 定向：某一台设备 |
| `ota/group/{group}` | 分批灰度：命名分组（如 `canary`、`stable`、`beta`） |

`{deviceId}` 是稳定的每设备标识（烧录或 MAC 派生的 id，与 `AgentStatus` 通道共用同一个）。
设备订阅 `ota/announce`、自己的 `ota/{deviceId}`，以及所属的 `ota/group/{group}`。
服务端向最精确描述目标受众的那个 topic 发布。

---

## 4. 消息 schema

```json
{
  "version": "3.1.0",
  "url": "https://github.com/agent-widget/agent-widget/releases/download/v3.1.0/firmware-v3.1.0.bin",
  "sha256": "…64 hex…",
  "signature": "…base64 RSA-2048 PKCS#1v1.5（对固件 sha256 签名）…",
  "min_version": "2.0.0",
  "id": "ota-2026-08-30-a"
}
```

- `min_version`：设备当前版本低于它时拒绝升级（防误降级护栏）。
- `id`：可选通知 id，用于去重/诊断。
- 负载**与显示语言无关**（只有版本号和哈希；UI 用消息键渲染「发现更新」提示，
  与 `AgentStatus` 的状态码约定一致）。

投递语义：QoS 1；广播 topic 用 retained（后加入的设备仍能看到当前通告）；定向/分组 topic 非 retained。

---

## 5. 设备端流程（复用现有状态机）

```
收到 MQTT 消息（ota/announce | ota/{id} | ota/group/{g}）
  → 校验：version > 当前 且 当前 >= min_version
  → 在 UpdatePanel + 自检屏显示「发现更新」提示
  → 等待用户确认（触摸 / 按键）
  → HTTPS 下载 → sha256 → RSA 验签 → 写 flash → 重启 → 自检 → valid/回滚
```

设备端唯一新增的是**触发源**：订阅 MQTT topic，把收到的负载喂给轮询器已经使用的同一个
「发现新版本」入口。sha256 + 签名 + 回滚仍是最后防线——即使设备被错误定向，
也装不进无效固件。

---

## 6. 灰度策略（服务端策略）

| 策略 | 做法 |
|---|---|
| 暂缓 | 不向该设备的 topic 发布即可 |
| 金丝雀（按百分比）| 把 `deviceId` 哈希分桶，向选中的桶发布 `ota/group/canary-N` |
| 命名分组 | `ota/group/beta`、`ota/group/internal` 等 |
| 单设备 | `ota/{deviceId}` |
| 熔断 / 召回 | 发布 `ota/announce` 且 `min_version` 指向锁定的好版本，或发定向回退通知 |

---

## 7. 与轮询的关系（互补，非二选一）

- **MQTT 推送** = 主通道：即时、定向、灰度。
- **轮询（1h）** = 兜底：设备在消息发出时离线、broker 不可达、首次上电/重新配网，
  以及 MQTT 路径本身的安全网。
- 收到 MQTT 通知不会取消轮询；两者都喂给同一个 `check_update()` 入口。

---

## 8. Broker 复用（AW-004）

broker **不是**新基础设施。AW-004 已计划为 `AgentStatus` 投递建一个 MQTT broker
（服务端发布 agent 状态，ESP32 订阅）。OTA 通知搭同一 broker、同一条设备连接，
只是 topic 前缀不同（`ota/` vs 状态 topic）。

实现顺序：

1. AW-004 落地 MQTT broker + 设备订阅 + `AgentStatus` 契约。
2. AW-006 增加 `ota/` topic、上面的通知 schema、设备端触发源粘合代码。
3. 服务端发布器（谁决定分组/百分比）是一个轻量服务或定时动作，
   读取 release 元数据后向目标 topic 发布。

---

## 9. 安全说明

- MQTT 通道与 `AgentStatus` 通道同样做认证 + TLS 加密。
- 通知本身**不**被当作完整性依据：固件仍按内置 RSA 公钥 + sha256 校验。
  伪造通知最多造成打扰，绝不 brick。
- `min_version` 防误降级推送。
- 生产签名密钥（RSA 私钥）留在发布侧（GitHub secret `OTA_SIGNING_KEY`），
  绝不进设备、也不进 MQTT。

---

## 10. 状态 / 后续

- 当前模拟（AW-006 PoC）已端到端实现**轮询**路径；MQTT 触发是 AW-004 之后预留的设计。
- 实现后，轮询保留为兜底通道。
