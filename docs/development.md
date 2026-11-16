# 本地开发与接手流程

## 当前阶段

已具备本地资料采集、BM25 检索、模型问答、FastAPI 与 Streamlit 页面。云部署和向量检索尚未实现；质量评估与人工核验仍需继续。

## 环境要求

- Python 3.11 及以上；开发机锁定 3.12（`.python-version`，CI 在 3.11 和 3.12 上验证）。
- 依赖使用精确版本：开发工具定义在 `pyproject.toml` 的 `dev` 附加项。运行时依赖和开发依赖均见 pyproject.toml；页面额外使用 web 附加依赖。
- 测试同时支持 `pytest` 和标准库 `unittest`。测试还需要项目依赖（API 测试使用 FastAPI/httpx）；安装完成后可用模拟模型离线验证。

## 初始化与检查

在仓库根目录执行；保存文件、提交和推送仍是独立步骤。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,web]"

python -m unittest discover -s tests -t .   # 已安装项目依赖后可运行
pytest                                      # CI 使用的入口
ruff check .
ruff format --check .
```

`pip install` 需要网络。测试通过 `tests/__init__.py` 使用 `src/` 下代码，但不替代第三方依赖安装。Windows 沙箱下 API 测试还需要允许本地回环连接。

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

- 只采集官方 A1 / A1 mini 的 `en`、`zh` 页面；正文片段写入被忽略的运行时 SQLite，原文及图片二进制不提交到 Git；图片二进制不由当前管道存储。运行时缓存和对外使用许可仍需确认。
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
- 查询和正文统一归一化“皮带/同步带”“第一层/首层”，标题单独加权；优先每文档最多 2 个片段，不足时回填，保持最终分数排序。
- 当前只有 BM25 关键词检索。向量检索需要选定 Embedding 供应商与凭据，尚未实现（见 [架构](architecture.md)）。

## 评估（T05）

首批 32 道人工核验题与判定方式见 [evals/README.md](../evals/README.md)。检索级基线：

```powershell
$env:PYTHONPATH='src'
python evals/run_retrieval_baseline.py --db runtime/printcare.sqlite3 --k 5
```

该基线只检查“预期依据是否被召回、是否串用机型”，不评价答案忠实度与引用正确性；后者属于 T07，需要真实模型后逐题人工核验。

## 问答（T07）

```powershell
$env:PYTHONPATH='src'
# Key 写入 runtime/model_key.txt（已忽略），或设置 PRINTCARE_MODEL_API_KEY
python -m printcare.assistant --db runtime/printcare.sqlite3 --machine a1_mini --question "挤出机堵料怎么清理？"
python -m printcare.assistant --db runtime/printcare.sqlite3 --machine a1 --question "..." --json
```

- 模型默认 `deepseek-flash`，可用 `PRINTCARE_MODEL_NAME` / `--model` 切换；`--thinking` 开启思考模式。
- 回答状态、引用与拒答规则见 [接口契约](interfaces.md)；引用会被校验为对应片段的逐字子串且不超过 200 字。
- 同一页面的片段最多取 3 个（避免长页面挤占上下文）；可用 `--k` 调整召回数。
- “那、刚才、已经”等追问可结合当前会话现象重新检索；显式机型冲突仍先拦截。更正机型时清空旧现象、步骤和历史，避免混用设备上下文；需要的现象和步骤可重新填写。
- 多轮会话：`--session runtime/session.json` 会在文件里保存机型、现象与历史轮次。
- 真实模型评估见 [回答评估记录](../evals/assistant-baseline.md)；自动检查不等于人工核验，不得据此宣称回答准确。

## API 与页面（T08）

```powershell
$env:PYTHONPATH='src'
python -m printcare.api --host 127.0.0.1 --port 8000      # 先启动 API
streamlit run src/printcare/web/app.py                    # 另一个终端启动页面
```

- 页面通过 `PRINTCARE_API_URL`（默认 `http://127.0.0.1:8000`）访问 API。
- 管理操作需要 `PRINTCARE_ADMIN_TOKEN`；页面侧边栏填写同一个令牌。未设置令牌且 `PRINTCARE_ENVIRONMENT=local` 时，本机开发放行，其他环境返回 503。
- `POST /api/v1/admin/refresh` 是同步接口，只适合小批量（≤20 篇）；完整采集仍用命令行。
- 会话保存在 API 进程内存中，空闲 30 分钟过期，重启即丢失；持久化留待 T09。
- 接口字段、错误码与管理接口见 [接口契约](interfaces.md)；反馈写入运行时数据库的 `feedback` 表。

## 配置

配置全部来自 `PRINTCARE_` 前缀的进程环境变量，变量清单见 [.env.example](../.env.example)。真实值放在本机 `.env` 或部署环境的秘密配置中，由启动方式注入；当前 API/CLI 不会自动加载 `.env`，请由启动方式注入。`.env`、运行数据库和索引目录已被忽略，不得提交。

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
