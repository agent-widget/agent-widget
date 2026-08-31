> English version: [09-github-actions-release-pipeline.md](./09-github-actions-release-pipeline.md)

# 09-GitHub Actions release pipeline（已配置）

> 日期: 2026-08-30
> 状态: ✅ 已推送并**验证通过**（run #33344266887 success，2026-08-30）：推 tag v2.0.0 → Actions 自动构建（arduino-cli）→ 创建 Release + 上传 firmware-v2.0.0.bin（1,026,560 B，magic 0xE9）→ manifest 自动更新。设备模拟端已确认走 GitHub Releases API 通道完成 OTA 升级（V1.0.0 → V2.0.0）。

---

## 一、做了什么

把「发布固件」从手动变成自动化。流程：

```
推 tag vX.Y.Z (main)  ──▶  GitHub Actions
                            ├─ 1. 解析版本号 (v2.0.0 → 2.0.0)
                            ├─ 2. 构建: ota-sim/build_arduino.sh（arduino-cli 本地编译，esp32 core 3.x + 自定义 OTA 双槽分区表）
                            ├─ 3. 创建 GitHub Release + 上传 firmware-vX.Y.Z.bin
                            └─ 4. 更新 firmware/manifest.json（回退通道，提交回 main）
设备侧: 启动 → GitHub Releases API 发现新版本 → 自动 OTA 升级
```

## 二、新增文件

| 文件 | 作用 |
|---|---|
| `.github/workflows/release.yml` | 触发：push tag `v*` 或手动 workflow_dispatch；用 GITHUB_TOKEN（无需用户凭据） |
| `ota-sim/sketch_gh_ota.ino` | 版本感知 OTA 客户端源（Arduino PoC，入库供 CI 构建） |
| `ota-sim/build_arduino.sh` | arduino-cli 本地编译（esp32 core 3.x + OTA 双槽分区表；`./build_arduino.sh <ver>`） |
| `ota-sim/custom_partitions.csv` | OTA 分区表（nvs/otadata/app0/app1/spiffs） |
| `ota-sim/build_gh.py` | （备用）Wokwi 云构建脚本 |
| `ota-sim/update_manifest.py` | 更新 manifest.json（新增/排序/替换条目） |
| `ota-sim/README.md` | 使用说明 |

## 三、如何使用

```bash
# 发布 v3.0.0（假设代码已在 main）:
git tag v3.0.0 && git push origin v3.0.0
# → Actions 自动构建 + 发布，设备下次启动自动发现升级
```

手动触发（GitHub Web: Actions → Release firmware → Run workflow，填 version；**需要该 tag 已存在**）。

## 四、边界与后续（AW-006）

- 当前构建是 **Arduino PoC**（arduino-cli 编译 app 镜像 + OTA 双槽分区表，模拟器/Wokwi 同路径）。生产替换点：workflow 的 build 步骤换成 ESP-IDF `idf.py build`，其余发布/清单逻辑不变。
- 真机刷机需要分区表配合（模拟器由项目 partitions.csv 控制；ESP-IDF 阶段由 sdkconfig 分区表控制）。
- 仓库的 `firmware/releases/*.bin`（raw 直链）与 manifest 仍保留为回退通道；Releases 发布后设备优先走 Releases API。生产期删除 raw 通道 + `.gitignore` 例外。
- Actions 运行状态可在仓库 Actions 页查看；release 结果公开可查（`GET /repos/agent-widget/agent-widget/releases`）。

## 五、验证结果（2026-08-30 已执行）

✅ 推 tag v2.0.0 → run #33344266887 **success**：
1. Actions 构建固件（arduino-cli，含 OTA 双槽分区表）
2. Release v2.0.0 发布，资产 firmware-v2.0.0.bin（1,026,560 B，magic 0xE9，sha256 3e3eadc1…）
3. manifest.json 自动更新（releases 列表：2.0.0, 1.0.0，URL 指向 Release 下载）
4. Wokwi 模拟端确认 `[OTA] Channel: GitHub Releases API` → 下载 Release 资产 → Update SUCCESS → 重启 V2.0.0 → `No update needed`（模拟串口证据：`wokwi-run/serial-1.0.0.txt`）

> 第一次触发失败根因：Wokwi 云构建 API 从 GitHub runner IP 不可用 → 改用 arduino-cli 本地编译（自包含）。
