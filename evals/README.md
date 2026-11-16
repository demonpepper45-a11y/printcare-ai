# 评估集（T05）

面向 A1 / A1 mini 首批资料的人工核验问题集，用于 T06 检索回归与 T07 回答评估。

## 现状

- 32 道题，覆盖 8 类情形；目标逐步扩充到 50 道。
- 每题含机型、类别、问题原文、预期行为（`answered` / `needs_clarification` / `insufficient_evidence` / `refused`）、预期依据与禁止依据。
- 依据路径来自 [T01 首批 42 篇清单](../docs/sources.md)，不包含未核实资料。

## 题目格式

`questions.jsonl` 每行一个 JSON 对象：

| 字段 | 说明 |
|---|---|
| `id` | 唯一编号，如 `A1-EC-01` |
| `machine` | `a1` 或 `a1_mini` |
| `category` | `direct_qa`、`error_code`、`multi_doc`、`machine_conflict`、`insufficient_evidence`、`unsupported_machine`、`chinese_synonym`、`multi_turn` |
| `question` | 用户问题原文 |
| `expected_status` | 对应 `docs/interfaces.md` 的回答状态 |
| `expected_evidence` | 期望被引用的文档路径（不含语言段） |
| `forbidden_evidence` | 不得出现的文档路径，用于检查机型串用 |
| `expected_refusal_reason` | 仅 `refused` 使用 |
| `notes` | 人工说明，不参与自动判定 |
| `context_turns` | 多轮题必填的前置轮次数组；每轮含 question、expected_status，可选 machine、expected_evidence、forbidden_evidence、expected_refusal_reason |

## 类别与数量

| 类别 | 数量 | 判定方式 |
|---|---|---|
| `direct_qa` | 8 | 检索到预期文档 |
| `error_code` | 6 | 错误码精确命中对应页面 |
| `multi_doc` | 4 | 两篇预期文档都被检索到 |
| `machine_conflict` | 4 | 返回 `machine_mismatch` 且无结果 |
| `insufficient_evidence` | 4 | T07 答案层判定（检索基线跳过） |
| `unsupported_machine` | 2 | 返回 `unsupported_machine_mentioned` 且无结果 |
| `chinese_synonym` | 2 | 口语表达仍召回预期文档 |
| `multi_turn` | 2 | T07 会话层判定（检索基线跳过） |

## 运行检索基线

```powershell
$env:PYTHONPATH='src'
python -m printcare.ingestion --paths-file runtime\first-batch.txt   # 先入库首批资料
python evals/run_retrieval_baseline.py --db runtime/printcare.sqlite3 --k 5
```

- `PASS`：预期依据全部召回且未出现禁止依据；机型冲突/不支持机型场景返回了正确告警。
- `FAIL`：未召回预期依据、出现跨机型依据，或告警缺失。
- `SKIP`：多轮、资料不足和非“不支持机型”的拒答由答案层判定；预期依据尚未入库时也会跳过并说明。改装拒答不能按不支持机型的检索告警判断。

## 运行回答评估（T07）

```powershell
$env:PYTHONPATH='src'   # 并把 DeepSeek Key 放入 runtime/model_key.txt
python evals/run_assistant_eval.py --db runtime/printcare.sqlite3 --k 8
```

自动判定：回答状态是否与预期一致、`answered` 是否引用预期文档、是否出现禁止机型文档、
`refused` 的原因是否符合预期。结果写入 `runtime/assistant-eval.json`，并输出 token 与成本估算。
最近一次真实模型结果见 [回答评估记录](assistant-baseline.md)。

多轮题现按 `context_turns` 在同一个真实 Session 中逐轮执行，再评估主问题。
任一前置轮次失败则整题失败，缺少上下文配置也判失败，不能静默跳过。
输出包含各前置轮次结果，token/cost 汇总包括前置轮次；默认 k=8，与应用保持一致。
每题独立建立会话，避免不同题之间泄漏上下文。运行真实评估会调用模型并产生费用。
新增自动回归使用模拟模型，只验证流程、引用规则和会话行为，不能替代真实多轮质量评估。

## 重要限制

- 这是**检索级与状态级**基线，不评价答案是否忠实、引用是否支持结论；不能据此宣称回答质量达标。
- 预期依据来自官方页面路径，人工核验需按本文逐题对照原文完成。
- 题目扩充到 50 道时，优先补充：更多 HMS 错误码、两台机型的同名维护主题、资料不足的近义问题、需要追问的模糊描述。
