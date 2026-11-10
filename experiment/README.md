# 实验 harness · 契语 vs Python

> 把 [02-实验方案.md](../02-实验方案.md) 变成可执行代码：生成 → 执行 → 错误回喂修复 → 判定 → results.csv。
> 判定器全部"从源数据重算期望值"，与生成上下文完全隔离（[canned/](canned/) 是 mock 生成器用的演示参考解，不参与真实实验）。

## 当前状态

- ✅ **全链路自检通过**（mock 生成器，**40/40**）：**20 个任务全部双语言**
- ✅ **修复回路双向演示**：
  - T01 契语：故意漏声明「写」能力 → `E_CAPABILITY_NOT_DECLARED` 结构化错误回喂 → 1 轮修复通过
  - T08 Python：漏建缓存目录 → traceback 回喂 → 1 轮修复通过
- ✅ 判定器 **20/20** ——实验平台就绪
- ⏳ 真实模型未接：`--生成器 api` 代码就绪，配 `QIYU_EXP_BASE_URL` / `QIYU_EXP_API_KEY` 两个环境变量即可跑正式实验

## 目录

| 文件 | 说明 |
|---|---|
| [harness.py](harness.py) | 批量实验主程序（支持 `.env` 配置模型） |
| [analyze.py](analyze.py) | 汇总 results.csv → 指标表与通过线判定 |
| [tasks.py](tasks.py) | 任务注册表 + 判定器（隔离区，不进生成上下文） |
| [pyshim.py](pyshim.py) | Python 侧外设 mock（smtplib/requests/urllib → 审计记录，与契语记录格式对齐） |
| [canned/](canned/) | mock 生成器参考解（含故意带 bug 的修复演示版） |
| runs/ | 每次运行的沙箱（fixture 副本 + 生成代码 + 产物），可复查取证 |
| [results/results.csv](results/results.csv) | 结果台账 |

## 用法

```powershell
# mock 自检（无需任何 API）
python -X utf8 experiment/harness.py --任务 all --语言 both --生成器 mock

# 真实实验（推荐：.env 文件配置）
#   1) 复制 qiyu/.env.example 为 qiyu/.env，填入 QIYU_EXP_BASE_URL 与 QIYU_EXP_API_KEY
#   2) 先小样验证连通性（一个任务一个模型一种子）：
python -X utf8 experiment/harness.py --任务 T01 --语言 both --生成器 api --模型 deepseek-chat --种子 1
#   3) 全量（3 模型 × 20 任务 × 3 种子）：
python -X utf8 experiment/harness.py --任务 all --语言 both --生成器 api --模型 modelA,modelB,modelC --种子 3
```

模型配置说明：
- `QIYU_EXP_BASE_URL`：任何 OpenAI 兼容端点（OpenAI / DeepSeek / Moonshot / 智谱均可），harness 自动拼 `/chat/completions`
- 两个配置的优先级：**系统环境变量 > .env 文件**（`.env` 支持 `qiyu/.env` 或 `experiment/.env`）
- 配置错误不会炸批：单次生成失败记为"生成器错误"继续跑（已验证：假 key → 401 → 干净记录）

指标口径（results.csv 每行 = 一次运行）：

| 列 | 含义 |
|---|---|
| compile_pass | 是否有版本通过编译（契语=解析+静态能力检查；Python=语法） |
| test_pass | 最终通过全部验收断言 |
| repair_rounds | 成功时的轮次（0=一次通过；未成功记 3） |
| tokens | 生成+修复总 token（api 模式） |
| undeclared_effects | 能力清单外操作次数（文件快照 diff + 外设记录，**两语言同口径**） |

## 公平性裁定（须记录）

任务提示两组逐字相同（任务卡提示词 + 运行参数/输出契约附录）。"外设如何被 mock"属于环境约定而非解法提示：契语的环境说明写在其 system prompt（03 规范）里；Python 只有三行环境说明（expanduser 指向数据根、smtplib/requests 已 mock），不含解法信息。若需消融：删去契语规范中的标准库一节再跑对比。

## 自检发现的标准库缺口（设计反哺 → 已记入 [03 规范](../03-语言规范v0.md) v1 待办）

| 任务 | 缺口 | 状态 |
|---|---|---|
| **全部 20 任务** | — | ✅ **双语言参考解与判定器齐备（v1–v1.3）** |

历史缺口与解法（记录留存）：遍历+分支+累加器（对每个/若/列表字面量/空表/加入行）→ T05/T07/T12/T17；查找+循环表达了合并（T02）、一对一配对（T06）、自联结（T18）——**无需专门联接算子**；`分页请求` 效果 → T11；`读记录`/`列表成表格`/`存JSON` → T09/T15/T19；`去重`/`含` → T13；`连接` → T16；复制文件批量模式 → T20。

这本身就是实验预测的预演：**约束式语言的正确率优势，一半来自"该内建的原语内建了"**——缺口清单即标准库路线图。另一个实战发现：`保证`/`文件存在` 读回自己的产物也需要 `读` 能力声明（T20/T19 亲自踩过）——能力系统连验收自检都不放行，这是正确的严格。

还有一条元教训：**判定器也要自检**——T05 判定器曾把"文件 diff 不记录删除"和"`~/` 前缀未归一化"当成被测程序的错误（其实文件状态是完美的），判定器错了会冤枉语言。harness 的每次运行沙箱都留在 `runs/`，判定纠纷可复查取证。
