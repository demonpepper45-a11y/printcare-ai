# 本地开发与接手流程

## 当前阶段

已有 Python 工程骨架、环境配置读取和自动检查（T02），尚无资料采集、检索、问答和页面，没有可启动的服务。现在不需要购买云服务器。

## 环境要求

- Python 3.11 及以上；开发机锁定 3.12（`.python-version`，CI 在 3.11 和 3.12 上验证）。
- 依赖使用精确版本：开发工具定义在 `pyproject.toml` 的 `dev` 附加项。当前没有运行时依赖；后续任务新增依赖时在同一处锁定版本，并说明新增原因。
- 测试同时支持 `pytest` 和标准库 `unittest`。`unittest` 入口只依赖标准库，可在无网络环境运行。

## 初始化与检查

在仓库根目录执行；保存文件、提交和推送仍是独立步骤。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

python -m unittest discover -s tests -t .   # 无需 pytest，可离线运行
pytest                                      # CI 使用的入口
ruff check .
ruff format --check .
```

`pip install` 需要网络；不可用时仍可用 `python -m unittest` 运行测试，它通过 `tests/__init__.py` 直接使用 `src/` 下的代码。

## 采集与解析（T04）

```powershell
$env:PYTHONPATH='src'                              # 未执行 pip install -e . 时使用
python -m printcare.ingestion --list --limit 10     # 只列官方清单，不抓正文
python -m printcare.ingestion --limit 3 --dry-run   # 抓取并解析，不写数据库
python -m printcare.ingestion --limit 3             # 写入 runtime/printcare.sqlite3
python -m printcare.ingestion --section maintenance --limit 10
python -m printcare.ingestion --paths-file runtime\first-batch.txt
```

约定：

- 只采集官方 A1 / A1 mini 的 `en`、`zh` 页面；正文与图片二进制不入库、不入 Git，只写入被忽略的 `runtime/` 目录与运行时数据库。
- `--deactivate-missing` 只应在完整清单运行时使用；带 `--limit`、`--section`、`--paths-file` 等过滤时使用会误停用未抓取的文档。
- 每次运行写入 `ingest_runs` 汇总，失败写入 `ingest_failures`（来源、阶段、异常类型、截断后的消息）；CLI 打印前 20 条，`--strict` 在有失败时返回非零。
- 同一内容重复导入只更新采集时间；内容变化会替换该文档全部片段，`chunk_id` 随正文变化，旧引用因此失效。
- 机型取自官方路径（`a1/` 或 `a1-mini/`），章节取自路径第二段；标题中的 “A1 Series” 不能作为机型依据。

## 检索（T06）

```powershell
$env:PYTHONPATH='src'
python -m printcare.retrieval --db runtime/printcare.sqlite3 --machine a1_mini --query "挤出机堵料"
python -m printcare.retrieval --db runtime/printcare.sqlite3 --machine a1 --query "HMS_0300-0100-0001-0008" --json
```

- 机型是硬过滤：只检索元数据 `machines` 包含该机型的片段；只有明确标注两款通用的文档才会同时命中。
- 问题中提到另一机型时返回 `warning=machine_mismatch` 且无结果；提到 X1 / P1S 等不支持机型时返回 `warning=unsupported_machine_mentioned`，不会把 A1 资料当成通用答案。
- 中文按字二元组切分，英文按词切分，HMS 错误码统一为 `0300_1800_0001_0001` 形式并额外加权。
- 当前只有 BM25 关键词检索。向量检索需要选定 Embedding 供应商与凭据，尚未实现（见 [架构](architecture.md)）。

## 评估（T05）

首批 32 道人工核验题与判定方式见 [evals/README.md](../evals/README.md)。检索级基线：

```powershell
$env:PYTHONPATH='src'
python evals/run_retrieval_baseline.py --db runtime/printcare.sqlite3 --k 5
```

该基线只检查“预期依据是否被召回、是否串用机型”，不评价答案忠实度与引用正确性；后者属于 T07，需要真实模型后逐题人工核验。

## 配置

配置全部来自 `PRINTCARE_` 前缀的进程环境变量，变量清单见 [.env.example](../.env.example)。真实值放在本机 `.env` 或部署环境的秘密配置中，由启动方式注入；当前版本没有入口服务，也不会自动加载 `.env`。`.env`、运行数据库和索引目录已被忽略，不得提交。

`Settings.describe()` 只输出是否配置了密钥，不回显密钥值。

## Git 基本操作

以下命令在仓库目录执行。操作前先检查工作区；存在未提交修改时先确认归属，不直接切换或清理。

```powershell
git status
git branch --show-current
git log -5 --oneline
```

任务完成后，检查差异，按文件选择暂存，再提交和推送自己的功能分支。保存文件、提交和推送是三个独立步骤。

```powershell
git diff
git add <本次任务的文件>
git diff --cached
git commit -m "清晰描述本次修改"
git push -u origin <功能分支>
```

不要将以上占位符原样执行。推送前确认已获相应授权；不要直接将未审核功能推送至 main。

## 新 Agent 接手提示词

```text
请接手 printcare-ai 仓库的一个开发任务。
仓库：https://github.com/demonpepper45-a11y/printcare-ai
本地路径：<填写工作目录>
基准分支或提交：<填写已经包含项目规则的分支或提交>
本次任务：<Issue 或 docs/tasks.md 中的任务编号>
验收标准：<具体条件>
允许修改的模块：<模块>
推送及创建 PR 权限：<明确允许范围>

先检查 Git 状态，阅读适用的 AGENTS.md、README 和 docs 中的需求、架构、任务及进度。
确认任务没有被其他 Agent 领取，再在独立功能分支中实施。
并行写代码时使用独立 worktree 或 checkout，保留他人的工作。
公共接口变更先与负责人协调。
推进到验收完成，交付真实验证结果、限制、提交编号和交接说明。
不自行合并 PR、部署生产服务或创建收费资源。
```

## 多 Agent 协作

初期推荐一名开发、一名审查。T01 与 T02 可以由不同 Agent 负责，但启动并行工作前应先明确负责人及目录。

Git worktree 隔离代码目录，不能自动隔离数据库或运行端口；各 Agent 的数据库路径和服务端口也应独立。公共接口和依赖文件由负责人协调。

任务详情和验收记录放在 Issue 与 PR，负责人维护 docs/progress.md 的阶段摘要。不要依赖某一段聊天作为唯一进度记录。
