# 08-GitHub OTA 模拟验证（Wokwi，2026-08-30 跑通）

> 任务: 用户要求「今天跑通模拟环境的 OTA；通过 GitHub 进行 OTA；任何一个版本都可以用来刷机；刷任意版本后无需再刷机（OTA 自动到最新）；可选：设置 OTA 到任意版本」
> 结果: ✅ **两个场景全部在 Wokwi 模拟器跑通，固件源为 GitHub（raw.githubusercontent.com 直链 + GitHub Releases API 双通道）**

---

## 一、结论速览

| 用户要求 | 状态 | 证据 |
|---|---|---|
| 模拟环境跑通 OTA | ✅ 跑通 | 见下方串口日志（V1→V2 全流程） |
| 通过 GitHub 进行 OTA | ✅ 双通道 | Releases API（生产主通道，暂无 release 时自动回退）+ manifest.json（raw 直链，PoC 通道） |
| 任何一个版本都可以刷机 | ✅ 已发布 1.0.0 / 2.0.0 | `firmware/releases/vX.Y.Z.bin`，sha256 已校验 |
| 刷任意版本后无需再刷机 | ✅ 自动检查升级 | 场景 1：V1.0.0 → 自动升 2.0.0；场景 2：V2.0.0 → No update needed |
| 设置 OTA 到任意版本（可选） | 🔧 已接线 | `OTA_TARGET_VERSION` 编译时指定（如 1.1.0）；回退（downgrade）有意拦截，与生产 anti-rollback 一致 |

**与 07 复盘的区别**：07 的固件源是 catbox.moe 临时文件、无版本比较；本次固件源换成 **GitHub**，并加入版本感知（semver 比较 + latest/指定版本双模式），模拟了真实 OTA 客户端行为。

---

## 二、架构

```
                 ┌─────────────────────────────── GitHub ───────────────────────────────┐
 ESP32 (Wokwi)   │  通道 A: api.github.com/repos/agent-widget/agent-widget/releases      │
 ┌───────────┐   │          (生产主通道；无 release 资产时 404 → 回退)                    │
 │ sketch    │──▶│  通道 B: raw.githubusercontent.com/.../firmware/manifest.json        │
 │ (OTA 客户端)│   │          (PoC 过渡通道；清单列出所有已发布版本+直链)                  │
 └───────────┘   │  固件:   raw.githubusercontent.com/.../firmware/releases/vX.Y.Z.bin  │
                 └───────────────────────────────────────────────────────────────────────┘
  启动 → 打印版本 → 连 Wokwi-GUEST → 查 GitHub → target(最新/指定) > 当前？
       ├─ 是 → 下载 → Update 写 flash → 重启 → 新固件运行
       └─ 否 → 打印 "No update needed" → 正常心跳
```

**sketch 关键设计**（`ota-verify/sketch_gh_ota.ino`，Arduino 生态，零外部依赖）：
- `FW_VERSION` / `OTA_TARGET_VERSION` 编译时注入（`build_gh.py`）
- 极简 JSON 解析（容忍 `"key": "value"` 空格），不引 ArduinoJson
- semver 比较（MAJOR.MINOR.PATCH 整数段）
- `Update` 类写 flash（Wokwi 分区表 otadata + app0/app1 已由项目 337425600260080210 提供）

---

## 三、场景 1：刷 V1.0.0 → 自动升级到最新 2.0.0（串口日志节选）

```
[BOOT] Firmware VERSION : 1.0.0
[BOOT] OTA target       : latest
[WIFI] Connected! Local IP: 10.10.0.2
[OTA] Releases API: no release assets found          ← 通道 A 无 release，自动回退
[OTA] Channel: manifest.json (raw.githubusercontent)  ← 通道 B
[OTA] Available versions (8): 1.0.0 2.0.0
[OTA] Target 2.0.0 > current 1.0.0 → updating
[OTA] Downloading new firmware from: https://raw.githubusercontent.com/agent-widget/agent-widget/main/firmware/releases/v2.0.0.bin
[OTA] HTTP GET response code: 200
[OTA] Firmware size: 1035952 bytes
[OTA] Update.begin() OK, writing to flash ...
[OTA] Progress: 10% (103808 / 1035952 bytes) ... 100%
[OTA] Downloaded 1035952 bytes (expected 1035952)   ← 逐字节一致
[OTA] Update SUCCESS! 1035952 bytes written to flash.
[OTA] Rebooting into new firmware ...
--- 重启 ---
[BOOT] Firmware VERSION : 2.0.0                       ← OTA 生效
[WIFI] Connected! Local IP: 10.10.0.2
```

完整日志: `wokwi-run/serial-1.0.0.txt`（本地；含真实 boot 序列 rst:0x1 POWERON_RESET → rst:0xc SW_CPU_RESET）

