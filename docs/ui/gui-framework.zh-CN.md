---
title: "GUI 框架选型"
date: 2026-08-21
status: complete
tags:
  - lvgl
  - gui
  - comparison
description: "ESP32 触摸屏 GUI 方案对比：LVGL vs Arduino_GFX vs SquareLine Studio vs 其他"
---
> English version: [gui-framework.md](./gui-framework.md)


# GUI 框架选型

> 创建时间: 2026-08-21

---

## 方案全景对比

| 方案 | 类型 | 学习成本 | UI 复杂度 | 数据图表能力 | 推荐场景 |
|---|---|---|---|---|---|
| **LVGL** ⭐ | 完整 GUI 框架 | 中 | 高（widget 丰富）| ⭐ 强（chart/arc/bar）| 仪表盘、多页面、触摸交互 |
| **Arduino_GFX** | 底层绘图库 | 低 | 低（画线/矩形/文字）| 中（需手写）| 简单状态屏、数值显示 |
| **TFT_eSPI** | 底层绘图库 | 低 | 低 | 中（有 sprite）| 快速图形、游戏 |
| **SquareLine Studio** | 可视化设计器 | 低（拖拽）| 极高（所见即所得）| 中（生成 LVGL 代码）| 快速出界面、团队协作 |
| **GUI Guider**（NXP）| 可视化设计器 | 低 | 高 | 中 | LVGL 生态备选 |
| **ESPHome LVGL** | YAML 配置 | 低 | 中 | 中 | Home Assistant 集成 |
| **MicroPython + LVGL** | 脚本 | 低 | 高 | 强 | 快速原型（性能略低）|

## 推荐：LVGL 为主，Arduino_GFX 为底

> ⚠️ **2026-08-24 更新**：本节是 Arduino 快速原型视角。正式固件目标是 **ESP-IDF**（项目操作契约），生产驱动层用官方 `espressif/esp_lcd_axs15231b`（QSPI），非 Arduino_GFX。LVGL 版本待 AW-005 锁定（官方 demo v8.4/v9.2.2；本仓库 PC 模拟器 v9.x）。本节结论仅作 Arduino PoC 参考。

**结论（Arduino PoC 视角）：LVGL + Arduino_GFX 驱动层** 组合的要点：

1. **官方 demo 即此组合**——开箱即用，省去移植
2. **lv_chart 是唯一开箱即用的图表组件**——折线/柱状/散点 + 触摸取点 + 双 Y 轴，做数据 diagram 的核心
3. **widget 生态全**：arc（仪表盘）、bar（进度条）、scale（坐标轴）、tabview（多页面）、anim（动画）
4. 8MB PSRAM 跑 LVGL 富 UI 无压力

### 为什么不选其他

- **纯 Arduino_GFX**：能画但一切手写（坐标换算、缩放、触摸命中检测都要自己做），做 diagram 成本高
- **TFT_eSPI**：Type B 是 QSPI + AXS15231B，TFT_eSPI 官方不支持该驱动（Arduino_GFX 才支持）——**排除**
- **SquareLine Studio**：免费版可导出 LVGL 代码，适合搭界面骨架，但图表逻辑仍需手写；且生成的代码是 v8 风格，注意匹配
- **ESPHome LVGL**：适合 HA 集成，纯 YAML 画简单控件；复杂 diagram 仍受限于 YAML 表达力

## LVGL v8 vs v9 选择（重要）

| | LVGL v8.4（官方 demo）| LVGL v9.x |
|---|---|---|
| 显示对象 | `lv_disp_drv_t` / `lv_disp_drv_register` | `lv_display_t` / `lv_display_create` |
| 屏幕对象 | `lv_scr_act()` | `lv_screen_active()` |
| 缓冲 | `lv_disp_draw_buf_init` | `lv_display_set_buffers` |
| 图表 | `lv_chart_*`（v8 即成熟）| `lv_chart_*`（API 微调）|
| 生态教程 | 最多（Random Nerd 等）| 较少但增长中 |
| SquareLine 导出 | 默认支持 | 需选 v9 模板 |

**建议**：新项目直接跟官方 demo 用 **v8.4**（教程/示例最多，踩坑少）；若想用新特性（如 3D 纹理、新 scale 组件）再上 v9。

## 我的分析（架构视角）

1. **分层思想**：驱动层（Arduino_GFX/QSPI）→ 框架层（LVGL）→ 数据层（自己管）→ UI 层（widget）。数据层独立出来（环形缓冲区 + 采样定时器），UI 只订阅渲染，互不阻塞
2. **图表性能（待真机验证）**：lv_chart 更新是增量绘制（只重画变化区域），比整屏刷新快很多；配合 PSRAM 大缓冲 + QSPI 高带宽，"30fps 图表动画"只是**假设**，须在 AW-005 真机测量（帧率/触摸延迟/内存）后才能作为结论
3. **触摸交互是差异化**：AXS15231B 一体触摸（I2C 0x3B，最多 2 点；⚠️ 不是 FT6336U，那是普通版 3.5），LVGL 事件系统（`lv_obj_add_event_cb`）天然支持点击图表取点——这是"数据可交互"的关键

---

## 引用来源

- [LVGL Chart 文档](https://docs.lvgl.io/master/widgets/chart.html)
- [SquareLine Studio 教程（Zbotic）](https://zbotic.in/squareline-studio-design-ui-for-esp32-tft-with-lvgl-visually/)
- [LVGL Open Widgets](https://lvgl.io/docs/open/widgets/chart)
- [Random Nerd Tutorials LVGL 系列](https://randomnerdtutorials.com/esp32-tft-lvgl-line-chart/)
