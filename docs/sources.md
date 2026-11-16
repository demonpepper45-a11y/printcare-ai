# 资料来源核实记录（T01）

状态：已完成初步核实；许可与官方确认事项未解决，首批范围待负责人确认。

核实时间：2026-11-15。核实对象：拓竹（Bambu Lab）官方 Wiki 的 A1 与 A1 mini 资料。
本文只记录可复核的事实与判断，不存放官方正文副本。

## 结论摘要

1. 官方 Wiki 可公开访问，A1 与 A1 mini 各有独立的英文、中文分节，页面为服务端渲染，可解析出正文、章节、表格和图片链接。
2. Wiki.js 提供公开 GraphQL 接口，可一次取得全站 66,462 篇页面的路径、标题、语言和官方更新时间；但**正文接口需授权**，因此正文只能抓 HTML。
3. 官方更新时间**可得且一致**：GraphQL `updatedAt` 与站点地图 `lastmod` 对同一页面取值相同，最早 2024-05-28，最新 2026-11-13。
4. 机型归属必须来自 URL 路径，不能只靠标题或正文：同一主题在 A1 与 A1 mini 下是完全不同的两篇文章，且标题常写“A1 Series”。
5. 错误码（HMS）在两个机型之间**完全不重叠**（A1 18 篇、A1 mini 15 篇，交集 0），必须按机型隔离。
6. 未找到 Wiki 的内容许可声明；站点 `/policies` 被 robots 禁止抓取。在获得人工确认前，只保存链接、元数据与必要短引用，不保存或再发布全文副本。
7. 首批建议 42 篇（每机型 21 篇），已逐条验证 42 个英文 URL 均返回 HTTP 200，且都有对应中文版本。

## 官方入口与访问规则

| 入口 | URL | 核实结果 |
|---|---|---|
| 官方 Wiki | https://wiki.bambulab.com/en/home | HTTP 200，可公开访问 |
| Wiki 站点地图 | https://wiki.bambulab.com/sitemap.xml | HTTP 200，10.08 MB，67,421 条 `<url>`，每条都有 `<lastmod>` |
| Wiki GraphQL | https://wiki.bambulab.com/graphql（POST） | HTTP 200，可查询页面清单；单页正文返回 `PageViewForbidden 6013` |
| Wiki robots | https://wiki.bambulab.com/robots.txt | HTTP 200，**0 字节**（无规则） |
| 官网/商店 robots | https://bambulab.com/robots.txt | `Allow: /`；`Disallow: /policies`、`/*/policies`、`/my`、`/sign-in`、`/sign-up`、`/family-hub` |
| 使用条款 | https://bambulab.com/en-us/policies/terms | 被 `Disallow: /policies` 覆盖；自动抓取返回 403 |

注意：

- `robots.txt` 没有规则不等于授权；`/policies` 明确禁止，因此条款内容未抓取，许可状态只能标为“未确认”。
- 站点地图既用于发现页面，也应作为更新监控的输入；但它不是严格合法 XML：第 16429 行附近有一个未转义的 `&`（发布说明 URL `2-1-3&V2-1-0-0`），严格 XML 解析器会报错，需要容错解析或改用 GraphQL 清单。

## 数据接口能力

```graphql
query { pages { list { id path title updatedAt locale } } }
```

- 返回 66,462 条记录，覆盖 24 个语言版本（zh 3,286、en 3,232、de 3,160、pt-br 3,160、fr 3,159、it 3,158 等）。
- 字段：`id`、`path`、`title`、`updatedAt`、`locale`。路径按语言重复出现，因此文档唯一键应为 `(locale, path)`。
- 单页正文查询（`pages { singleByPath(...) { content } }`）返回 `You are not authorized to view this page`（`PageViewForbidden 6013`），匿名不可用；正文抓取走 HTML。
- 页面 HTML 为服务端渲染（样例页正文约 3,199 词），含 `h2/h3`、表格、图片与图注；无页脚版权声明、无 `last updated` 字样。

## 许可与再分发

- Wiki 没有版权声明、许可协议或转载说明；仓库内也没有可引用的许可页面。
- 官网把 `/policies`（含使用条款）设为禁止抓取，无法自动取得条款原文。
- **当前策略（负责人 2026-11-15 确认；许可确认后复核）**：
  - 仓库只提交 URL、标题、机型、语言、官方更新时间等元数据；
  - 正文片段实际保存于本地运行时 SQLite，不提交 Git；图片二进制不由当前管道存储。该缓存与对外使用范围仍待许可确认；
  - 回答中引用原文时只用短引用并附来源链接，不整段复制；
  - 不得把资料再分发给第三方。
