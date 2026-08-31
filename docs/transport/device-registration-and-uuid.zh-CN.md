# 设备注册与设备 UUID 设计

> 日期: 2026-08-31
> 状态: 设计提案 — 2026-08-31 用户确认;实现阻塞于 AW-004(MQTT broker + AgentStatus 传输)
> 范围: 设备如何获得不可变身份、首次联网后如何注册到 MQTT broker,以及运营者之后如何定位和管理设备。

---

## 1. 动机

机群中的每台设备都必须可寻址,运营者才能向它推送定向消息(状态订阅、OTA 通知、通用指令)。两个需求决定了本设计:

1. **每台设备刷同一份固件。** 烧录不得要求逐台构建或逐台镜像;出厂与现场流程对所有设备保持一致。
2. **身份不可变且可管理。** 运营者必须能定位物理设备、寻址、跟踪生命周期——这需要一个稳定的设备 UUID,它在重刷、OTA、甚至整片 flash 克隆后都不变。

同时满足两者的设计是:**所有设备烧录同一镜像;设备身份从芯片硬件派生,无需逐台烧写;每台专属凭据由注册服务在首次联网时动态签发。**

---

## 2. 身份模型:三层分离

| 层 | 内容 | 生命周期 | 存储 |
|---|---|---|---|
| **设备身份** | `UUID = aw-` + eFuse base MAC 小写 hex(如 `aw-f0f5bd7a91c3`) | 永久,永不变 | eFuse(MAC)+ 运行时派生;不落 NVS |
| **引导凭据** | 共享 fleet 引导账户 + MAC 白名单准入 | 首次注册用一次 | 固件 / 共享 NVS 镜像 |
| **专属凭据** | 注册服务签发的随机密钥 | 长期,可轮换 | 设备 NVS(`device.credential`) |

三层刻意分离:身份回答**"这是哪台设备"**,引导凭据回答**"这台设备可以申请凭据吗"**,专属凭据才是设备运营期内实际认证用的。

---

## 3. 设备 UUID 派生

ESP32-S3 没有独立的序列号寄存器。硬件级唯一标识是**烧死在 eFuse BLK0 的 base MAC**:

```c
uint8_t mac[6];
esp_efuse_mac_get_default(mac);        // 始终返回出厂 MAC
// 或 esp_read_mac(mac, ESP_MAC_BASE); // 同一值;务必显式用 BASE
```

为什么这是正确的身份来源:

- **每颗芯片唯一**:每颗 ESP32-S3 出厂都烧有唯一的 base MAC。
- **不可变**:存在 eFuse 而非 flash——重刷、OTA、恢复出厂、甚至整片 flash 克隆都不变(克隆的 flash 仍然只有目标芯片自己的 MAC,克隆永不冲突)。
- **零预置**:同一份固件在每块板上自动派生出不同 UUID;烧录时无需写入任何逐台数据。

MQTT 表示:`UUID = "aw-" + base MAC 小写 hex`,如 `aw-f0f5bd7a91c3`。短、MQTT 主题安全、人类可读。该 UUID 用作 MQTT client ID、每设备 broker 用户名、主题中的 `{deviceId}` 以及注册表主键。

> 可选的管理便利:可按 RFC 4122 **UUIDv5**(固定 namespace + MAC)派生标准 UUID 用于对接管理系统;它与 MAC 同源、确定一致。

规则:

- 始终读 `ESP_MAC_BASE` / `esp_efuse_mac_get_default`,绝不用接口的 default MAC(可能被 MAC override 配置改动)。
- 不要用 NVS 持久化的随机 UUID 作为身份:它会在 NVS 擦除/换 flash 后改变,并在 flash 克隆时重复。

---

## 4. 主题

复用并扩展 mqtt-lab 的主题布局(见 `experiments/mqtt-lab/broker/mosquitto.conf`)。

