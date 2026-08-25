---
title: "Panel UI 设计：轮播 + 垂直滚动详情 + 状态指引器"
date: 2026-08-24
status: proposed
tags:
  - ui
  - panel
  - carousel
  - agent-status
  - ota
  - design
description: "ESP32-S3-Touch-LCD-3.5B（320×480竖屏/LVGL）的 Panel 轮播界面设计：一 panel 一 agent、垂直滚动展开详情、状态色指引器、OTA/固件升级界面的完整交互与状态机。"
---

# Panel UI 设计：轮播 + 垂直滚动详情 + 状态指引器

> 对应任务：`AW-005`（Specify Panel UI and establish real-device responsiveness measurements）
> 视觉来源：ChatGPT 生成的四个方向（A 深色信息仪表盘 / B 极简一眼式 / C 卡片式轻量 / D 数据与运营视图）——**仅作参考，非最终设计**。本设计以这些方向为素材重新组织。
> 硬件事实来源：`docs/hardware/board-spec-constraints.md`（权威）；术语沿用 `docs/architecture/00-repository-organization-design.md`。
> OTA 事实来源：`docs/ota/02-ota-design-esp-https-rollback.md`、`docs/ota/04-ota-evaluation-conclusion.md`。

---

## 0. 设计定位

- 设备：Waveshare ESP32-S3-Touch-LCD-3.5B，**320×480 竖屏**（原生 ROT 0），RGB565（16bpp），AXS15231B（QSPI 显示 + I2C 0x3B 触摸），8MB PSRAM，16MB Flash。
- GUI 框架：**LVGL**。版本在 AW-005 锁定（官方 demo v8.4 / v9.2.2；本仓 PC simulator 为 v9.x —— 二选一，禁止混用 API）。
- 视觉底座：选定 **方案A（深色信息仪表盘）**——高信息密度、强层级、深色低干扰，最衬“状态词 + 进度/用量”的 agent 信息。方案C（卡片式）与方案B（极简）作为交互与留白参考；方案D（数据运营）仅作为详情页图表的取舍依据。
- 术语固定：
  - **Panel**：整个横向滑动的一页屏幕。
  - **AgentPanel**：展示一个 agent 会话状态的 Panel。
  - **UpdatePanel**：OTA / 固件升级的常驻系统 Panel（P1）。
  - **SettingsPanel**：固定存在的设置 Panel（永远最后一张）。
  - **AgentCard**：Panel 内展示一个 agent 的状态卡。
  - **PanelIndicator**：屏幕底部的可点击位置点；颜色/形状同时表达对应 Panel 的聚合状态。

---

## 1. Panel 集合与循环轮播

### 1.1 结构

```text
[AgentPanel₁ … AgentPanelₙ] → [UpdatePanel] → [SettingsPanel]
```

- **横向轮播**：一屏一个 Panel，左右滑动，**无限循环**（首尾镜像副本实现无缝、无跳变）。
- **动态集合**：`n` = 当前活跃 agent 会话数（可为 0）。
  - `AgentPanel₁ … AgentPanelₙ`：动态生成，每个对应一个 agent 会话。
  - `UpdatePanel`：**常驻**系统 Panel（OTA 是 P1，任何设备都必须可测更新）。始终存在，位于 agent 面板之后、Settings 之前。
  - `SettingsPanel`：**固定为最后一张**，永远存在。
- 空态：无活跃 agent 时，集合为 `[UpdatePanel, SettingsPanel]`，并显示空态页（见 §9）。
- 松手**吸附**：手指拖拽用原生 scroll 行为跟手，不加额外跟手动画；松手后自动对齐最近的 Panel。

> 备选（未采用，可切换）：OTA 不单独占 panel，只作为 SettingsPanel 顶部的“系统更新区 + 全屏覆盖层”。本设计采用独立 `UpdatePanel`，理由：开发期 OTA 状态最易一眼看到，且与“每 panel 上下滚动展开详情”的交互模式一致。

### 1.2 数据驱动

- 会话增删 → `rebuild_panels()`：重建轮播面板 + 指引器点数，保持吸附与循环。
- 动态卡片数：预留重建接口；增删时不整屏重建，只增删对应 Panel。
- 每个 AgentPanel 组合 **1–2 张 AgentCard**（架构文档口径）；本设计默认**一 panel 一 agent**，故一 panel 一张 AgentCard，展开态承载该 agent 的更多信息（见 §2）。

---

## 2. 单 Panel 的信息分层（设计核心）

