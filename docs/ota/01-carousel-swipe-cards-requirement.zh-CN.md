> English version: [01-carousel-swipe-cards-requirement.md](./01-carousel-swipe-cards-requirement.md)

# 01-滑动卡片轮播需求（左右滑动 + 循环 + 底部指示器）

> 日期: 2026-08-22
> 项目: ESP32-S3-Touch-LCD-3.5B（320×480 竖屏, LVGL 9.6, 模拟器验证）
> 状态: 需求定稿，待实现

---

## 一、功能需求

### 1. 左右滑动卡片（Carousel）
- 卡片横向排列，**卡片数量不确定**（动态 N 张，≥1）
- 手指左右滑动切换卡片
- 滑动有**吸附效果**（松手后自动对齐到最近的卡片，不卡在中间）

### 2. 循环滑动（无限轮播）
- **第一张继续向左滑 → 滑到最后一张**（循环）
- **最后一张继续向右滑 → 滑到第一张**（循环）
- 视觉上无缝循环，用户感觉是首尾相连的环

### 3. 底部指示器（Page Dots）
- 底部显示 N 个圆点，表示当前卡片在总卡片中的位置
- 当前卡片对应的点**高亮**（不同颜色/大小），其余灰暗
- 随滑动**实时更新**

### 4. 卡片内容（结合 Agent Status 项目）
每张卡片展示一个 Agent 的状态（与 agent-telemetry 项目数据对应）：
```
Agent 名（Codex / Claude Code / Copilot）
状态（RUNNING / WAITING / SUCCESS / ERROR）
任务描述
Token 用量 / 时间
```

---

## 二、技术约束与流畅度要求（关键）

1. **LVGL 9.6 无内置 carousel 组件** → 基于原生 scroll + snap 实现（不引入额外库）
2. **循环实现方式**：首尾镜像副本（第一张前插最后一张副本、最后一张后插第一张副本）→ 滑到副本时无动画跳回真实卡
3. **流畅度是第一优先级**：
   - 单缓冲 vs 双缓冲：PC 模拟器双缓冲；真机建议 `LV_COLOR_DEPTH=16` + PSRAM 双 buffer
   - 卡片内容**避免**渐变/阴影/半透明等重渲染效果（SW 渲染器下是流畅度杀手）
   - 文字、圆角矩形、实色块为主
   - 动画时间适中（200-300ms），跟随手指拖拽用 scroll 原生行为（不额外动画跟手）
   - 若偶发丢帧，保持手势跟手性（丢帧可接受，卡顿不可接受）
4. **320×480 竖屏布局**：
   - 卡片区: 顶部 ~400px（全宽，卡片即一屏宽）
   - 指示器区: 底部 ~60px 居中
5. **动态卡片数**：数据源变化时支持重建/增删卡片（预留 `rebuild_cards()` 接口）

---

## 三、实现验收标准（模拟器）

- [ ] 多张卡片（≥5）左右滑动吸附正常
- [ ] 第一张左滑 → 直接到最后一张（循环）
- [ ] 最后一张右滑 → 直接到第一张（循环）
- [ ] 底部 dots 随滑动正确高亮
- [ ] 长列表不卡顿（模拟器肉眼流畅）
- [ ] 代码结构清晰（cards 数据与 UI 分离，便于后续接 agent-telemetry 数据）

---

## 四、参考数据样例（卡片内容）

```c
// 卡片数据（模拟 agent-telemetry 的 session 模型）
card_t cards[] = {
    {"CODEX",    "RUNNING", "Refactoring auth middleware", 12482, 134},
    {"CLAUDE",   "WAITING", "Waiting for permission",      4300,  12},
    {"COPILOT",  "SUCCESS", "OTA design research",         20414, 356},
    {"CODE",     "ERROR",   "Build failed: link error",     812,   5},
    {"HERMES",   "IDLE",    "No active task",               0,     0},
};
```

---

## 五、落地位置

- 实现: `/mnt/sdc1/Playground/esp32-lvgl-sim/src/main.c`（模拟器 demo）
- 文档: `~/docs.local/esp32-lvgl-ui/`（本目录）
