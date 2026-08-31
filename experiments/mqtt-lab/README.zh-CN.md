# agent-widget MQTT 实验室（本地测试服务）

在单台机器上尽可能复刻 agent-widget **未来生产 MQTT 环境**的本地测试服务，
为 [AW-004](../../docs.local/session/plan.md)（`AgentStatus` v1 经 MQTT 投递到设备）
与 OTA 通知通道（[docs/ota/11](../../docs/ota/11-ota-notification-mqtt.md)，复用同一
broker）提供测试床。

一条命令即可拉起一队虚拟设备，自证消息投递、灰度发布、离线补投、retained 广播、
重连与回滚等行为。

> 状态：面向 AW-004 的本地测试基础设施。`contracts/` 下的 JSON Schema 是
> 供给 AW-004 的工作草案，**不是**正式协议契约（正式契约在 AW-004 落地后
> 归入 `protocols/`）。

---

## 1. 未来环境长什么样

```
 Agent / 适配器 ──HTTP API──▶ 服务器 ──MQTT──▶ broker ──MQTT──▶ ESP32-S3 设备
                                            (TLS + 认证)         (订阅)
      OTA 发布 ──GitHub Releases──▶ 元数据 ──MQTT──▶ ota/announce、ota/{deviceId}、
                                    (version/url/sha256/signature/min_version)
                                    固件二进制仍走 HTTPS
```

本实验室复现的生产特性：

| 特性 | 未来环境 | 本实验室 |
|---|---|---|
| Broker | mosquitto 同类 | Docker 中 `eclipse-mosquitto:2` |
| TLS | 真实 CA 的监听器 | 8883 端口本地自签 CA（仅服务端认证） |
| 认证 | 按角色 / 按设备凭证 | `server` 操作员 + 每设备一个用户（用户名 == deviceId） |
| 授权 | topic ACL（按设备分组、生成式） | `broker/state/acl.conf`（由 `acl.template.conf` + `gen-acl.sh` 生成） |
| 状态契约 | `AgentStatus` v1（状态码、语言无关） | `contracts/agent-status-v1.schema.json`，发布与接收两侧校验 |
| OTA 触发 | MQTT 只传元数据 | `contracts/ota-announce-v1.schema.json`（与设计文档字段一致） |
| 投递 | QoS1，广播 retained | 全 QoS1；`ota/announce` retained，定向/分组不 retained |
| 离线行为 | 持久会话补投 QoS1 | 持久会话（`clean_session=False`）+ broker 持久化 |
| LWT | 设备离线遥测 | `device/{id}/telemetry` 上的 retained 遗嘱消息 |
| 重连 | 退避重连 | 自动退避重连 |
| 发布策略 | canary / 分组 / 单设备 / 召回 | `sims/ota_pub.py` 四种全实现 |
| 回滚 | 自检失败回滚 | `--fail-self-test` 演练 |

## 2. 快速开始

前置：Docker（daemon 运行中）、Python 3.10+、`openssl`、`nc`。

```bash
# 1. 一次性初始化（venv + paho-mqtt + jsonschema）
bash scripts/setup.sh

# 2. 启动 broker（生成 TLS 证书、预置用户、起容器）
bash scripts/start-broker.sh

# 3. 跑自验证端到端场景（约 90 秒）
.venv/bin/python sims/demo.py
#    ... 加 --fast 可缩短

# 4. 实时看全量流量（另开终端）
.venv/bin/python sims/tail.py
```

停止 / 重置：

```bash
bash scripts/stop-broker.sh      # 停止，保留状态
bash scripts/reset-broker.sh     # 完全清空用户/会话/队列
bash scripts/add-device-user.sh esp32s3-cafebabe   # 注册新设备 id
```

## 3. 手动探索

```bash
# 发布一条 agent 状态（retained，新设备连上立即可见）
.venv/bin/python sims/server_pub.py --once --agents claude-01,deepseek-02

# 连续状态游走
.venv/bin/python sims/server_pub.py --loop --interval 5 --steps 40

# 跑一台虚拟设备（持久会话、LWT、重连）
.venv/bin/python sims/device.py --device-id esp32s3-a1b2c3
.venv/bin/python sims/device.py --device-id esp32s3-778899 --fail-self-test   # 回滚演练
.venv/bin/python sims/device.py --device-id esp32s3-112233 --offline-start 15 # 迟到加入者
.venv/bin/python sims/device.py --tls --ca broker/certs/ca.crt               # TLS 通道

# OTA 发布策略（详见 sims/ota_pub.py --help）
.venv/bin/python sims/ota_pub.py --target broadcast --version 3.3.0
.venv/bin/python sims/ota_pub.py --target canary   --percent 40 --version 3.1.0
.venv/bin/python sims/ota_pub.py --target group    --group stable --version 3.1.0
.venv/bin/python sims/ota_pub.py --target device   --device-id esp32s3-112233 --version 3.2.0
# 召回防护：
.venv/bin/python sims/ota_pub.py --target broadcast --version 3.0.0 --min-version 3.3.0
```

任意标准 MQTT 客户端也可接入：`tcp://127.0.0.1:1883`、
`ssl://127.0.0.1:8883`（信任 `broker/certs/ca.crt`）或 `ws://127.0.0.1:9001`
（浏览器工具如 MQTTX）。