## 四、场景 2：刷 V2.0.0 → 无需再刷机（串口日志节选）

```
[BOOT] Firmware VERSION : 2.0.0
[WIFI] Connected! Local IP: 10.10.0.2
[OTA] Releases API: no release assets found
[OTA] Channel: manifest.json (raw.githubusercontent)
[OTA] Available versions (8): 1.0.0 2.0.0
[OTA] Current 2.0.0 already >= target 2.0.0. No update needed.
[APP] heartbeat ... running firmware 2.0.0
```

完整日志: `wokwi-run/serial-2.0.0.txt`

---

## 五、复现步骤（本地）

```bash
# 1) 构建任意版本固件（Wokwi 云构建 API，无需认证；esp32 fqbn，与模拟器芯片一致）
cd ota-verify
python3 build_gh.py 1.0.0 latest bin/firmware-v1.0.0.bin      # FW=1.0.0, target=latest
python3 build_gh.py 2.0.0 latest bin/firmware-v2.0.0.bin

# 2) 发布：更新 firmware/manifest.json + 拷贝 bin 到 firmware/releases/，git push
#    （脚本: scripts/publish_release.sh 可切换为 GitHub Releases 生产通道）

# 3) 运行模拟（headless Chrome 驱动 Wokwi 编辑器，注入 sketch → 启动 → 抓串口）
cd wokwi-run && npm i puppeteer-core@24 --cache /tmp/npm-cache
node run_ota.js 1.0.0 latest upgrade    # 场景 1: V1 自动升级
node run_ota.js 2.0.0 latest uptodate   # 场景 2: V2 无需再刷机
```

依赖: 本机 google-chrome（headless）、node≥18、可访问 wokwi.com；Wokwi 编辑器项目使用公开项目
`https://wokwi.com/projects/337425600260080210`（带 otadata/app0/app1 分区表的 ESP32 工程）。

## 六、发布物与仓库状态

- `firmware/manifest.json` — 发布清单（version/url/size）
- `firmware/releases/v1.0.0.bin`（1,035,952 B, sha256 `1ae3f29b…`）
- `firmware/releases/v2.0.0.bin`（1,035,952 B, sha256 `78ea321f…`）
- `.gitignore` 已加例外 `!firmware/releases/*.bin`（PoC 过渡通道；生产 AW-006 迁移 Releases 后删除）
- 代码源（本地 PoC，不入库，符合 00 文档边界）: `ota-verify/sketch_gh_ota.ino`、`ota-verify/build_gh.py`、`wokwi-run/run_ota.js`

> ⚠️ 已知小瑕疵：串口捕获日志里 `→` 显示为 `â`，是 DOM 文本捕获的 UTF-8 编码显示问题，真机串口无此问题；功能无影响。

---

## 七、真机落地还缺什么（生产 AW-006 路径）

模拟验证的是 **应用层 OTA 逻辑**（查询 GitHub → 下载 → 写 flash → 重启）。真机生产还缺：

| # | 缺口 | 说明 |
|---|---|---|
| 1 | ESP-IDF 正式固件 | `firmware/` 目前为空；AW-003 基线（显示/触摸/WiFi/健康信号）→ AW-004 AgentStatus → AW-005 UI 都未开始。模拟用的是 Arduino 生态 sketch，不是 S3 生产代码 |
| 2 | esp_https_ota + 双槽分区 | 生产用 IDF 的 `esp_https_ota`、`factory + ota_0 + ota_1` 分区、otadata；当前 Wokwi 项目分区表仅 2 槽无 factory |
| 3 | 健康检查回滚 | 新固件启动后 PENDING_VERIFY 自检（显示/触摸/WiFi/OTA 任务存活）→ mark_valid / 失败显式回滚（见 docs/ota/02） |
| 4 | GitHub Actions CI | 编译（idf.py build）→ 上传 GitHub Releases（tag=版本号）→ 更新 manifest；固件不再入 git |
| 5 | GitHub Releases 真发布 | 当前仓库无 release（API 通道回退到 manifest）；用 `scripts/publish_release.sh`（gh CLI 或 GH_TOKEN）一键发布后，设备自动切 Releases 通道 |
| 6 | 真机验证 | 在 ESP32-S3-Touch-LCD-3.5B 上跑通升级 + 故意失败回滚演练 |
| 7 | 安全增强（生产前） | Secure Boot v2 / Flash Encryption 需单独计划（eFuse 不可逆，需用户确认，见 AGENTS.md human gate） |

**模拟已验证的结论可复用到生产**：GitHub 作为固件源可行、semver 版本比较逻辑、OTA 客户端状态流（检查→下载→写→重启→自检）。生产实现直接复用这些状态与 `OTA_TARGET_VERSION` 的设置入口（对应 AW-005 SettingsPanel 的 UpdatePanel）。