- 需要负责人确认：是否可以存储正文副本、是否可以在产品中展示原文摘录、是否需要向厂商申请书面许可。

## 机型覆盖与数量（`locale=en`，按路径前缀统计）

| 机型 | 页面数 | maintenance | troubleshooting | manual | 其他 | 更新时间范围 |
|---|---|---|---|---|---|---|
| A1 | 93 | 48 | 26（含 18 篇 HMS） | 18 | 1（screen-operation） | 2024-05-28 → 2026-11-11 |
| A1 mini | 84 | 39 | 25（含 15 篇 HMS） | 16 | 4（midi、purge-wiper、camera、th-board 各 1） | 2024-05-28 → 2026-11-11 |

中文版：A1 89 篇、A1 mini 85 篇，最新更新到 2026-11-13，结构与英文版大体对应（个别页面章节数不同，见下例）。

## 机型隔离证据（对检索与回答的硬约束）

1. **HMS 错误码不重叠**：A1 18 个、A1 mini 15 个，交集为空。同一条错误码不能跨机型复用。
2. **同名主题是两篇文章**：21 个共享 slug（如 `maintenance/belt_tension`、`maintenance/x-axis`、`maintenance/bottom-base`），但内容不同：
   - `troubleshooting/circuit-fault`：A1 版 1,807 词、7 个二级标题、11 张图；A1 mini 版 2,260 词、8 个二级标题、20 张图；两版章节结构不同（A1 分“电源开关指示灯灭/亮”，A1 mini 分“屏幕不亮、HMS 指示灯亮/灭”）。
   - 两版正文几乎不互相提及对方机型（A1 版提及 “A1 mini” 0 次；A1 mini 版提及 9 次，属自述）。
3. **标题不能作为机型依据**：`a1-mini/maintenance/hotend_blob` 标题是 “Hotend Clumping/Blob Cleaning Instructions-A1”；`a1-mini/troubleshooting/nozzle-clog` 标题是 “A1/A1 mini Nozzle/Hotend Unclogging Procedure”；`a1/troubleshooting/homing-leveling-failure` 标题写 “A1 series”。机型一律取自路径，并保留原始标题与 URL 供引用。
4. **`A1 Series` 不等于通用**：多个页面标题写 “A1 Series”（挤出机、热端、风扇等），但落在单一机型路径下，正文步骤与拆装对象不同，不能当作两机型通用资料。通用资料必须另有明确标注，目前未在 Wiki 中发现这样的标注。

## 解析样例（5 篇，均为英文页）

| 页面 | 正文词数 | 二级标题 | 三级标题 | 图片 | 表格 | 观察 |
|---|---|---|---|---|---|---|
| `a1-mini/maintenance/period-maintenance` | 3,199 | 4 | — | 52 | 32 | 维护总览页，大量表格链接到子页面；适合做索引而非答案来源 |
| `a1-mini/troubleshooting/extruder-clog` | 872 | 6 | 13 | 42 | 16 | 步骤高度依赖图片，42 张图**全部无 alt**；纯文本抽取会丢失关键动作 |
| `a1-mini/maintenance/clean-hotend-assembly` | 405 | 4 | 4 | 10 | 0 | 图片 alt 为中文（如“按压切刀1.jpg”），说明英文页内也混用中文素材 |
| `a1/troubleshooting/circuit-fault` | 1,807 | 7 | — | 11 | — | 含 “Safety Warning”“Required Tools and Materials” 章节，安全前提可保留 |
| `a1-mini/troubleshooting/extruder-clog`（中文版） | 170 | 5 | 9 | 41 | 16 | 中文版正文明显更短（170 词），信息主要靠图片；中英文不可互相替代 |

其他数据质量发现：

- `locale=en` 中混入德语、西班牙语、法语页面（如 `a1/maintenance/heatbed-replacement-guide-DE/-ES/-FR`），语言字段不能直接信任，需要检测标题/正文语言。
- 路径大小写不一致：3 条中文页面以大写开头（`A1-mini/maintenance`、`A1-mini/Midi`、`A1/troubleshooting/hmscode/1200_1200_0001_0001`），可能重复收录同一文档；去重时需统一小写。
- 存在 `(locale, path)` 完全重复的记录（抽查其他机型段已发现至少 5 条，A1 段本次未见），入库前需去重。
- 部分维护页图片可下载但体积大、无图注；仅靠文本无法复现操作步骤，需要在界面上展示原图或链接。

## 首批 42 篇建议清单

