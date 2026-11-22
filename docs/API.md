# 接口与证据

- `GET /api/health` 返回项目和规则版本。
- `GET /api/{模块}/{样例}` 单独计算到该阶段。模块与样例见深度登记。`signoff` 与 `mailings` 可加 `?scope=V3,V3-B` 指定签核采用的分支范围。
- `POST /api/runs` 接收 `{"sample":"clean"}`、`{"sample":"dirty"}` 或 `{"data":{…}}`，返回完整计算和归档 ID。
- `GET /api/runs/{id}` 查询不可变归档。`POST /api/runs/{id}/rerun` 用归档输入与当前规则运行。相同规则与来源复用原记录。
- `GET /api/runs/{id}/export` 下载 JSON 证据。内含批次设置、各输入表、原行号、各阶段计算及规则版本。

## 签核卷

签核卷由归档运行生成，按轮次追加，不回写原归档。

- `POST /api/runs/{id}/signoff` 接收 `{"scope":["V3","V3-B"]}`，缺省收齐全部并行末版。按采用范围形成可交（`ready`）或待补（`supplement`）的卷，返回 `items`、`omitted`、`totals`、`mailings` 等。
- `GET /api/runs/{id}/signoff` 取当前卷；`GET /api/runs/{id}/signoff/history` 列全部轮次。
- `GET /api/runs/{id}/signoff/{volume_id}` 查询单轮；`/export` 下载该轮证据；`/history/export` 下载整条签核历史。
- `GET /api/runs/{id}/signoff/{volume_id}/mailings` 返回该轮的寄送结果。只有签核完成的意见所在记录可标记 `ready`，其余一律 `held`，且 `sendable` 反映整卷状态。
- `POST /api/runs/{id}/signoff/{volume_id}/restore` 以新轮次恢复旧卷内容，旧轮次与原始依据不删除。

重跑同一批（相同运行、范围与状态）只返回原轮次并标 `reused`，不新增重复记录。每轮保存 `scope`、`status`、`parent`、`restored_from`、`created_at`，并附原始输入摘要与规则版本。

行号从 1 开始，按各 JSON 数组的位置计。归档键由项目、规则版本、来源名和规范化输入 JSON 计算。输入摘要为规范化 JSON 的 SHA-256。耗时与生成时刻只在首次提交时落库，便于重启后比较同一份记录。