一个 AgentPanel 内做**折叠 / 展开**两级，靠**垂直滚动**切换：

| 层级 | 内容 | 触达方式 |
|---|---|---|
| **折叠态（默认）** | agent 名 · 状态色+图标 · 当前任务一行 · 关键指标（token 进度条 / %） | 进入即见 |
| **展开态** | 活动时间线、token 用量细分（输入/输出）、已用时长、context %、费用、迷你趋势/小柱状 | 垂直上滑 |

- **折叠态信息一屏容纳，不滚动。**
- **展开态是滚动容器**：只加载“更多”区块；信息不足一屏时禁止滚动出现空白。
- **默认规则**：进入 / 切回某个 Panel 时**回到折叠态**（确定性、可预期）；用户点按展开后才进入展开态。任何 Panel（含 Update、Settings）都遵循此默认。

同样规则适用于 `UpdatePanel` 与 `SettingsPanel`：默认显示核心状态，可垂直滚动看更多。

---

## 3. 手势冲突消解（关键）

水平轮播与垂直滚动在同一屏，靠 **方向锁定** 消解：

| 手势 | 动作 | LVGL 实现 |
|---|---|---|
| 水平滑动 | 切换 Panel（外层 carousel，HOR lock） | 外层横向 scroll 容器 |
| 垂直滑动 | 展开/回缩 Panel 内详情（内层 scroll，VER lock） | 内层纵向 scroll 容器 |
| 点按指引器圆点 | 跳转到对应 Panel | dot 点击事件 |
| 点按卡片元素 | （可选）展开详情 / 执行动作 | 卡片事件回调 |

- 用 `LV_OBJ_FLAG_SCROLL_ONE` / `scroll_dir` 让外层只认横滑、内层只认纵滑，保证不误触。
- 触摸：AXS15231B 一体触摸（I2C 0x3B，最多 2 点，ROT 0 直接映射 320×480，无 swap/mirror）。

---

## 4. PanelIndicator（底部指引器）— 双语义

- **N 个圆点 = N 个 Panel 的位置。**
- **圆点颜色 = 该 Panel 对应 agent 的聚合状态**（或 Update/Settings 的系统状态）。
- 当前 Panel 的圆点：**放大 + 描边/高亮**；其余灰暗小点。
- 圆点本身用状态色区分（**无文字**）；“远看一眼”即知每个 agent / 系统在忙/在等/出错/完成。
- 空态时只剩系统点（Update + Settings）。
- 指引器区域需预留底部安全边距，避免触摸命中与内容区相互干扰。

---

## 5. 状态 → 颜色 / 图标 / 文案映射

> 状态码来自 `AgentStatus` 契约。界面显示**状态色 + 图标 + 双语文案键**，不通篇英文。此表同时驱动指引器颜色、卡片状态徽标、详情页横幅、更新状态。

### 5.1 agent 状态

> 图标的“⏸ ▶ 🧠 ✓ ✕ ○”为示意；设备端用**主题内置的绘制形状/矢量图标**（或用已嵌入字体的符号字形），**不渲染 emoji**。每个状态一个固定图标语义，随状态色一同切换。

| AgentStatus | 指引器/徽标色 | 图标语义 | 中文文案 | 英文键 |
|---|---|---|---|---|
| `WAITING` | 琥珀 `0xFFB300` | 暂停/等待 | 等待 | waiting |
| `RUNNING` | 绿 `0x00C853` | 播放/进行 | 运行中 | running |
| `THINKING` | 蓝 `0x2094F3` | 脑/思考 | 思考中 | thinking |
| `DONE` | 青 `0x00BFA5` | 对勾/完成 | 完成 | done |
| `ERROR` | 红 `0xFF3D00` | 叉/出错 | 出错 | error |
| `IDLE` / `OFFLINE` | 灰 `0x7A7A7A` | 圆点/空心 | 空闲 · 离线 | idle / offline |

- 逻辑归并：`NEEDS_INPUT → WAITING`；`SUCCESS → DONE`；`IDLE`/`OFFLINE` 单列。
- **聚合状态** = 活跃里优先级最高的异常/进行态：`ERROR > RUNNING > WAITING > DONE > IDLE`。

### 5.2 更新（OTA）状态