选取规则：每机型 8 篇维护、5 篇排障、6 条 HMS 错误码、2 篇手册；优先覆盖安全前提、常见故障与高频维护。全部 42 个英文 URL 于 2026-11-15 逐条验证返回 HTTP 200，且均有中文版本。

### A1 mini（21 篇）

| 路径（`https://wiki.bambulab.com/en/` 之后） | 标题（截断） | 官方更新 | 中文版 |
|---|---|---|---|
| `a1-mini/maintenance/period-maintenance` | A1 mini Maintenance Guidelines | 2026-11-11 | 有 |
| `a1-mini/maintenance/clean-hotend-assembly` | Nozzle stuck – hotend residue adhesion | 2026-08-13 | 有 |
| `a1-mini/maintenance/hotend_blob` | Hotend Clumping/Blob Cleaning Instructions-A1 | 2026-11-10 | 有 |
| `a1-mini/maintenance/ptfe-tube` | A1 series Printer PTFE Tube Removal | 2026-11-10 | 有 |
| `a1-mini/maintenance/belt_tension` | A1 mini Belt Tensioning | 2026-11-10 | 有 |
| `a1-mini/maintenance/lubricate-y-axis` | Guide on how to lubricate the A1 mini Y-axis guide rail | 2026-11-10 | 有 |
| `a1-mini/maintenance/filament-sensor-base-replacement` | A1 series Filament Sensor Base Replacement Guide | 2026-11-10 | 有 |
| `a1-mini/maintenance/x-axis` | A1 mini X-axis Assembly Installation Tutorial | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/circuit-fault` | Printer Circuit Failure Troubleshooting – A1 Mini | 2026-06-22 | 有 |
| `a1-mini/troubleshooting/extruder-clog` | A1 series extruder cleaning tutorial | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/heatbed-not-heat-up` | A1 Mini HeatBed Temperature Abnormality Troubleshooting | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/print-issues-troubleshooting` | A1 Series First Layer Print Issues | 2026-11-11 | 有 |
| `a1-mini/troubleshooting/nozzle-clog` | A1/A1 mini Nozzle/Hotend Unclogging Procedure | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/hmscode/0300_0200_0001_0009` | HMS_0300-0200-0001-0009 喷头温控异常 | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/hmscode/0300_1800_0001_0001` | HMS_0300-1800-0001-0001 挤出机涡流传感器值过小 | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/hmscode/0300_1800_0001_0002` | HMS_0300-1800-0001-0002 挤出机涡流传感器灵敏度异常 | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/hmscode/0300_1800_0001_0003` | HMS_0300-1800-0001-0003 挤出力传感器不可用 | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/hmscode/0300_1800_0001_0004` | HMS_0300-1800-0001-0004 挤出机涡流传感器信号异常 | 2026-11-10 | 有 |
| `a1-mini/troubleshooting/hmscode/0300_1900_0001_0001` | HMS_0300-1900-0001-0001 Y 轴涡流传感器不可用 | 2026-03-30 | 有 |
| `a1-mini/manual` | A1 mini manual | 2026-07-06 | 有 |
| `a1-mini/manual/faq` | A1 mini FAQ | 2026-11-10 | 有 |

### A1（21 篇）

