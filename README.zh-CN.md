# agent-widget

**基于 ESP32-S3 的 AI Agent 状态显示终端。**

agent-widget 将一块 Waveshare ESP32-S3-Touch-LCD-3.5B 变成 AI 编码 Agent 的实时状态仪表盘：可靠地接收状态更新，在 320×480 电容触摸屏上流畅渲染，并通过经过验证的 OTA 发布流程更新自身固件。

## 项目目标

项目的最终目标是一个可在真机上复现的演示：

1. Agent 的 `AgentStatus` 通过网络到达设备（以 MQTT 为主的数据通路）。
2. 设备在触摸屏上流畅渲染状态——一个 Agent 一个 Panel，带状态色指示器。
3. 设备可以从 GitHub Releases 安装经过验证的固件更新——包括健康检查失败时的自动回滚。

## 当前状态

| 领域 | 状态 |
|---|---|
| UI 设计（Panel 轮播、可展开 Agent 卡片、更新覆盖层） | 已定稿 —— 见 [`docs/ui/panel-ui-design.md`](docs/ui/panel-ui-design.md) |
| OTA 发布流程（GitHub Actions → GitHub Releases → 设备） | 已端到端验证（v2.0.0）—— 见 [`docs/ota/`](docs/ota/) |
| 板卡约束调研（引脚、I2C、显示、构建配置） | 权威文档 —— 见 [`docs/hardware/board-spec-constraints.md`](docs/hardware/board-spec-constraints.md) |
| 生产固件（ESP-IDF） | 开发中 |
| AgentStatus 传输（MQTT） | 规划中 |

## 首选硬件

当前硬件目标为 **Waveshare ESP32-S3-Touch-LCD-3.5B**（SKU 31137；SKU 31334 "3.5B-C" 带外壳与摄像头）。

| 组件 | 规格 |
|---|---|
| SoC | ESP32-S3R8 —— 双核 Xtensa LX7 @ 240 MHz |
| 内存 | 512 KB SRAM + 8 MB Octal PSRAM |
| Flash | 16 MB QIO NOR Flash（W25Q128JVSIQ） |
| 屏幕 | 3.5 英寸 IPS 电容触摸，320×480 竖屏，262K 色 |
| 显示 / 触摸控制器 | AXS15231B（QSPI 显示 + I2C 触摸 @ 0x3B） |
| 无线 | 2.4 GHz Wi-Fi（802.11 b/g/n）+ 蓝牙 5 LE |
| 工具链 | ESP-IDF ≥ 5.4 |

官方链接：

- [产品页](https://www.waveshare.com/product/esp32-s3-touch-lcd-3.5b.htm)
- [Wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-3.5B)
- [文档平台](https://docs.waveshare.com/ESP32-S3-Touch-LCD-3.5B)
- [官方示例仓库](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-3.5B)

## 仓库结构

```
agent-widget/
├── docs/            # 面向用户的文档（以美式英文为主；中文版使用 .zh-CN.md 后缀）
├── firmware/        # 生产 ESP-IDF 固件（开发中）
├── ota-sim/         # 发布流程使用的 Arduino PoC（历史遗留）
├── protocols/       # AgentStatus 协议与传输契约
└── scripts/         # CI 与发布辅助脚本
```

## 文档

- [`docs/architecture/00-repository-organization-design.md`](docs/architecture/00-repository-organization-design.md) —— 架构与仓库设计
- [`docs/hardware/board-spec-constraints.md`](docs/hardware/board-spec-constraints.md) —— 权威板卡规格、引脚与构建约束
- [`docs/ui/panel-ui-design.md`](docs/ui/panel-ui-design.md) —— 屏幕 UI 设计
- [`docs/ota/`](docs/ota/) —— OTA 设计、验证证据与发布流程

## 许可证

MIT —— 见 [LICENSE](LICENSE)。