| 阶段 | 颜色 | 文案（中文/英文键） |
|---|---|---|
| 有可用更新 | 蓝 `0x2094F3` | 有新版本 / update_available |
| 更新中（下载/校验） | 琥珀 `0xFFB300` | 更新中 / updating |
| 已是最新 | 灰 `0x7A7A7A` | 已是最新 / up_to_date |
| 回滚 | 红 `0xFF3D00` | 已回滚 / rolled_back |

---

## 6. OTA 与固件升级界面（P1 · 最高优先级）

> 定位：这套界面**不只是给用户看状态，而是开发期验证 OTA 能否工作的测试仪器**。对应 AW-006 管道三阶段（检查 / 下载 / 自检回滚），UI 在每个阶段都必须可观测、可干预、可诊断。

OTA/更新 UI 由**三个面**组成。

### 6.1 全屏更新覆盖层（Update Overlay）— 状态机，接管整个屏幕

更新进行中时无条件全屏显示，避免任何 agent 内容盖在上面。状态机严格对齐 OTA 管道：

| 阶段 | 屏幕呈现 | 用户可干预 |
|---|---|---|
| 检查更新 | 转圈 + 「正在检查更新…」 | 可取消 |
| 有新版 | 新旧版本号 + 大小 + changelog + 「下载并安装」 | 确认 / 放弃 |
| 下载中 | **进度条 + 已下载字节 + 速度**（由 `ESP_HTTPS_OTA` 事件驱动） | 不可中断（防半写） |
| 校验中 | 转圈 + SHA256/签名校验 | — |
| 将重启 | 「更新完成，正在重启…」 | — |
| 自检（PENDING_VERIFY） | 新固件首屏渲染**自检页**（见 6.2） | — |
| 成功 | 绿 ✓「更新成功 · 运行 vX」 | — |
| 失败 / 回滚 | 红 ✕「更新失败，已回滚到 vPrev」+ 原因 | 查看诊断 |

### 6.2 自检 / 健康页（Self-Test Screen）— 回滚决策屏（对“能否实现 OTA”最关键）

对标 OTA 04 Q4：新固件启动后进入 `PENDING_VERIFY`，**必须先渲染出这个自检页**才能证明显示 + 触摸初始化成功，且该页本身就是「是否 `mark_valid` 回滚」的判定面。逐项打勾/打叉：

- [x] 显示初始化（本页已渲染 = 已证明）
- [x] 触摸 I2C ACK
- [x] WiFi STA 已连接并获取 IP
- [x] OTA 检查任务存活
- [ ] 服务器可达（**仅记录，不回滚**——云端故障不该把好固件标为坏）

全部通过 → `esp_ota_mark_app_valid_cancel_rollback()`；任一**必过项**失败/超时 → 显示「自检失败，回滚中」并触发 `esp_ota_mark_app_invalid_rollback_and_reboot()`。

> **这页是 AW-006 回滚演练的肉眼判据。** 回滚窗口可按 `CONFIG_BOOTLOADER_APP_ROLLBACK_TIMEOUT` 配置（默认 5s，建议调大到 30–60s）。

### 6.3 系统更新区（UpdatePanel 主体）

作为常驻系统 Panel（P1），提供测试期可观测诊断：

- **当前版本** + **运行槽**（factory / ota_0 / ota_1）+ 构建信息。
- **「检查更新」按钮** + 上次检查时间 + 结果。
- **诊断信息**：启动次数 / 上次崩溃原因 / OTA 状态 / 回滚历史（来自 NVS，用于回滚原因分析）。
- 下载中在此显示进度（与 6.1 全屏覆盖层同步）。

### 6.4 OTA 管道 → UI 对照

```text
检查更新 → HTTPS 拉取 manifest（签名验证 + fresh 检查）
  → 版本 > 当前？ → 下载到临时区 → 校验 sha256+签名 → esp_ota_write 到空闲槽
  → 重启（bootloader 置 PENDING_VERIFY）
  → 自检（6.2：显示/触摸/WiFi/OTA 任务）
  → 全过 → mark_valid | 失败/超时 → mark_invalid_rollback
  → 连续失败 N 次 / GPIO 长按 → 跳 factory 恢复固件
```

---

## 7. 数据流（AgentStatus → UI）

- 设备只消费统一 `AgentStatus`。
  - **状态码** → 颜色/图标（§5）。
  - **数值** → 进度/统计。
  - **文案** → 按当前语言由消息键映射（协议不携带显示用英文）。
