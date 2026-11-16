# 接口与元数据定义（T03）

状态：草案，待负责人确认后锁定。
适用范围：知识库文档、片段、问答与会话接口的字段、标识与错误格式。
依据：[需求](requirements.md)、[架构](architecture.md)，以及 T01 核实记录（`docs/sources.md`，随 PR #4 合入）。

本文件只定义契约，不包含业务实现。实现由 T04（采集与解析）、T06（检索）、T07（回答）、T08（页面）分别完成。

## 目录

1. [设计原则](#设计原则)
2. [枚举与常量](#枚举与常量)
3. [文档元数据](#文档元数据)
4. [片段](#片段)
5. [标识、去重与更新](#标识去重与更新)
6. [问答接口](#问答接口)
7. [会话接口](#会话接口)
8. [管理接口与反馈](#管理接口与反馈t08-实现)
9. [错误格式](#错误格式)
10. [接口层的机型与依据规则](#接口层的机型与依据规则)
11. [版本与兼容](#版本与兼容)
12. [待确认事项](#待确认事项)
13. [对后续任务的约束](#对后续任务的约束)

## 设计原则

1. **机型硬隔离**：检索只能命中 `machines` 包含请求机型的文档；不得用另一机型的资料补全步骤。
2. **有据才答**：`answered` 必须至少带一条引用；无足够依据时返回 `insufficient_evidence` 或 `refused`，不得凭空生成维护步骤。
3. **来源可追溯**：引用包含文档标识、片段标识、原文链接、章节路径、官方更新时间与短引用。
4. **许可约束**：引用为原文短句（≤200 字符），接口不返回整段正文；正文只存在于运行时缓存，不入 Git（见 T01 决策）。
5. **时间双字段**：`official_updated_at` 来自官方（可为空），`retrieved_at` 是采集时间，二者不得互相替代。
6. **可更正**：会话中的机型、现象、已尝试步骤允许用户更正，旧机型的中断结论作废。
7. **稳定标识**：标识由内容与路径确定性生成，重复导入不产生新标识，内容变化产生新片段标识。

## 枚举与常量

### Machine（机型）

| 代码 | 显示名 | 说明 |
|---|---|---|
| `a1` | 拓竹 A1 | 仅 A1 的资料 |
| `a1_mini` | 拓竹 A1 mini | 仅 A1 mini 的资料 |

- 首版**不支持**其他机型；未知机型返回 `422 unsupported_machine`，不做近似映射。
- “通用资料”不是第三个枚举值，而是 `machines` 同时包含两个机型，且必须填写 `shared_reason`（见下）。
- T01 未发现官方明确标注“两款通用”的页面，因此共享文档默认为 0；字段保留以便将来确有依据时使用。

### Section（文档所属章节）

`maintenance`、`troubleshooting`、`manual`、`other`。

由官方路径的第二段推导（`/en/a1-mini/maintenance/...` → `maintenance`）；无法归类时用 `other`，不猜测。

### Locale（语言）

`zh`、`en`。仅这两种进入首版知识库；官方另有 22 个语言版本，暂不采集。

### AnswerStatus（回答状态）

| 值 | 含义 | 必须满足 |
|---|---|---|
| `answered` | 依据充分，直接回答 | `answer` 非空；`citations` ≥ 1；`refusal_reason` 为空 |
| `needs_clarification` | 缺少影响结论的条件，先追问 | `follow_up_question` 非空；`missing_information` ≥ 1；`citations` 为空 |
| `insufficient_evidence` | 有相关资料但不足以支持结论 | `answer` 非空（说明不足）；`citations` 可为空；`refusal_reason` 为空 |
| `refused` | 超出范围或不应回答 | `answer` 非空（说明原因）；`refusal_reason` 非空；`citations` 为空 |

判定优先级：`refused` > `needs_clarification` > `insufficient_evidence` > `answered`。

### MissingInformation（缺失条件）

`machine_conflict`、`phenomenon`、`trigger_condition`、`filament_material`、`already_tried`、`firmware_version`、`other`。

### RefusalReason（拒答原因）

| 值 | 使用场景 |
|---|---|
| `no_reliable_source` | 机型过滤后没有任何可用资料 |
| `out_of_scope` | 与 A1 / A1 mini 售后无关 |
| `unsafe_procedure` | 请求涉及绕过安全保护、改装或高风险操作 |
| `unsupported_machine` | 问题指向不支持的机型（与 422 错误不同：这里指自然语言里提到，服务仍正常返回） |

### MachineCheckResult（机型核对结果）

`match`（问题与所选机型一致）、`mismatch`（问题提到另一机型）、`unknown`（问题未提机型，按所选机型处理）。

## 文档元数据

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `doc_id` | string | 是 | `^doc_[0-9a-f]{16}$` | 由 `locale` 与规范化路径确定性生成 |
| `canonical_path` | string | 是 | `^[a-z0-9][a-z0-9/_-]*$` | 小写、无首尾斜杠、不含语言段 |
| `alias_paths` | string[] | 是 | 默认 `[]` | 大小写变体等重复路径，保留原始形式 |
| `locale` | Locale | 是 | `zh` / `en` | 文档语言；以实际正文检测为准，不直接信任官方字段 |
| `source_url` | string(uri) | 是 | 官方页面完整 URL | 引用与人工核对入口 |
| `title` | string | 是 | 1–300 字符 | 官方标题原文，不翻译、不改写 |
| `machines` | Machine[] | 是 | 1–2 个，不重复 | 文档适用机型 |
| `shared_reason` | string\|null | 条件必填 | 当 `machines` 含两个机型时非空 | 官方依据（正文位置或说明），不得凭推测填写 |
| `section` | Section | 是 | 见枚举 | 由路径推导 |
| `official_updated_at` | datetime\|null | 是 | RFC 3339，UTC | 官方更新时间；未知时为 `null`，不得用采集时间填充 |
| `retrieved_at` | datetime | 是 | RFC 3339，UTC | 采集时间 |
| `content_hash` | string | 是 | `sha256:` + 64 位十六进制 | 规范化正文的指纹，用于判断更新 |
| `enabled` | boolean | 是 | 默认 `true` | 停用后不进入检索，但保留记录 |
| `ingested_at` | datetime | 是 | RFC 3339，UTC | 最近一次入库时间 |

示例（不包含正文）：

```json
{
  "doc_id": "doc_5f1c0a7d2e9b3a41",
  "canonical_path": "a1-mini/troubleshooting/extruder-clog",
  "alias_paths": [],
  "locale": "zh",
  "source_url": "https://wiki.bambulab.com/zh/a1-mini/troubleshooting/extruder-clog",
  "title": "A1 系列挤出机清理教程",
  "machines": ["a1_mini"],
  "shared_reason": null,
  "section": "troubleshooting",
  "official_updated_at": "2026-11-10T08:19:17Z",
  "retrieved_at": "2026-11-15T10:42:03Z",
  "content_hash": "sha256:9f2c...（64 位）",
  "enabled": true,
  "ingested_at": "2026-11-15T10:42:09Z"
}
```

## 片段

片段是检索与引用的最小单位，按文档章节切分。

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `chunk_id` | string | 是 | `^doc_[0-9a-f]{16}#[0-9a-f]{10}$` | 片段标识，由正文指纹生成 |
| `doc_id` | string | 是 | 同文档 | 所属文档 |
| `ordinal` | integer | 是 | ≥ 0 | 文档内顺序，从 0 开始 |
| `heading_path` | string[] | 是 | 可为空数组 | 从二级标题到所属标题的原文路径 |
| `anchor` | string\|null | 是 | `^[a-z0-9-]+$` | 官方页面锚点，用于跳转 |
| `text` | string | 是 | 运行时字段 | 片段正文；**不写入仓库、不写入日志** |
| `char_count` | integer | 是 | ≥ 1 | 正文字符数 |
| `machines` | Machine[] | 是 | 继承文档 | 冗余存储，供机型过滤 |
| `locale` | Locale | 是 | 继承文档 | 冗余存储 |
| `official_updated_at` | datetime\|null | 是 | 继承文档 | 引用展示用 |
| `retrieved_at` | datetime | 是 | 继承文档 | 引用展示用 |

示例：

```json
{
  "chunk_id": "doc_5f1c0a7d2e9b3a41#a1b2c3d4e5",
  "doc_id": "doc_5f1c0a7d2e9b3a41",
  "ordinal": 3,
  "heading_path": ["拆装指引", "移除挤出机"],
  "anchor": "remove-extruder",
  "text": "（运行时存储，不进入仓库）",
  "char_count": 412,
  "machines": ["a1_mini"],
  "locale": "zh",
  "official_updated_at": "2026-11-10T08:19:17Z",
  "retrieved_at": "2026-11-15T10:42:03Z"
}
```

## 标识、去重与更新

### 标识生成

```text
canonical_path = lower(trim_slashes(percent_decode(path)))  # 不含 locale 段
doc_id         = "doc_" + sha256(locale + "\n" + canonical_path).hexdigest()[:16]
chunk_id       = doc_id + "#" + sha256(normalized_chunk_text).hexdigest()[:10]
content_hash   = "sha256:" + sha256(normalized_document_text).hexdigest()
```

规范化正文：去掉脚本与样式、压缩连续空白、保留标题层级与表格文本、图片只保留 URL 与图注。图片二进制不参与指纹。

### 去重

- 唯一键为 `(locale, canonical_path)`；同一键只保留一条文档。
- 大小写不同的路径视为同一文档；原始写法记入 `alias_paths`（T01 已发现 3 条大写路径）。
- 同一页面的不同语言版本是两条独立文档，不互译、不合并。
- 重复导入同一内容（`content_hash` 相同）时不重建片段，只更新 `retrieved_at`。

### 更新与删除

- 内容变化（`content_hash` 变化）：重建该文档的全部片段；`doc_id` 不变，旧 `chunk_id` 失效。
- 引用中若出现已失效的 `chunk_id`，回答不得继续展示该引用，须提示“资料已更新”并重新检索。
- 页面从官方清单消失或人工停用：`enabled = false`，从索引移除，记录保留以便审计；不物理删除。
- 删除后再出现：复用同一 `doc_id`，重新启用并重建片段。

## 问答接口

### `POST /api/v1/chat`

请求：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `question` | string | 是 | 1–2000 字符 | 用户问题原文，不做改写 |
| `machine` | Machine | 是 | 枚举内 | 用户选择的机型 |
| `session_id` | string\|null | 否 | `^s_[A-Za-z0-9]{16,32}$` | 省略则新建会话 |
| `locale` | Locale | 否 | 默认 `zh` | 回答语言；引用标题保留原文 |
| `request_id` | string\|null | 否 | ≤64 字符 | 客户端幂等标识，服务端回显 |

响应：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `request_id` | string | 是 | 回显或服务端生成 |
| `session_id` | string | 是 | 本次会话 |
| `status` | AnswerStatus | 是 | 见枚举与不变量 |
| `answer` | string | 是 | 回答正文；`needs_clarification` 时可为空字符串 |
| `citations` | Citation[] | 是 | 可为空数组 |
| `missing_information` | MissingInformation[] | 是 | 可为空数组 |
| `follow_up_question` | string\|null | 是 | 仅在 `needs_clarification` 时非空 |
| `refusal_reason` | RefusalReason\|null | 是 | 仅在 `refused` 时非空 |
| `machine_check` | MachineCheck | 是 | 机型核对结果 |
| `session` | SessionSummary | 是 | 更新后的会话摘要 |

`Citation`：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `chunk_id` | string | 是 | 片段标识 | 可定位到原文与版本 |
| `doc_id` | string | 是 | 文档标识 | |
| `title` | string | 是 | 原文标题 | 不翻译 |
| `source_url` | string(uri) | 是 | 官方完整 URL | |
| `section_path` | string[] | 是 | 可为空 | 与片段 `heading_path` 一致 |
| `anchor` | string\|null | 是 | | 跳转到章节 |
| `machine` | Machine | 是 | | 该引用所属文档的机型 |
| `official_updated_at` | datetime\|null | 是 | | 用户判断时效 |
| `quote` | string | 是 | 1–200 字符 | 原文短引用，须为模型可见的官方标题或正文子串 |
| `quote_truncated` | boolean | 是 | | 是否因长度截断 |

`MachineCheck`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `requested` | Machine | 请求机型 |
| `detected_in_question` | Machine[] | 问题文本中识别到的机型，可为空 |
| `result` | MachineCheckResult | `mismatch` 时状态必须为 `needs_clarification` |

### 不变量（测试与评审必须逐条覆盖）

1. `status = answered` ⇒ `citations.length ≥ 1` 且每条 `citations[].machine ∈ machines(请求机型)`。
2. `status = needs_clarification` ⇒ `follow_up_question` 非空且 `missing_information` 非空且 `citations` 为空。
3. `status = insufficient_evidence` ⇒ `answer` 说明缺什么，且不得包含具体维护步骤。
4. `status = refused` ⇒ `refusal_reason` 非空且 `citations` 为空。
5. `machine_check.result = mismatch` ⇒ 不得直接 `answered`。
6. 任何 `quote` 都必须是模型可见的官方标题或片段正文（当前最多前 1,200 字符）的连续子串（归一化空白），且长度 ≤ 200 字符。正文标记若无对应的有效摘录，整条 answered 降为 insufficient_evidence；这仍不等于语义蕴含校验。
7. 响应中的 `citations` 不得包含未启用的文档或已失效的片段。
8. 不得返回跨机型片段：`citations[].machine` 必须等于请求机型（共享文档除外，共享文档须同时列出两机型）。

以下示例只用于说明字段与状态，引用的标题、原文短句与时间均为示意值，不代表实际页面内容。真实取值由 T04 采集后产生。

### 示例 1：依据充分

请求：

```json
{
  "question": "A1 mini 挤出机堵料了，怎么清理？",
  "machine": "a1_mini",
  "locale": "zh"
}
```

响应：

```json
{
  "request_id": "req_01J8Z3K4",
  "session_id": "s_01J8Z3K4M2Q7",
  "status": "answered",
  "answer": "先断电并等待喷头降温，再按官方拆装指引取下挤出机组件清理。注意：不要带电操作加热部件。",
  "citations": [
    {
      "chunk_id": "doc_5f1c0a7d2e9b3a41#a1b2c3d4e5",
      "doc_id": "doc_5f1c0a7d2e9b3a41",
      "title": "A1 系列挤出机清理教程",
      "source_url": "https://wiki.bambulab.com/zh/a1-mini/troubleshooting/extruder-clog",
      "section_path": ["拆装指引"],
      "anchor": "remove-extruder",
      "machine": "a1_mini",
      "official_updated_at": "2026-11-10T08:19:17Z",
      "quote": "断电并等待喷头冷却后再拆卸挤出机组件。",
      "quote_truncated": false
    }
  ],
  "missing_information": [],
  "follow_up_question": null,
  "refusal_reason": null,
  "machine_check": { "requested": "a1_mini", "detected_in_question": ["a1_mini"], "result": "match" },
  "session": {
    "session_id": "s_01J8Z3K4M2Q7",
    "machine": "a1_mini",
    "reported_issue": "挤出机堵料",
    "attempted_steps": [],
    "updated_at": "2026-11-15T10:45:12Z"
  }
}
```

### 示例 2：机型冲突（追问）

请求：

```json
{ "question": "A1 mini 的热床怎么换？", "machine": "a1", "locale": "zh" }
```

响应：

```json
{
  "request_id": "req_01J8Z3K5",
  "session_id": "s_01J8Z3K5N3R8",
  "status": "needs_clarification",
  "answer": "",
  "citations": [],
  "missing_information": ["machine_conflict"],
  "follow_up_question": "你问的是 A1 还是 A1 mini？两者的热床拆装步骤不同，我需要确认后再查对应资料。",
  "refusal_reason": null,
  "machine_check": { "requested": "a1", "detected_in_question": ["a1_mini"], "result": "mismatch" },
  "session": {
    "session_id": "s_01J8Z3K5N3R8",
    "machine": "a1",
    "reported_issue": "热床更换",
    "attempted_steps": [],
    "updated_at": "2026-11-15T10:46:40Z"
  }
}
```

### 示例 3：资料不足

请求：

```json
{ "question": "A1 mini 打印 PA-CF 时封闭腔体温度应该设多少？", "machine": "a1_mini", "locale": "zh" }
```

响应：

```json
{
  "request_id": "req_01J8Z3K6",
  "session_id": "s_01J8Z3K6P4S9",
  "status": "insufficient_evidence",
  "answer": "现有官方资料没有给出 A1 mini 打印 PA-CF 时腔体温度的具体建议，因此无法给出温度数值。",
  "citations": [],
  "missing_information": ["filament_material"],
  "follow_up_question": null,
  "refusal_reason": null,
  "machine_check": { "requested": "a1_mini", "detected_in_question": ["a1_mini"], "result": "match" },
  "session": {
    "session_id": "s_01J8Z3K6P4S9",
    "machine": "a1_mini",
    "reported_issue": "PA-CF 腔体温度",
    "attempted_steps": [],
    "updated_at": "2026-11-15T10:47:05Z"
  }
}
```

### 示例 4：拒答

请求：

```json
{ "question": "怎么短接热床温控保护让它继续打印？", "machine": "a1", "locale": "zh" }
```

响应：

```json
{
  "request_id": "req_01J8Z3K7",
  "session_id": "s_01J8Z3K7Q5T0",
  "status": "refused",
  "answer": "短接温控保护属于绕过安全保护的操作，可能造成过热或火灾风险，我不能提供该步骤。若热床报温度异常，可以先按官方排障流程检查并联系官方支持。",
  "citations": [],
  "missing_information": [],
  "follow_up_question": null,
  "refusal_reason": "unsafe_procedure",
  "machine_check": { "requested": "a1", "detected_in_question": ["a1"], "result": "match" },
  "session": {
    "session_id": "s_01J8Z3K7Q5T0",
    "machine": "a1",
    "reported_issue": "热床温控保护",
    "attempted_steps": [],
    "updated_at": "2026-11-15T10:48:10Z"
  }
}
```

## 会话接口

会话用于多轮排障：记录机型、现象与已尝试步骤，并允许更正。

实现约定：更正机型时清空旧机型的现象、已尝试步骤和历史；同一次 PATCH 可提供新现象和步骤。
冲突机型提问不会成为首次现象。省略主语的追问可使用当前现象辅助检索，仍先检查本轮显式机型。

### `SessionSummary`（问答响应内嵌）

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_id` | string | 会话标识 |
| `machine` | Machine | 当前机型（可被更正） |
| `reported_issue` | string\|null | 首次描述的现象摘要，≤200 字符 |
| `attempted_steps` | string[] | 已尝试步骤，最多 10 条 |
| `updated_at` | datetime | 最近更新时间 |

### `GET /api/v1/sessions/{session_id}`

返回 `SessionSummary` 加 `corrections` 数组；`corrections` 每项为 `{field, from, to, at}`，用于审计用户更正。

### `PATCH /api/v1/sessions/{session_id}`

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `machine` | Machine\|null | 否 | 更正机型；此后旧机型结论作废 |
| `reported_issue` | string\|null | 否 | 更正现象描述 |
| `attempted_steps` | string[]\|null | 否 | 整体替换已尝试步骤，≤10 条 |

### `DELETE /api/v1/sessions/{session_id}`

删除会话与对话记录，用于用户撤回；返回 `204`。

### 保留期

当前实现（T08）：会话保存在服务进程内，空闲 30 分钟过期，服务重启即丢失。
持久化与更长的保留期需要 T09 的服务端存储方案，具体时长与隐私说明待负责人确认（见待确认事项）。

## 管理接口与反馈（T08 实现）

### `GET /api/v1/health`

返回 `{status, documents, chunks, model}`，用于页面与部署探活。

### `GET /api/v1/machines`

返回机型枚举与显示名：`[{"code": "a1", "label": "拓竹 A1"}, ...]`。

### `POST /api/v1/feedback`

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `session_id` | string | 是 | 会话标识 |
| `solved` | boolean | 是 | 是否解决 |
| `comment` | string\|null | 否 | ≤500 字符，自愿填写 |

返回 `{"id": 1}`。反馈写入运行时 SQLite 的 `feedback` 表。

### 管理接口（需要认证）

| 方法与路径 | 用途 | 请求/响应 |
|---|---|---|
| `GET /api/v1/admin/documents` | 资料状态 | 可选查询参数 `machine`；返回文档列表（含 `enabled`、`chunk_count`、官方更新时间） |
| `PATCH /api/v1/admin/documents/{doc_id}` | 启用/停用资料 | `{"enabled": false}`；返回更新后的文档 |
| `POST /api/v1/admin/refresh` | 手动更新资料 | `{"paths"?: string[], "limit"?: 1–20}`；同步执行采集解析，返回本次运行统计与失败列表 |
| `GET /api/v1/admin/feedback` | 反馈汇总 | 返回 `{total, solved, unsolved}` |

认证方式：请求头 `X-Admin-Token` 必须等于 `PRINTCARE_ADMIN_TOKEN`。
未配置令牌时，只有 `PRINTCARE_ENVIRONMENT=local` 的本机开发允许访问；
其他环境返回 `503 admin_not_configured`，令牌错误返回 `401 unauthorized`。

注意：

- `admin/refresh` 为同步接口，只适合小批量（≤20 篇）；大批量采集应使用命令行。
- 刷新完成后服务会重建内存检索索引；停用文档同样只影响本次进程的后续查询需重新加载。

## 错误格式

所有非 2xx 响应统一为：

```json
{
  "error": {
    "code": "invalid_request",
    "message": "machine 必须是 a1 或 a1_mini",
    "details": { "field": "machine" },
    "request_id": "req_01J8Z3K8"
  }
}
```

| `code` | HTTP | 触发条件 |
|---|---|---|
| `invalid_request` | 400 | JSON 非法、缺少必填字段、类型错误 |
| `validation_failed` | 422 | 字段存在但不满足约束（长度、格式、枚举） |
| `unsupported_machine` | 422 | `machine` 不在枚举内 |
| `session_not_found` | 404 | `session_id` 不存在或已过期 |
| `unauthorized` | 401 | 管理令牌缺失或错误 |
| `admin_not_configured` | 503 | 非 local 环境未配置管理令牌 |
| `not_found` | 404 | 管理资源（如文档）不存在 |
| `payload_too_large` | 413 | 请求体超过限制 |
| `rate_limited` | 429 | 超过频率限制；需带 `Retry-After` |
| `source_unavailable` | 503 | 依赖的资料服务不可用，且无缓存可用 |
| `internal_error` | 500 | 未预期错误；不得在 `message` 中回显内部细节 |

约束：

- `message` 面向用户，可读、不包含堆栈、路径、密钥或正文。
- `details` 只放字段名与允许值，不放用户输入原文。
- 每个响应带 `X-Request-Id`，与 `error.request_id` 一致，便于排查。

## 接口层的机型与依据规则

1. `machine` 是硬过滤条件，先于关键词与向量检索生效；不得先检索再过滤（避免跨机型片段进入候选）。
2. 问题中出现的机型与请求机型不一致时，先追问，不自动切换机型（用户可能选错，也可能问错）。
3. 命中资料只覆盖另一机型时，视为“无可用资料”，返回 `refused` + `no_reliable_source`，不借用另一机型步骤。
4. `answered` 的每个结论句都必须能对应到至少一条引用；无法对应的句子应删除或降级为 `insufficient_evidence`。
5. 涉及拆机、加热、电源、安全保护的步骤，必须在回答中保留官方安全前提；官方资料未给安全前提时不得补写。
6. 引用只展示短句，长步骤用“见原文对应章节”并给出链接，避免整段转载。

## 版本与兼容

- 路径前缀 `/api/v1`；`v1` 内只做向后兼容变更。
- 允许：新增可选请求字段、新增响应字段、新增枚举值（客户端须容忍未知枚举）。
- 不允许（需 `/v2`）：删除或改名已有字段、改变字段语义、收紧必填约束。
- 知识库元数据字段的变更需同步更新本文件与迁移说明。

## 待确认事项

1. `quote` 上限 200 字符是否符合许可与展示需要。
2. 会话保留期（默认 30 天）与删除粒度（整会话删除是否满足撤回要求）。
3. 是否需要英文回答（`locale=en`）进入首版；当前默认中文。
4. `shared_reason` 的判定标准：是否需要负责人人工签署才能把文档标为两款通用。
5. 是否需要在 `v1` 增加知识库管理接口（T08），当前只定义问答与会话。
6. 反馈（是否解决）字段是否并入本契约，或留到 T08 单独定义。

## 对后续任务的约束

- **T04**：按本文生成 `doc_id` / `chunk_id` / `content_hash`；保留 `heading_path`、`anchor`、图片 URL 与图注；正文只存运行时目录，不入 Git。
- **T06**：检索前执行机型硬过滤；返回片段必须带 `machines`、`official_updated_at`、`retrieved_at`，供接口直接组装引用。
- **T07**：按不变量实现状态判定；`answered` 逐句对齐引用；`mismatch` 必须追问；无依据时返回 `insufficient_evidence` 或 `refused`。
- **T08**：页面按 `status` 渲染不同区块（引用、追问、资料不足、拒答），并支持会话更正与删除。
