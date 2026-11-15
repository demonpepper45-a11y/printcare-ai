# 检索基线记录（2026-11-15）

这是 T06 关键词检索在 T05 评估集上的**检索级**基线，仅检查“预期依据是否召回、是否串用机型”，**不评价答案忠实度与引用正确性**。

## 环境与数据

| 项 | 值 |
|---|---|
| 代码版本 | `feat/t05-eval-set`（基于 `main` `187c4ce`） |
| 数据集 | T01 首批 42 个路径 × `en`/`zh`，共 84 篇文档、1,185+ 片段 |
| 入库命令 | `python -m printcare.ingestion --paths-file runtime/first-batch.txt --delay 0.6` |
| 入库结果 | `selected=84 parsed=84 inserted=84 failed=0` |
| 查询命令 | `python evals/run_retrieval_baseline.py --db runtime/printcare.sqlite3 --k 5` |

## 结果（k=5）

| 类别 | 题数 | 通过 | 失败 | 跳过 |
|---|---|---|---|---|
| direct_qa | 8 | 7 | 1 | 0 |
| error_code | 6 | 6 | 0 | 0 |
| multi_doc | 4 | 3 | 1 | 0 |
| machine_conflict | 4 | 4 | 0 | 0 |
| unsupported_machine | 2 | 2 | 0 | 0 |
| chinese_synonym | 2 | 1 | 1 | 0 |
| insufficient_evidence | 4 | — | — | 4（T07 答案层判定） |
| multi_turn | 2 | — | — | 2（T07 会话层判定） |
| **合计** | **32** | **23** | **3** | **6** |

k=10 时为 24 通过 / 2 失败（`A1-MD-02` 通过，`heatbed` 文档排名第 7）。

## 失败项与原因

| 题目 | 现象 | 原因 |
|---|---|---|
| `A1-DQ-02` “A1 的皮带松了怎么调张力？” | 预期 `a1/maintenance/belt_tension` 未进前 5，排名第 13 | 同一 HMS 页面的多个片段占据前 10；`皮带` 与官方标题的 `Belt Tensioning`/`同步带` 存在词汇差异 |
| `A1-MD-02` “A1 热床需要更换，同时确认线缆…” | 预期两篇只召回一篇 | `a1/maintenance/heatbed` 排名第 7；k=5 深度不足，k=10 可通过 |
| `A1M-SYN-01` “A1 mini 第一层太薄粘不住怎么办？” | 40 条召回内没有 `print-issues-troubleshooting` | 口语 `第一层` 与官方文档 `首层` 的词汇差异；BM25 无法跨词召回 |

已修正一处题目标注：`A1-SYN-01` 原预期挤出机清理页，实际正确依据是热端堵塞页（口语“堵头”对应 `nozzle-clog`），挤出机堵料由 `A1M-DQ-01` 覆盖。

## 结论与后续

- 检索层对**错误码、机型冲突、不支持机型、维护类直接问答**表现稳定（error_code 6/6、machine_conflict 4/4、unsupported 2/2）。
- 已知薄弱点：同页多片段挤占排名、口语同义词、多文档问题的召回深度。
- 这些不是答案质量问题，也不能据此宣称问答可用；T07 需要在真实模型下逐题核验依据、引用与拒答。
- 后续可做（T06 迭代）：按文档去重/限量、标题加权、同义词扩展；T05 扩充到 50 题时优先补这三类。