```
设备 → 服务
  device/{uuid}/register            QoS1, 非 retained   注册请求(含自检)
  device/{uuid}/telemetry           QoS1, retained      在线/心跳(已有)
  device/{uuid}/events              QoS1                生命周期日志(已有)
  device/{uuid}/ota/result          QoS1, retained      最近 OTA 结果(已有)
服务 → 设备
  device/{uuid}/register/response   QoS1, 一次性        签发的凭据
  device/{uuid}/cmd                 QoS1                通用指令(新增:reboot/query)
  ota/{uuid}  ota/group/{g}  ota/announce               OTA 通知(已有,docs/ota/11)
```

---

## 5. 注册协议

### 5.1 请求 — `device/{uuid}/register`

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

- `selfTest` 携带开机自检(`boot_health`)结果:显示、触摸、Wi-Fi、OTA 传输任务。自检失败意味着设备状态不足以保证注册为机群成员。

### 5.2 响应 — `device/{uuid}/register/response`

```json
{ "v": 1, "uuid": "aw-f0f5bd7a91c3", "ok": true,
  "credential": "<随机专属密钥>", "expires": 0, "ts": 1780000000 }
```

失败响应:

| 条件 | 响应 |
|---|---|
| 自检失败 | `ok:false, reason:"self_test_failed"` — 不签发凭据;设备指数退避重试 |
| UUID 不在 MAC 白名单 | `ok:false, reason:"not_allowlisted"` — 不签发凭据 |
| UUID 已注册(重新注册) | 重新签发新凭据(轮换)并记录审计日志 |

投递语义:QoS1。设备在发布请求**之前**订阅 `device/{uuid}/register/response` 并保持持久会话,链路中途断开也不会丢响应。

---

## 6. 设备端流程(固件)

```
上电 -> 读 eFuse base MAC -> 派生 UUID -> 初始化(boot_health 自检)
  |- 无专属凭据(NVS 空):
  |      以引导身份连接(client_id = UUID)
  |      发布 device/{uuid}/register(含自检)
  |      等待 device/{uuid}/register/response
  |      凭据存 NVS -> 以专属身份重连
  '- 已有专属凭据:直接以专属身份连接

每次连接后:发布 retained device/{uuid}/telemetry(在线/心跳)
```

- UUID 本身从不存储:每次开机都从 eFuse 重新派生。
- 只有签发的凭据被持久化(NVS 键 `device.credential`),OTA 永不触碰。
- 注册重试采用有界指数退避;自检失败按退避重试,不视为硬损坏。

---

## 7. 注册服务

1. 订阅 `device/+/register`;对照 **MAC 白名单** 与自检结果校验 `uuid`。
2. 创建每设备 broker 用户(用户名 == UUID),配随机密钥与按设备 ACL——与 mqtt-lab 用 `scripts/add-device-user.sh` 预置的契约相同,现在由服务动态调用。
3. 在 `device/{uuid}/register/response` 上回发凭据。
4. 吊销该 UUID 的引导通道(引导账户不得再为其注册)。
5. 维护 **fleet 注册表**(见 §8)与注册/重注册/轮换的审计日志。

服务刻意保持轻薄:只做校验、签发、记录。不涉及固件下载、OTA 策略或状态渲染。

---

## 8. Fleet 注册表(服务端库存)

| 字段 | 示例 |
|---|---|
| uuid | `aw-f0f5bd7a91c3` |
| mac | `f0:f5:bd:7a:91:c3` |
| 凭据哈希 | 签发密钥的 sha256(绝不存明文) |
| fw | `3.1.0` |
| group / batch | `stable`、`canary-2`(由 UUID 哈希桶) |
| last online | ISO 时间戳 |
| last self-test | 结果 + 时间戳 |
| registered at / rotated at | ISO 时间戳 |

注册表正是设备"可定位、可管理"的载体:运营者列出设备、从 retained 遥测看到在线状态、定向到单台或队列、审计凭据生命周期。