## 4. Topic 与载荷

| Topic | 方向 | QoS / retained | 载荷 schema |
|---|---|---|---|
| `agents/{agentId}/status` | 服务器 → 设备 | QoS1, retained | `agent-status-v1` |
| `ota/announce` | 服务器 → 设备 | QoS1, retained | `ota-announce-v1` |
| `ota/{deviceId}` | 服务器 → 设备 | QoS1 | `ota-announce-v1` |
| `ota/group/{group}` | 服务器 → 设备 | QoS1 | `ota-announce-v1` |
| `device/{deviceId}/telemetry` | 设备 → 服务器 | QoS1, retained | `device-telemetry-v1` |
| `device/{deviceId}/events` | 设备 → 服务器 | QoS1 | `device-event-v1` |
| `device/{deviceId}/ota/result` | 设备 → 服务器 | QoS1, retained | `device-ota-result-v1` |

Canary 分组：`hash(deviceId) % 5` → `canary-0..canary-4`。设备订阅自己所在
桶 + `stable` 组；操作员向编号最小的 `ceil(桶数 × 百分比 / 100)` 个桶发布。
实际设备覆盖率取决于哈希分布，由 `ota_pub.py` 打印。

凭证（**仅供本地测试，切勿复用**）：操作员 `server` / `srv-dev-pass`；每台
设备有自己的随机密钥，由 `scripts/start-broker.sh` 生成并写入
`broker/state/device-creds.env`（gitignored），设备模拟器自动读取。新增设备：
`scripts/add-device-user.sh <deviceId> [extra-groups...]`。

授权：`scripts/gen-acl.sh` 由 `broker/acl.template.conf`（全局 pattern：本人
定向 OTA、本人遥测、agent 状态、广播）渲染出 `broker/state/acl.conf`，并为
每台设备追加一个 `user <deviceId>` 块，列出该设备可订阅的 cohort 主题。
设备没有通用的 `ota/group/+` 权限——分组归属按设备逐个枚举。

## 5. `demo.py` 自验证了什么

1. 设备队列启动并上报在线（遥测 + retained）
2. `AgentStatus` v1 状态投递并渲染（retained、语言无关）
3. canary 灰度：只有哈希落桶的设备升级
4. 分组（`stable`）发布升级其余设备
5. 离线设备：broker 触发 LWT；定向公告被持久会话排队，重连后安装
   （用 SIGSTOP/SIGCONT 注入断连）
6. retained 广播：迟到加入的设备安装已广播版本并渲染 retained 状态；
   收不到未 retained 的 canary/分组/定向消息
7. 召回防护：旧版本公告被**每台设备**拒绝（防降级）、越过 `min_version`
   墙的升级被**每台设备**拒绝（防回退底线）
8. 回滚演练：自检失败的设备回滚并保持原固件版本
9. ACL 负向探测：设备凭证不能写入他机遥测、不能订阅他机定向/分组主题

退出码 0 = 全部通过。设备日志在 `logs/<deviceId>.log`。

`demo.py` 开始时会在 collector 订阅确认后，用零长度 retained 发布清空
实验室自有的 retained 主题（默认 agents + fleet + 广播主题），保证每次
运行都基于全新 broker 状态，不被残留数据污染。

## 6. 目录结构

```
mqtt-lab/
├── broker/
│   ├── mosquitto.conf       # 贴近生产的 broker 配置
│   ├── acl.template.conf   # ACL 模板；gen-acl.sh 按设备渲染
│   ├── docker-compose.yml   # eclipse-mosquitto 容器
│   └── scripts/gen-certs.sh # 8883 用本地 CA + broker 证书
├── contracts/               # JSON Schema（供给 AW-004 的草案）
├── sims/
│   ├── common.py            # topic、凭证、canary 计算、载荷构造
│   ├── device.py            # 虚拟 ESP32-S3 设备
│   ├── server_pub.py        # AgentStatus 发布器
│   ├── ota_pub.py           # OTA 发布策略器
│   ├── tail.py              # 流量查看器
│   └── demo.py              # 自验证端到端场景
└── scripts/                 # setup / start / stop / reset / add-device
```

生成物（`broker/certs/`、`broker/state/`、`.venv/`、`logs/`）已 gitignore，仅存本地。

## 7. 局限

- 设备是 Python 进程而非 ESP32 固件，时序不代表真实 MCU。
- 证书是自签本地 CA（仅服务端认证、无客户端证书）——拓扑一致，信任锚与生产不同。
- OTA 公告中的 `url`/`sha256`/`signature` 为结构合法的占位符；固件下载为
  模拟（可选 `--check-url` 会对真实 GitHub URL 发 HEAD 请求）。
- MQTT 3.1.1 的遗嘱在连接时固定：OTA 安装后 LWT 遥测里的 `version` 可能
  陈旧。安装时会刷新 retained 在线遥测，因此对外的设备状态始终正确；
  LWT 载荷只作为崩溃信号。
- `mosquitto` 默认不把 client_id 绑定到认证用户；生产应用 mTLS 或认证
  插件绑定设备身份与 client ID（实验室 ACL 基于用户名）。
- 这是本地测试基础设施：这里的 schema 是 AW-004 的输入，正式 `AgentStatus`
  契约由 AW-004 落地到 `protocols/`。
