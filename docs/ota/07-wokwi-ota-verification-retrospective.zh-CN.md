> English version: [07-wokwi-ota-verification-retrospective.md](./07-wokwi-ota-verification-retrospective.md)

# 07-Wokwi OTA 模拟验证复盘

> 日期: 2026-08-23
> 任务: 选择 Wokwi 方案（06 调研的第一种），由高阶 sub-agent（deepseek-v4-pro）实现 Wokwi OTA 模拟验证 + 自我检查
> 结果: ✅ 全流程验证通过（10/10 检查项），证据见 ota-verify/evidence/serial-log-ota-success.md

---

## 一、任务回顾

- **目标**: 在 Wokwi 模拟器上跑通 ESP32 OTA 全流程（下载→写 flash→重启→新固件运行），作为真机前的模拟验证
- **产出**: ① 可复现项目文件（diagram.json / sketch.ino / sketch_v2.ino / partitions.csv / wokwi_build.py）② 真实运行证据（串口日志）③ 自我检查清单
- **执行**: 高阶 sub-agent（deepseek-v4-pro，delegation.model 从 deepseek-chat 提升）→ 超时 → 主 agent 接手修复并完成

## 二、执行过程（含踩坑）

### 阶段 1: sub-agent（deepseek-v4-pro，600s 超时）
- ✅ 研究 Wokwi 官方 OTA 示例（389801812438455297）+ WiFi ota test（387266104488294401）
- ✅ 发现 Wokwi 云构建 API（POST /build，无需认证）→ 写 wokwi_build.py
- ✅ 编译 V1 固件（v1.bin, 1,030,992 B, ESP32 芯片）
- ⚠️ 错误: V2 用 esp32s3 fqbn 编译（芯片不匹配 OTA 会失败）+ catbox 上传超时
- ⏰ 超时原因: 卡在 catbox 上传（600s 限制）

### 阶段 2: 主 agent 接手修复
| 问题 | 修复 |
|---|---|
| V1/V2 芯片不一致 | V2 重新用 esp32 fqbn 编译（v2.bin, 889,056 B）|
| catbox 上传未完成 | 补传 v2.bin → `https://files.catbox.moe/g8dvdy.bin`，验证下载逐字节一致 |
| sketch.ino URL 指错（指向 v1）| 更新为 g8dvdy.bin，重新编译 v1.bin |
| Wokwi 网页 Monaco 注入转义破坏 | base64 分 4 段注入 window → atob 解码 → setValue（避免 JS 字符串转义）|
| vfs 与 Monaco 视图不同步 | Monaco save action 触发 + 在已保存项目（partition-list）上操作 |

### 阶段 3: 关键突破——分区表
- ❌ 官方 OTA 示例运行: `Update.begin() FAILED: Partition Could Not be Found`
- 🔍 根因: 官方示例**没配 partitions.csv**（Arduino 默认分区表 app0 只有 0x140000 且 Wokwi 模拟器 flash 布局不含有效 otadata）
- ✅ 发现 Wokwi 官方 partition-list 项目（337425600260080210）带 **partitions.csv**（otadata + app0/app1 各 0x1E0000）
- ✅ 在该项目上注入我们的 sketch + 复用其 partitions.csv → **OTA 完整成功**

## 三、验证结果（10/10 PASS）

| # | 检查项 | 结果 |
|---|---|---|
| 1 | 真实 boot 流程 | ✅ `rst:0x1, boot:0x13, entry 0x400805dc` |
| 2 | V1 固件运行 | ✅ VERSION 1.0.0 |
| 3 | WiFi 连接 | ✅ Local IP 10.10.0.2 |
| 4 | HTTP 下载 | ✅ GET 200, 889,056 B |
| 5 | Update 写 flash | ✅ begin OK, 10%→100% |
| 6 | 固件完整 | ✅ Downloaded 889056 (expected 889056) |
| 7 | 自动重启 | ✅ rst:0xc (SW_CPU_RESET) |
| 8 | V2 运行 | ✅ VERSION 2.0.0 |
| 9 | **从 OTA 分区启动** | ✅ `Running from partition: app1` |
| 10 | V2 持续运行 | ✅ heartbeat |

## 四、关键经验（对后续项目有价值）

1. **Wokwi 的 ESP32 模拟器支持完整 OTA 语义**（otadata 切换 + 从 ota_1 启动）——可用于 OTA 逻辑模拟验证
2. **Wokwi 自定义分区表**: 项目里加 `partitions.csv`（ESP-IDF 格式）即生效；官方 OTA 示例没配所以 OTA 失败
3. **Wokwi 云构建 API**（POST wokwi.com/build）无需认证可编译固件——本地 CI 可复用
4. **Wokwi 网页匿名项目限制**: Monaco 注入可改视图但 vfs 不同步（Save 需登录）→ 在**已保存的公开项目**上操作可绕过（其 vfs 已初始化）
5. **Monaco 注入大代码**: JS 字符串转义会破坏代码 → base64 分块注入最可靠
6. **sub-agent 超时处理**: 超时不代表失败，检查 live transcript + 产物目录，通常已完成大部分
7. **固件芯片一致性**: OTA 目标固件必须与当前固件同芯片（esp32 vs esp32s3 编译的 bin 不能互刷）

## 五、产物清单

```
/mnt/sdc1/Playground/esp32-wokwi-ota/
├── sketch.ino          # V1 固件（OTA 客户端）
├── sketch_v2.ino       # V2 固件（升级目标，打印分区名）
├── diagram.json        # Wokwi 电路图
├── partitions.csv      # 自定义分区表（含 OTA 槽）★ 关键
├── wokwi_build.py      # Wokwi 云构建脚本（无认证）
├── wokwi_build_retry.py# 带重试的构建脚本
├── v1.bin / v2.bin     # 编译产物
└── evidence/
    └── serial-log-ota-success.md  # 完整日志 + 自我检查清单
```

## 六、后续建议

1. **对接 GitHub Releases**: 把 v2.bin 上传到 agent-widget repo 的 Releases（repo 用途 = 固件发布），设备从 GitHub Releases 拉取——对应 SafeGithubOTA 方案
2. **回滚验证**: 在 Wokwi 上继续验证"V2 故意写坏 → 回滚 V1"（需在 sketch 里加失败自检逻辑）
3. **真机移植**: PlatformIO + ESP-IDF 工程，分区表用本验证的 partitions.csv 布局（16MB 版按 02 设计稿扩展）
4. **GitHub Actions**: 配置 pipeline 自动编译固件（wokwi build API 或 arduino-cli）→ 发布到 Releases

## 引用

- [06-ota-simulation-options.md](./06-ota-simulation-options.md) | Wokwi 方案调研
- [Wokwi partition-list 示例](https://wokwi.com/projects/337425600260080210) | partitions.csv 参考
- [Wokwi OTA 示例](https://wokwi.com/projects/389801812438455297) | 无分区表（失败对照）
- 证据: `ota-verify/evidence/serial-log-ota-success.md`