---

## 9. 安全边界

- **引导阶段按设计是弱秘密**:base MAC 在 Wi-Fi 帧中可见,不是秘密。准入控制来自运营者掌握白名单。这可以接受,因为引导凭据一次性使用:注册后设备切换到强专属密钥,引导通道随即吊销。
- 专属凭据存于 NVS;在启用 Flash Encryption 前是 flash 明文——本阶段记录在案、接受的风险(由未来的 Secure Boot / Flash Encryption 方案治理)。
- 所有 MQTT 流量走 TLS(复用 mqtt-lab 8883 通道)。
- 凭据轮换 = 服务重签 + 设备重存;旧密钥在 broker 失效并记入审计。
- broker 不得接受 client_id/username 与其 ACL 不一致的连接(mosquitto 默认不绑 client_id;生产 broker 需要 mqtt-lab 教训中提到的 mTLS/插件加固)。

---

## 10. 规模化(500 台)

烧录与发证解耦,两者都不会成为瓶颈:

1. **全设备同一镜像**:`esptool merge_bin` 将 bootloader + 分区表 + app + 共享 NVS 合成单个 `fleet-all.bin`;每台设备烧录完全相同的文件(多 USB hub 并行 / `xargs -P`),随后 `verify_flash` 校验写入。
2. **烧录时顺带采集 MAC**:`write_flash` 之后设备仍在下载模式——`esptool read_mac` 直接返回 base MAC,烧录脚本将 `uuid,mac,timestamp` 追加进白名单 CSV。烧完 500 台,白名单也正好 500 行,零人工抄录。可选:打印含 UUID 的二维码标签贴到外壳。
3. **凭据在运行时签发**:注册服务加载白名单 CSV,专属密钥完全不参与烧录。
4. **准入可控**:服务可按批次/队列灰度放行,并审计重复注册尝试。

首烧时间估算:~10–20 秒/台(原生 USB 921600 波特,总计 ~1.5–2 MB),10 口 hub 烧完 500 台(含人工插拔)远小于 1 小时。精确数字须在 AW-002/003 真机实测。

> **SD 卡烧录方案已评估并否决。** ESP32 ROM 不能从 SD 启动,所以"插卡、插电、自动烧录"只对已烧过引导固件的板子成立——而这类板子本来就能 OTA 更新。既然首烧快速且可并行、之后全部走 OTA,SD 路径没有价值。(3.5B 板确实有 TF 槽;保留给未来存储需求。)

---

## 11. 与现有资产的衔接

| 资产 | 关系 |
|---|---|
| **AW-004**(MQTT broker + AgentStatus) | 注册复用同一 broker 与连接;无新增基础设施 |
| **mqtt-lab**(`experiments/mqtt-lab/`) | `add-device-user.sh` 从手工预置演进为注册服务动态签发;schema 从 `contracts/` 毕业到 `protocols/` |
| **boot_health**(固件) | 自检结果随注册请求上报;失败阻止注册 |
| **docs/ota/11**(MQTT OTA 通知) | `deviceId` 定案为本设计的 UUID;`ota/{uuid}` 与 `ota/group/{g}` 直接寻址设备 |
| **docs/ota/02 / 04** | 首烧后 OTA 是唯一更新通道;注册不新增更新路径 |

---

## 12. 状态 / 后续

- 2026-08-31 用户确认的决策:单镜像烧录、MAC 白名单引导、专属凭据动态签发、UUID 取自 eFuse base MAC、不做 SD 卡升级路径。
- 实现阻塞于 AW-004(broker + 固件内 AgentStatus)。AW-004 落地后:在固件 MQTT 任务中加入注册客户端状态机,schema 毕业到 `protocols/`,先针对 mqtt-lab broker、再针对生产 broker 实现注册服务。
- 固件行为与 schema 版本(上面的 v1)在 AW-004 定案。
