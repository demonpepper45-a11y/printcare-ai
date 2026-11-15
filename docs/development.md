# 本地开发与接手流程

## 当前阶段

当前只有项目规划和协作模板，尚无可运行应用。Python 安装、依赖和运行命令由 T02 确定，不需要现在购买云服务器。

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
