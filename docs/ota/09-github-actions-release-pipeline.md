# 09-GitHub Actions release pipeline（已配置）

> 日期: 2026-08-30
> 状态: ✅ 已推送仓库（commit 308accd）；验证触发需打 tag（见文末「如何触发」）

---

## 一、做了什么

把「发布固件」从手动变成自动化。流程：

```
推 tag vX.Y.Z (main)  ──▶  GitHub Actions
                            ├─ 1. 解析版本号 (v2.0.0 → 2.0.0)
                            ├─ 2. 构建: ota-sim/build_gh.py（Wokwi 云构建 API，零依赖）
                            ├─ 3. 创建 GitHub Release + 上传 firmware-vX.Y.Z.bin
                            └─ 4. 更新 firmware/manifest.json（回退通道，提交回 main）
设备侧: 启动 → GitHub Releases API 发现新版本 → 自动 OTA 升级
```

## 二、新增文件

| 文件 | 作用 |
|---|---|
| `.github/workflows/release.yml` | 触发：push tag `v*` 或手动 workflow_dispatch；用 GITHUB_TOKEN（无需用户凭据） |
| `ota-sim/sketch_gh_ota.ino` | 版本感知 OTA 客户端源（Arduino PoC，入库供 CI 构建） |
| `ota-sim/build_gh.py` | Wokwi 云构建脚本（`python3 build_gh.py <ver> <target> <out.bin>`） |
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

- 当前构建是 **Arduino PoC**（Wokwi 云构建 API 编译 app 镜像），与模拟验证完全同路径。生产替换点：workflow 第 2 步换成 ESP-IDF `idf.py build`，其余发布/清单逻辑不变。
- 真机刷机需要分区表配合（模拟器由项目 partitions.csv 控制；ESP-IDF 阶段由 sdkconfig 分区表控制）。
- 仓库的 `firmware/releases/*.bin`（raw 直链）与 manifest 仍保留为回退通道；Releases 发布后设备优先走 Releases API。生产期删除 raw 通道 + `.gitignore` 例外。
- Actions 运行状态可在仓库 Actions 页查看；release 结果公开可查（`GET /repos/agent-widget/agent-widget/releases`）。

## 五、验证方式

打一个 tag（如 `v2.0.0`）触发 workflow，然后检查：
1. Actions 运行变绿
2. `https://github.com/agent-widget/agent-widget/releases` 出现 v2.0.0 + firmware-v2.0.0.bin 资产
3. manifest.json 自动更新（新增 v2.0.0 条目）
4. （可选）重新跑 Wokwi 模拟：设备将打印 `[OTA] Channel: GitHub Releases API`（不再回退 manifest）