| 路径（`https://wiki.bambulab.com/en/` 之后） | 标题（截断） | 官方更新 | 中文版 |
|---|---|---|---|
| `a1/maintenance/basic-maintenance` | A1 Maintenance Guidelines | 2026-10-12 | 有 |
| `a1/maintenance/heatbed` | A1 Heatbed Replacement Guide | 2026-10-14 | 有 |
| `a1/maintenance/replace-hotend` | Hotend Replacement for A1 Series | 2026-08-24 | 有 |
| `a1/maintenance/hotend_blob_without_hotend_heating` | Hotend Blob/Clump Cleaning Instructions with Hotend Heating Abnormal | 2025-10-09 | 有 |
| `a1/maintenance/belt_tension` | A1 Belt Tensioning | 2026-11-10 | 有 |
| `a1/maintenance/lubricate-y-axis` | Guide on how to lubricate the A1 Y-axis guide rail | 2026-11-10 | 有 |
| `a1/maintenance/x-axis` | A1 X-axis Assembly Installation Tutorial | 2026-11-03 | 有 |
| `a1/maintenance/heatbed-sensor` | A1 Heatbed Sensor Installation Tutorial | 2025-05-19 | 有 |
| `a1/troubleshooting/circuit-fault` | Printer Circuit Failure Troubleshooting - A1 | 2026-07-06 | 有 |
| `a1/troubleshooting/heatbed-not-heat-up` | Troubleshooting guide for A1 heatbed not heating up | 2026-07-14 | 有 |
| `a1/troubleshooting/homing-leveling-failure` | Homing and leveling failure troubleshooting guide for A1 series | 2026-11-10 | 有 |
| `a1/troubleshooting/screen-not-working-as-expected` | A1 - Screen Anomaly Troubleshooting | 2026-07-15 | 有 |
| `a1/troubleshooting/upgrade-fail` | A Series Upgrade Failed | 2026-06-02 | 有 |
| `a1/troubleshooting/hmscode/0300_0100_0001_0008` | HMS_0300-0100-0001-0008 加热过程异常 | 2026-03-18 | 有 |
| `a1/troubleshooting/hmscode/0300_0100_0001_000C` | HMS_0300-0100-0001-000C 热床满载运行过久 | 2025-05-19 | 有 |
| `a1/troubleshooting/hmscode/0300_0100_0001_000D` | HMS_0300-0100-0001-000D 加热模块异常 | 2026-10-09 | 有 |
| `a1/troubleshooting/hmscode/0300_0600_0001_0003` | HMS_0300-0600-0001-0003 A 电机电阻异常 | 2026-07-31 | 有 |
| `a1/troubleshooting/hmscode/0300_1000_0002_0001` | HMS_0300-1000-0002-0001 X 轴共振频率偏低 | 2026-11-10 | 有 |
| `a1/troubleshooting/hmscode/0300_1800_0001_0005` | HMS_0300-1800-0001-0005 Z 轴电机运行时卡住 | 2026-11-10 | 有 |
| `a1/manual` | A1 Manual | 2026-10-19 | 有 |
| `a1/manual/faq` | A1 FAQ | 2026-11-10 | 有 |

说明：HMS 标题只保留错误码与中文摘要，完整英文标题在抓取时由接口提供，不在此复制。

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 许可未确认 | 不能保存或再发布正文 | 只存元数据与链接；正文缓存在被忽略的运行时目录；引用限短句并注明来源；待人工确认 |
| 步骤依赖图片且无 alt | 纯文本答案可能漏掉关键动作 | 解析时保留图片 URL、顺序和图注；回答中明确“需按原文图示操作”；评估时人工核验 |
| 中文版正文远短于英文版 | 中文答案依据不足 | 以英文正文为依据、中文页作校对；语言字段不可信，需检测实际语言 |
| 机型与标题不一致（“A1 Series”） | 可能把 A1 步骤用于 A1 mini | 机型只取路径；入库时校验路径机型与正文提及；检索强制机型过滤 |
| 同名主题两机型内容不同 | 混淆维护步骤 | 同一 `(section, slug)` 建立两机型映射并分别检索，不合并、不互相补全 |
| 路径大小写与重复记录 | 重复收录、引用不一致 | 规范化小写后去重；以 `(locale, normalized_path)` 为唯一键；保留原始 URL |
| 站点地图 XML 非法、更新频繁 | 增量更新漏页或失败 | 以 GraphQL 清单为主、sitemap 为辅；解析容错；按 `updatedAt` 增量更新 |
| 页面结构可能改版 | 解析器失效 | 解析失败可诊断并保留上次成功版本；定期抽样回归 |

## 需要人工确认

1. 官方资料的使用与再分发许可（是否可存副本、是否可展示摘录）。
2. 首批 42 篇是否符合预期；是否需要补充 AMS、首层、耗材相关页面。
3. 中文页与英文页的取舍：是否接受“以英文为依据、中文校对”的策略。
4. 图片是否需要在界面中直接展示（涉及图片版权与加载策略）。

## 复现方式

```bash
# 页面清单与官方更新时间（公开只读）
curl -s https://wiki.bambulab.com/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { pages { list { id path title updatedAt locale } } }"}'

# 抓取规则
curl -s https://wiki.bambulab.com/robots.txt
curl -s https://bambulab.com/robots.txt

# 正文（服务端渲染 HTML）
curl -s https://wiki.bambulab.com/en/a1-mini/troubleshooting/extruder-clog
```

## 对后续任务的影响

- T03：机型枚举固定为 `a1`、`a1_mini`；文档唯一键用 `(locale, path)`；元数据必须含 `source_url`、`updated_at`（官方）、`retrieved_at`（采集时间，二者分开）与语言。
- T04：解析走 HTML，不走 GraphQL 正文；去重按规范化路径；保留章节层级、表格、图片链接与图注；中英文分别入库，不互译填充。
- T06：机型过滤必须是硬过滤；HMS 查询先按机型再按错误码；标题含 “A1 Series” 的文档需以路径机型为准。
- T05：评估集需包含“同名主题跨机型冲突”和“中文页信息不足”两类题。