- 渲染走**增量更新**：状态码/数值变化才重绘对应区域（卡头顶部 / 进度条 / 详情区块），不整屏刷；局部失效重绘。
- 会话增删 → `rebuild_panels()`（§1.2）。
- 数据与 UI 解耦：采集/传输在任务，UI 在 `lv_timer_handler()` 主循环；数据先入缓冲，UI 只读缓冲渲染。

---

## 8. 双语与字体

- 界面从第一天起支持**中文与英文**。
- 协议传递稳定状态码和文案键；设备按当前语言映射文案。**不能把英文展示文案当作协议状态。**
- 设备端**内置中文字体**（LVGL 字体转换，子集化按需嵌字符以省 Flash）；PC sim 的宿主字体仅作布局参考。
- 语言切换入口在 SettingsPanel。

---

## 9. 设置面板与空态 / 错误态

### 9.1 SettingsPanel（末尾固定）

- 语言切换（中 / 英）。
- 主题 / 亮度。
- 关于（固件版本、设备号、运行槽）。
- （OTA 相关集中在 UpdatePanel，不在 Settings 重复；此处仅“关于/版本”只读展示。）

> 早期（OTA 测试期）Settings 内也可放“系统更新区”的只读摘要，但与 UpdatePanel 分工需明确，避免两处状态不一致。

### 9.2 空态 / 错误态

- 无活跃 agent：空态页 + 仅系统点（Update + Settings）。
- 离线 / 传输中断：状态卡显示 `OFFLINE` 灰，对应指引器点转灰，不整屏报错。
- `ERROR`：状态卡 + 指引器点转红，正文显示原因；可滚动看详情。

---

## 10. 性能与实现约束（真机验收，不靠 sim 下结论）

- 16-bit RGB565、PSRAM 全屏 draw buffer、局部失效重绘、控件复用、短动画（200–300ms）。
- **避免渐变/阴影/半透明**——SW 渲染器下是流畅度杀手；以实色块、圆角矩形、文字为主。
- 优先保证手势跟手性（偶发丢帧可接受，卡顿不可接受）。
- 中文为设备内置字体；数值×100/×1000 存整型再除回。
- **PC sim 只验证布局、滑动规则、状态映射、交互语义**；帧率、触摸延迟、内存/PSRAM、Wi-Fi 重连、OTA 回滚只能在真机测量（AW-002/003/005）。

---

## 11. 验收范围（AW-005）

- [ ] Panel / AgentCard / SettingsPanel / UpdatePanel / PanelIndicator 行为已指定（本文）。
- [ ] 一 panel 一 agent（可扩展到 1–2 张 card）。
- [ ] 折叠/展开、横滑循环、方向锁定、吸附、指引器状态色已指定。
- [ ] 双语（中/英）字符串键已指定；协议 payload 不随显示语言变化。
- [ ] 真机测得触摸延迟、帧率、内存基线（AW-005 测量，非 sim 结论）。
- [ ] OTA 三面（6.1/6.2/6.3）与 AW-006 管道对齐，可用于回滚演练判据。

---

## 12. 待确认 / 可切换点

1. **OTA 独立 panel（采用）vs 仅 Settings 顶部区**：本设计采用 `…→[UpdatePanel]→[SettingsPanel]`，UpdatePanel 常驻。若切换为“仅 Settings 顶部区”，则指引器点减少，Update 状态仅能在 Settings 内查看。
2. **展开/折叠跨 panel 记忆**：已定默认——**进入/切回任何 Panel 都回到折叠态**（确定性、可预期），不跨 panel 记忆展开态。若后续需要“保持上次展开”，在此追加即可。
3. **LVGL 版本**：v8.4（官方 demo，教程多）vs v9.x（与 PC sim 一致）——AW-005 锁定后写死到本文与 `gui-framework.md`。
4. **更新覆盖层是否允许在 Settings 打开“更新历史/回滚详情”**：本设计仅在诊断区给只读摘要，未做完整历史页。

---

## 引用来源

- `docs/architecture/00-repository-organization-design.md`（Panel/AgentCard/SettingsPanel/PanelIndicator 术语）
- `docs/hardware/board-spec-constraints.md`（板级权威约束）
- `docs/ui/gui-framework.md`（LVGL 版本与架构）
- `docs/ui/data-viz-diagram-design.md`（图表/仪表盘渲染方法）
- `docs/ota/02-ota-design-esp-https-rollback.md`、`docs/ota/04-ota-evaluation-conclusion.md`（OTA 管道与自检/回滚判据）
- `docs/ota/01-carousel-swipe-cards-requirement.md`（轮播循环/吸附/指示器需求）
