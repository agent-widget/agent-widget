#!/usr/bin/env bash
# update-gh-aw006.sh — 把 AW-006（issue #6）标记完成（评论 + done label）。
# 需要 agent-widget 的 fine-grained PAT 具有 "Issues: Read and write" 权限
# （当前 pass github/agent-widget 的 PAT 只有 Issues 读权限，写被 403 拒绝）。
# 用法：在你自己的终端运行（或先更新 PAT 权限后我再跑）：
#   bash scripts/update-gh-aw006.sh
set -euo pipefail

GH="/home/linuxbrew/.linuxbrew/bin/gh"
export GH_TOKEN="$(pass show github/agent-widget)"

COMMENT='## ✅ AW-006 模拟环境 OTA 全链路完成（2026-08-31）

**完成范围**：QEMU + ESP-IDF 环境的 OTA 全链路验证（真机部分依赖 AW-002/003 硬件 bring-up，未在本任务）。

### 交付
- ESP-IDF 固件 firmware/：ota_manager（发现/manifest/流式 sha256/RSA 验签/安装）+ boot_health（PENDING_VERIFY 自检回滚）+ connectivity（openeth/wifi）+ mqtt_trigger（MQTT OTA 通知）+ app_console（UART 命令）
- QEMU 测试基础设施 firmware/test/qemu/scripts/（run_t1-t5/t5b/mqtt + harness + fixture server），证据 docs.local/operations/qemu-ota/evidence/
- Release pipeline：ESP-IDF board 构建 + sdkconfig 门禁 + fail-closed 签名（OTA_SIGNING_KEY 已配）+ manifest 带 sha256+signature
- Codex code review：REJECT→7 BLOCKING（B1-B7）全修→复跑全绿

### 测试结果（QEMU 真跑，7 项全 PASS）
T1 正常升级 3.0.0→3.1.0（PENDING_VERIFY→MARK_VALID→二次重启 VALID）
T2 坏 sha 拒绝（SHA_FAIL）｜T3 坏签名拒绝（SIGNATURE_FAIL）
T4 自检失败回滚（MARK_INVALID→回滚）｜T5 PENDING_VERIFY 断电 bootloader 回滚｜T5b 下载中断电
MQTT 触发 OTA（ota/announce→offer_candidate→升级成功）

### 遗留
- 真机 bring-up（AW-002/003）+ 真机升级/回滚演练
- 生产签名密钥轮换（当前 dev 密钥）
- IDF 本地 patch 升级时需重打'

"$GH" issue comment 6 --repo agent-widget/agent-widget --body "$COMMENT"
"$GH" issue edit 6 --repo agent-widget/agent-widget --add-label done
echo "AW-006 issue #6 updated: comment added + done label"
