> English version: [00-repository-organization-design.md](./00-repository-organization-design.md)

# Agent Widget：仓库整理与基础架构设计

> 日期：2026-08-23
> 状态：已确认，等待按此设计整理仓库

## 目标

`agent-widget` 是唯一正式 GitHub 仓库。它将来构建 ESP32-S3 固件，并通过 GitHub Release 承载可验证的 OTA 发布物。

仓库同时保存可复现的设计、协议和验证证据；不保存临时 PoC、编译产物、私钥、依赖缓存或设备专属数据。

## 范围与边界

| 内容 | 处理方式 | 原因 |
|---|---|---|
| Waveshare 3.5B 硬件、开发环境与 LVGL 研究文档 | 纳入 `docs/hardware/` 与 `docs/research/` | 是后续开发的稳定参考 |
| OTA 方案、Wokwi 串口证据与复盘 | 纳入 `docs/ota/` | 保留已验证结论与限制 |
| `esp32-wokwi-ota` 的 `.ino`、Python 构建脚本、`.bin` | 不迁移 | 是独立 Arduino/ESP32 PoC，不是目标 S3 固件 |
| `esp32-lvgl-sim` 的上游 clone、子模块与构建目录 | 不迁移 | 体积大且是外部 LVGL 参考工程 |
| 截图 | 仅保留能说明 UI 设计的精选图，放入 `docs/ui/assets/` | 便于评审，避免构建产物膨胀 |
| 密钥、证书、设备日志、固件、SDK/依赖缓存 | 留在本地并由 `.gitignore` 忽略 | 安全、可复现性与仓库体积 |

## 目标目录

```text
agent-widget/
├── firmware/                  # 未来唯一的 ESP-IDF ESP32-S3 固件
├── macos-client/              # 可选 macOS 采集/转发器；先放设计与实验说明
├── protocols/                 # 跨进程/跨网络消息契约及传输实验
├── simulator/                 # 未来可复现的 PC LVGL simulator
├── experiments/               # 可跟踪的实验说明；本地产物默认忽略
├── docs/
│   ├── architecture/          # 本设计与 ADR
│   ├── hardware/              # 板卡与 toolchain 资料
│   ├── ui/                    # 信息架构、交互、性能验收、截图
│   ├── transport/             # Mac/Agent/服务端到设备的数据路径
│   ├── ota/                   # OTA 设计、验证证据、发布流程
│   └── research/              # 原始研究和外部资料摘要
├── .gitignore
└── README.md
```

目录可为空；在进入相应实现阶段前，先放 README 或设计文档，避免创建没有用途的脚手架代码。

## 三个产品方向

### 1. Agent 状态采集与传输

设备只消费统一的 `AgentStatus` 契约，不知道 Codex CLI、Claude Code 或 Copilot CLI 的日志格式。

```text
Agent 或 macOS adapter -> AgentStatus -> transport -> ESP32 device
```

第一优先的验证路径为：Agent 或其自动化脚本调用 HTTP API，服务端发布 MQTT，ESP32 订阅 MQTT。

macOS client 是一个可选 adapter：它仅在直接采集本机 CLI 状态显著可靠或易用时再实现。BLE 和局域网 Wi-Fi 是对照实验，不应阻塞 MQTT 主线。所有路径必须产生完全相同的 `AgentStatus` 数据。

### 2. ESP32 UI 与性能

术语固定如下：

- **Panel**：整个横向滑动的一页屏幕。
- **AgentCard**：Panel 内展示一个 agent 的状态卡。
- **SettingsPanel**：固定存在的设置 Panel，不混入 AgentPanel。
- **PanelIndicator**：屏幕底部的可点击位置点；颜色/形状同时表达对应 Panel 的聚合状态。

每个 **AgentPanel** 组合 1--2 张 `AgentCard`。界面从第一天起支持英文与中文；协议传递稳定状态码和文案键，设备按当前语言映射文案，不能把英文展示文案当作协议状态。

性能验收以真实设备为准：16-bit 色深、PSRAM buffer、局部失效重绘、复用控件、少量短动画。PC simulator 只验证布局、滑动规则和状态映射，不替代真机帧率、触摸延迟或内存验证。

### 3. OTA 基础设施

第一次 USB 刷写只安装 bootstrap 固件；之后所有日常升级必须走 OTA：

```text
GitHub Actions build -> Release + signed manifest -> HTTPS OTA
-> inactive OTA slot -> reboot -> health check -> valid / rollback
```

正式实现采用 ESP-IDF、双 OTA app 分区和 rollback。健康检查至少包括显示初始化、Wi-Fi 连接、状态传输任务存活与 UI 主循环存活。Secure Boot 与 Flash Encryption 在该流程完成多次真机成功/失败回滚演练之后，单独建立密钥管理与不可逆 eFuse 启用计划。

## Git 管理原则

提交：源代码、分区表、构建配置、测试、消息 schema、文档、少量精选截图、经人工确认的串口证据。

本地忽略：`build/`、`.pio/`、`.idf/`、`managed_components/`、`*.bin`、`*.elf`、`*.map`、`sdkconfig` 的本机覆盖、密钥/证书、下载缓存、临时日志、视频和实验输出。用于发布的固件不入 Git history，而是由 CI 上传 GitHub Release。

## 非目标

- 不把现有 Arduino/Wokwi PoC 伪装成 ESP32-S3 正式代码。
- 不把 880 MB 的 LVGL upstream clone 或 submodule vendor 到本仓库。
- 不承诺同时完成 MQTT、BLE、局域网 Wi-Fi 和 macOS client；它们是按证据淘汰的备选路径。
- 不在开发初期烧录 Secure Boot eFuse。
