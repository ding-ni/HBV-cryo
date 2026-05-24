# staged_calibration_v1 三阶段率定流程验收记录

日期：2026-04-27

## 本轮目标

本轮实现的是 `staged_calibration_v1` 三阶段率定工程流程，把原先的“三阶段率定顺序”从文字策略落到可运行、可验证、可追踪 metadata 的运行链。

本轮不是继续调 BM-02，也没有改动 BM-02 已冻结参数、translator、HBV-Cryo 前向核心、legacy/V6 objective，且没有新增多个 daily objective selector。正式日尺度目标函数继续固定为 `daily_unified_professional_v1`。

## 设计决定

`staged_calibration_v1` 接入现有正式运行链：

```text
Studio API -> studio_service.start_calibration()
  -> HBV-Studio/profile_runner.py
  -> HBV-Cryo/率定核心.py
```

没有新增普通用户 UI 里的 objective selector。该流程最初接入时曾让日尺度 profile 默认解析为 `staged_calibration_v1`；2026-04-28 过程复核后，日尺度默认已恢复为 `single_pass`，`staged_calibration_v1` 仅通过 `calibration_workflow` 或 `率定流程` 显式调用。

三阶段流程复用现有 MC / DE / refine 搜索函数，不重写 forward core。每个 phase 使用上一阶段最优参数作为 seed；未释放参数会被收窄到 seed 附近的近固定小窗口，从而在实际搜索中保持锁定/强约束。

## 三阶段定义

### Phase 1: hydrologic_skeleton

目标：先识别雨洪、土壤、地下水和退水骨架，防止雪/冰过程过早代偿。

释放参数：

- `RFCF`
- `FC`
- `BETA`
- `LP`
- `K`
- `K1`
- `K2`
- `UZL`
- `PERC`

锁定/强约束：

- `TT`
- `SFCF`
- `CFR`
- `CWH`
- `CFMAX_low`
- `CFMAX_high`
- `ICE_FACTOR`
- `K_MUSK`
- `X_MUSK`
- glacier temperature correction 等非标量可调项保持数据派生状态，不在本阶段释放

### Phase 2: snow_process

目标：在水文骨架稳定后，识别春季起涨、融雪季体积和雪储量释放。

释放参数：

- `TT`
- `SFCF`
- `CFR`
- `CWH`
- `CFMAX_low`
- `CFMAX_high`

锁定/强约束：

- Phase 1 已识别的水文骨架参数
- `ICE_FACTOR`
- Muskingum routing 参数
- glacier temperature correction / glacier fraction / glacier elev 等输入或派生项

### Phase 3: glacier_refinement

目标：最后释放冰川参数，只允许冰川解释晚融季、暖季、雪耗尽后的额外径流。

释放参数：

- `ICE_FACTOR`

锁定/强约束：

- Phase 1 水文骨架参数
- Phase 2 雪过程参数
- Muskingum routing 参数
- fractional glacier / glacier_elev 相关栅格仍作为输入或派生项，不作为当前标量参数释放

继续受以下 objective / diagnostics 护栏约束：

- `flow_guard`
- `nonflow_cap`
- `ice_dominance_guard`
- `peak_source_guard`
- `recession_takeover_diagnostic`

## metadata 写出

新结果 metadata 会写出以下关键字段：

- `calibration_workflow: staged_calibration_v1`
- `calibration_phases`
- 每个 phase 的 `name`
- 每个 phase 的 `released_parameters`
- 每个 phase 的 `locked_parameters`
- 每个 phase 的 `fixed_parameters`
- 每个 phase 的 `fixed_parameter_values`
- 每个 phase 的 `seed_from_previous_phase`
- 每个 phase 的 `seed_source`
- 每个 phase 的 `best_objective`
- 每个 phase 的 `score_summary`
- 每个 phase 的 `selected_search_stage`
- 每个 phase 的 `search_stats`
- `final_selected_phase`
- `final_parameters_from_phase`
- `calibration_workflow_guards`
- `objective_family: daily_unified_professional_v1`

这些字段由核心运行链写入，不是前端文案。

## touched files

- `HBV-Cryo/率定核心.py`
  - 新增 `--calibration-workflow`。
  - 新增 `staged_calibration_v1` 三阶段 phase 定义、phase bounds 构造、phase 搜索执行和 metadata 汇总。
  - metadata 写出 `calibration_workflow`、`calibration_phases`、`final_selected_phase` 等字段。
- `HBV-Studio/profile_runner.py`
  - 新增 workflow 解析。
  - 当前日尺度默认解析为 `single_pass`，`staged_calibration_v1` 保留为显式 experimental workflow。
  - 将 workflow 参数传给 HBV-Cryo 核心。
- `HBV-Studio/studio_service.py`
  - `start_calibration()` 解析并传递 `calibration_workflow`。
  - 任务 metadata 暴露 workflow 字段，便于运行追踪。
- `dev_tools/check_staged_calibration_metadata.py`
  - 新增 staged metadata / legacy metadata / 产品边界回归检查。
- `dev_tools/staged_calibration_acceptance_20260427.md`
  - 本验收记录。

## 验证命令

已通过：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python dev_tools\check_staged_calibration_metadata.py
$env:PYTHONDONTWRITEBYTECODE='1'; python dev_tools\check_peak_recession_diagnostics.py
node --check HBV-Studio\web\app.js
```

已通过 Python `ast.parse` 语法检查：

- `HBV-Cryo/率定核心.py`
- `HBV-Studio/profile_runner.py`
- `HBV-Studio/studio_service.py`
- `dev_tools/check_staged_calibration_metadata.py`
- `dev_tools/check_peak_recession_diagnostics.py`

`check_staged_calibration_metadata.py` 验证内容：

- `calibration_workflow=staged_calibration_v1`
- 三个 phase 名称：`hydrologic_skeleton`、`snow_process`、`glacier_refinement`
- 每个 phase 均包含 released/fixed 参数信息
- Phase 2 / Phase 3 记录从上一阶段继承 seed
- `objective_family=daily_unified_professional_v1`
- legacy `weighted_daily_universal` metadata 仍能兼容加载并作为 historical legacy 处理
- synthetic `weighted_multi_criteria` metadata 仍能兼容加载并保持 historical legacy family
- 产品 objective selector 仍只有一个 `daily_unified_professional_v1`
- 未暴露 BM-02 tuning/search 脚本

## known limitations

- 本轮未运行完整真实流域长时段三阶段率定，因为该任务目标是工程流程、metadata 链路和 regression 可验证性，不是继续 BM-02 调参。
- 当前参数体系中没有独立的 glacier temperature correction 标量参数；`glacier_elev` / `GLACIER_DELTA_T` 作为输入或派生栅格记录在 phase metadata 的非可调固定项里。
- `staged_calibration_v1` 改变的是参数释放顺序和搜索边界构造，不改变 `daily_unified_professional_v1` objective 本身，也不改变 HBV-Cryo 前向计算核心。
- 若验收记录或日志中出现本机路径，只代表验收环境路径；产品代码中不应硬编码这些临时绝对路径。

## 2026-04-27 追加：主文档固化与自动执行验证

### 已更新的既有 MD

本轮不是只新增 dev_tools 验收记录，而是把 `staged_calibration_v1` 写入了既有主文档：

- `HBV-Studio/docs/project_framework.md`
  - 先写入三阶段流程，2026-04-28 后修订为：日尺度默认 workflow 为 `single_pass`，`staged_calibration_v1` 为 experimental。
  - 明确 `objective_family` 仍为 `daily_unified_professional_v1`。
  - 明确本轮不是 BM-02 调参，不改 BM-02 frozen 参数，不重写 HBV-Cryo forward core，不改 translator，不恢复 V6/legacy objective，不新增多个 daily objective selector。
  - 写入三阶段释放/锁定参数、metadata 字段和 2026-04-27 自动验证结果。
- `HBV-Studio/docs/HBV-Studio_用户说明_2026-04-13.md`
  - 在“正式率定”说明中补充日尺度三阶段流程。
  - 面向使用者解释 Phase 1 / Phase 2 / Phase 3 的目标、释放参数、锁定内容和 metadata 追踪字段。

### 本轮 touched files

- `HBV-Studio/docs/project_framework.md`
- `HBV-Studio/docs/HBV-Studio_用户说明_2026-04-13.md`
- `dev_tools/check_staged_calibration_metadata.py`
- `dev_tools/staged_calibration_acceptance_20260427.md`

本轮没有改动 BM-02 frozen 参数、objective tuning、translator、HBV-Cryo forward core、daily objective selector 或普通用户 UI 入口。

### 自动运行的验证命令

已通过：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python dev_tools\check_staged_calibration_metadata.py
```

验证结果摘要：

- `calibration_workflow = staged_calibration_v1`
- phase names = `hydrologic_skeleton`、`snow_process`、`glacier_refinement`
- phase release counts = 9 / 6 / 1
- daily default workflow = `single_pass`（2026-04-28 收口后）
- explicit staged workflow = `staged_calibration_v1`
- hourly default workflow = `single_pass`
- legacy Demo metadata checked = 5
- legacy objective families = `weighted_daily_universal`
- synthetic `weighted_multi_criteria` compatibility = true
- objective selector options = 1
- Web 未暴露 BM-02 / dev_tools 脚本
- 产品代码未硬编码本机验收临时路径

已通过：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python dev_tools\check_peak_recession_diagnostics.py
```

验证结果摘要：

- `objective_family = daily_unified_professional_v1`
- `flow_guard = ok`
- `secondary_terms = ok`
- `ice_dominance_guard = ok`
- `peak_source_guard = above_guard`
- `recession_takeover_diagnostic = takeover`
- legacy Demo metadata checked = 5

已通过：

```powershell
node --check HBV-Studio\web\app.js
```

已通过 Python `ast.parse`：

- `HBV-Cryo/率定核心.py`
- `HBV-Studio/profile_runner.py`
- `HBV-Studio/studio_service.py`
- `dev_tools/check_staged_calibration_metadata.py`
- `dev_tools/check_peak_recession_diagnostics.py`

产品边界检查已通过：

- `HBV-Studio/web/index.html` 仍只有一个 `daily_unified_professional_v1` objective option。
- 未恢复 `weighted_daily_universal` / `weighted_multi_criteria` 为正式 objective。
- 未新增多个 daily objective selector。
- Web 入口未暴露 BM-02 tuning/search 脚本。
- dev_tools 脚本未接入普通用户 UI。
- 产品代码中未硬编码 `F:\HBV成勘院代码\memories\studio_acceptance\...` 这类本机验收路径；该类路径如出现在记录中，只表示验收环境路径。

### 最小真实链路验收尝试

已尝试使用现有 `正式测试` 日尺度工作区执行极小搜索链路：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python HBV-Studio\profile_runner.py --config HBV-Studio\workspaces\正式测试.json --calibration-mode daily --objective-mode daily_unified_professional_v1 --calibration-workflow staged_calibration_v1 --method mc_only --mc-samples 1 --maxiter 1 --popsize 1 --workers 1 --debug-days 1 --seed 20260427
```

结果：300 秒超时，未生成新的完整 `metadata.json`，超时后未发现残留 Python 进程。该项不计为通过。

原因判断：现有真实工作区的数据装载/缓存和首轮模拟仍偏重；本轮目标是文档固化、自动验证和产品边界确认，不继续调 BM-02，也不为追一次真实结果改 objective tuning 或 translator。

当前已由 regression 覆盖：

- workflow 解析：当前日尺度默认 `single_pass`，显式 `staged_calibration_v1` 仍可调用，小时尺度 `single_pass`
- phase 定义与 released/fixed 参数信息
- phase seed 继承语义
- metadata 模板字段
- `daily_unified_professional_v1` objective diagnostics
- legacy metadata historical compatibility
- 产品边界

仍缺：一套足够小、可控、可在数分钟内完整跑完的真实三阶段样例数据，用于验证 Phase 1 / Phase 2 / Phase 3 的完整落盘 run metadata。

## 2026-04-27 追加：staged smoke fixture 闭环

### 目标

本轮新增 `staged_calibration_v1` 的最小 smoke 验收链路，用极小 synthetic hydrograph 证明三阶段 workflow 能完整执行并落盘 metadata。

该 smoke fixture 只验证工程链路，不是科学 benchmark，不替代 BM-02，不用于继续调 BM-02，不改 frozen benchmark，不改 translator，不恢复 legacy objective，不新增 daily objective selector。

### 新增脚本

- `dev_tools/check_staged_calibration_smoke_run.py`

脚本行为：

- 运行时生成极小 synthetic series。
- 直接调用 `HBV-Cryo/率定核心.py` 中真实的 `run_staged_calibration_workflow()`。
- 使用 `mc_only + mc_samples=1`，让 Phase 1 / Phase 2 / Phase 3 都真实进入搜索管线。
- 写出 `simulation.csv` 与 `metadata.json`。
- 生成两个 legacy fixture：`weighted_daily_universal` 与 `weighted_multi_criteria`，用于确认 historical compatibility。
- 通过 `studio_service.normalize_run_metadata()` 与 `_build_run_summary()` 验证 Studio metadata parser 能读取 smoke run 和 legacy fixture。

默认产物路径：

```text
F:\HBV成勘院代码\memories\staged_calibration_smoke\workspace\结果\日尺度\运行记录\staged_calibration_v1_smoke_run\metadata.json
```

该路径是验收环境路径；脚本支持通过 `HBV_STAGED_SMOKE_ROOT` 覆盖输出根目录。产品代码中不硬编码该路径。

### smoke run 断言

已断言：

- 进程正常结束。
- 生成 `metadata.json`。
- `metadata.calibration_workflow == staged_calibration_v1`。
- `metadata.objective_family == daily_unified_professional_v1`。
- `calibration_phases` 至少 3 个。
- Phase 1 `name == hydrologic_skeleton`。
- Phase 2 `name == snow_process`。
- Phase 3 `name == glacier_refinement`。
- 每个 phase 有 `released_parameters`。
- 每个 phase 有 `locked_parameters` 或 `fixed_parameters`。
- Phase 2 有 `seed_from_previous_phase=true`。
- Phase 3 有 `seed_from_previous_phase=true`。
- `final_selected_phase == glacier_refinement`。
- `final_parameters_from_phase == glacier_refinement`。
- `peak_source_guard` / `recession_takeover_diagnostic` 在 workflow guard 或 objective diagnostics 中存在。
- legacy `weighted_daily_universal` / `weighted_multi_criteria` metadata 仍能 historical 兼容读取。

### 自动验证命令

已通过：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python dev_tools\check_staged_calibration_smoke_run.py
```

输出摘要：

- `phase_names = hydrologic_skeleton, snow_process, glacier_refinement`
- `phase_release_counts = 9 / 6 / 1`
- `phase_fixed_counts = 9 / 12 / 17`
- `summary_objective_family = daily_unified_professional_v1`
- `studio_compatible = true`
- `legacy_families = weighted_daily_universal, weighted_multi_criteria`
- `dev_tool_only = true`
- `not_bm02_tuning = true`
- `not_scientific_benchmark = true`

### known limitations

- smoke fixture 使用 synthetic hydrograph，只验证 staged workflow、metadata 落盘和 Studio metadata parser 兼容，不验证真实流域科学可信度。
- smoke 运行使用最小搜索样本，不用于评价 NSE/KGE/PBIAS 科学表现。
- smoke 输出目录是验收环境路径，可由 `HBV_STAGED_SMOKE_ROOT` 改写；不应写入产品代码或普通用户 UI。

## 2026-04-27 追加：沱沱河 Demo 真实实例复核

### 纠偏说明

本轮真实问题对象是：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河
```

不是 `F:\HBV成勘院代码\HBVStudio_Demo\运行目录\正式测试`。之前用户指出的“冰川融水峰值过大”来自沱沱河 Demo 的日尺度结果日志和运行记录。

本轮未改 BM-02 frozen 参数，未改 translator，未改 objective tuning，未重写 HBV-Cryo forward core，未恢复 legacy objective，未新增 daily objective selector，未把 dev_tools 接入普通用户 UI。

### 旧 run

旧 run：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\hbv_cryo_custom_tif_inline_20260427_002549
```

旧 run 已是 `daily_unified_professional_v1`，不是 `weighted_daily_universal`，但它没有 `staged_calibration_v1` workflow metadata，也没有本轮新增的 `peak_source_report` 和 `recession_takeover_diagnostic`。旧 run 的流量指标为：

- 率定期 NSE=0.7127，KGE=0.7410，PBIAS=-3.46%，RMSE=38.6429 m3/s。
- 验证期 NSE=0.6589，KGE=0.6994，PBIAS=5.14%，RMSE=50.7538 m3/s。
- 冰源占比约 32.15%，`glacier_fraction_report=above_window`。

### 新 staged run

新 run：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\staged_calibration_v1_tuotuohe_20260427_221228
```

实际运行命令：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONUTF8='1'
python -u HBV-Studio\profile_runner.py `
  --config 'F:\HBV成勘院代码\HBVStudio_Demo\HBV-Studio\workspaces\tuotuohe_test.json' `
  --calibration-mode daily `
  --objective-mode daily_unified_professional_v1 `
  --calibration-workflow staged_calibration_v1 `
  --prec-source custom_tif `
  --prec-dir 'F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\数据\模型输入\降水_本地导入' `
  --method mc_only `
  --mc-samples 5 `
  --maxiter 1 `
  --popsize 1 `
  --workers 1 `
  --seed 20260427 `
  --init-params-file 'F:\HBV成勘院代码\memories\demo_staged_run\tuotuohe_init_params_from_20260427_002549.json' `
  --init-bound-shrink 0.05
```

运行结果：

- 运行完成，耗时约 293.1 秒。
- 非 `debug-days`，覆盖完整日尺度率定/验证时段。
- 每阶段只做 5 个 MC 样本，并继承旧 run 参数作为初值；因此这是实例复核和 diagnostics 落盘，不是重新大规模科学率定。
- `metadata.json` 与 `simulation.csv` 均已落盘。
- Studio metadata parser 可读取：`objective_family=daily_unified_professional_v1`，`flow_guard_status=ok`，`studio_compatible=true`。

### 三阶段 metadata 验证

metadata 已写出：

- `calibration_workflow=staged_calibration_v1`
- `objective_family=daily_unified_professional_v1`
- `calibration_phases = hydrologic_skeleton, snow_process, glacier_refinement`
- Phase 2 `seed_from_previous_phase=true`
- Phase 3 `seed_from_previous_phase=true`
- `final_selected_phase=glacier_refinement`
- `final_parameters_from_phase=glacier_refinement`

### 指标与诊断

流量指标：

- 率定期 NSE=0.7127，KGE=0.7410，PBIAS=-3.46%，RMSE=38.6429 m3/s。
- 验证期 NSE=0.6589，KGE=0.6994，PBIAS=5.14%，RMSE=50.7538 m3/s。
- `flow_guard=ok`。

过程与冰川诊断：

- `secondary_terms=capped`：过程项惩罚很大，但受 `nonflow_cap=0.35` 限制，未压倒流量拟合。
- `ice_dominance_guard=ok`：在 basin-adaptive guard 下未硬性失败。
- `glacier_fraction_report=above_window`：冰源占比约 32.15%，高于软区间上限约 26.87%。
- `peak_source_guard=above_guard`：2013、2015、2016、2017 被标记为证据不足或偏高的冰源峰值年。
- `recession_takeover_diagnostic=takeover`：2013、2015、2016 存在退水段冰源接管。
- `peak_source_report` 中 2010、2012、2014 被归为可能合理的晚融季冰峰；2013、2015、2016、2017 被归为 `suspicious_or_evidence_limited_ice_peak`。

### 结论

这次 staged run 没有显著改善流量分数，因为运行方式是小样本复核，并且旧 run 参数已作为初值保留；但它把问题解释清楚了：

- 当前不是流量拟合底线失败，`flow_guard=ok`。
- 主要问题是过程解释可信度不足，尤其是冰川标签占比和峰日/退水段冰源过强。
- 当前 Demo 使用 `binary_legacy` / 1 km binary 冰川表示。该模式默认不启用 `glacier_fraction.tif` 和 `glacier_elev.tif`，这不等同于冰川空间数据缺失，也不应作为沱沱河冰源异常的主因。
- 用户已说明率定前冰川空间诊断中真实冰川面积和 1 km 统计冰川面积基本一致，因此本轮判断不再把冰川面积或 1 km mask 作为首要怀疑对象。

最关键下一步不是继续堆测试，也不是盲目补 1 km binary 模式未启用的 tif，而是：

1. 检查参数和过程代偿：降水/固态降水、雪过程释放、温度指数冰融强度、K/K1/K2/PERC/UZL 退水结构。
2. 检查外部入流或观测误差；GM/SCA/geodetic mass balance 可作为独立过程证据补充。

## 2026-04-27 追加：沱沱河 Demo 中等强度 staged run

### 口径修正

本轮修正了 1 km binary 模式的解释口径：

- `binary_legacy` / 1 km binary glacier 表示下，`glacier_fraction.tif` 与 `glacier_elev.tif` 未启用属于模式设定。
- 这不等同于冰川空间数据缺失，也不能作为沱沱河冰源抢峰或退水接管的主要原因。
- fractional_subgrid 模式仍保留原逻辑：如果用户明确使用 fractional glacier chain，则 glacier_fraction / glacier_elev 的完整性是关键证据。
- 结果页 warning 改为优先说明 peak/recession diagnostics 暴露的过程风险，而不是把 1 km binary 模式未启用的 tif 当成失败原因。

### 中等强度运行

工作目录：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河
```

新 run：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\staged_calibration_v1_tuotuohe_medium_20260427_223836
```

实际命令：

```powershell
python -u HBV-Studio\profile_runner.py `
  --config F:\HBV成勘院代码\HBVStudio_Demo\HBV-Studio\workspaces\tuotuohe_test.json `
  --calibration-mode daily `
  --objective-mode daily_unified_professional_v1 `
  --calibration-workflow staged_calibration_v1 `
  --prec-source custom_tif `
  --prec-dir F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\数据\模型输入\降水_本地导入 `
  --method mc_only `
  --mc-samples 100 `
  --maxiter 1 `
  --popsize 1 `
  --workers 4 `
  --seed 20260427 `
  --init-params-file F:\HBV成勘院代码\memories\demo_staged_run\tuotuohe_init_params_from_20260427_002549.json `
  --init-bound-shrink 0.05
```

运行记录：

- 完整 2009-2020 时段，非 `debug-days`。
- 每阶段 100 个 MC 样本；因 5 样本完整运行已约 4.5 分钟，本次作为中等强度实例复核，不作为 BM-02 调参或最终科学重率定。
- 前台运行退出码 0，耗时约 976.5 s。
- `metadata.json` 与 `simulation.csv` 已落盘。
- Phase 1 / Phase 2 / Phase 3 均真实执行，Phase 2/3 从上一阶段 seed 继承，最终参数来自 `glacier_refinement`。

主要指标：

- 率定期 NSE=0.7140，KGE=0.7404，PBIAS=-2.84%，RMSE=38.5577 m3/s。
- 验证期 NSE=0.6579，KGE=0.6928，PBIAS=5.37%，RMSE=50.8217 m3/s。
- `flow_guard=ok`，`secondary_terms=capped`。
- `ice_dominance_guard=above_guard`，`glacier_fraction_report=above_window`，冰源占比约 32.25%，仍高于软区间上限约 26.87%。
- `peak_source_guard=above_guard`，2013、2015、2016、2017 仍需复核；2010、2012、2014 仍为可解释的晚融季冰峰。
- `recession_takeover_diagnostic=takeover`，2013、2015、2016 仍存在退水段冰源接管。

与旧 run / 5 样本 run 对比：

- 旧 run `hbv_cryo_custom_tif_inline_20260427_002549`：无 staged workflow metadata，无 peak/recession diagnostics；流量指标为率定 NSE=0.7127、验证 NSE=0.6589，冰源占比约 32.15%。
- 5 样本 staged run `staged_calibration_v1_tuotuohe_20260427_221228`：三阶段链路已跑通，但分数和冰源占比基本沿用旧初值。
- 本次 100 样本中等强度 run：水文骨架、雪过程和 ICE_FACTOR 均有小幅调整，率定期 NSE 略升到 0.7140，但验证期 NSE 略降到 0.6579；peak/recession 异常年份没有减少。

结论：

- `staged_calibration_v1` 工程链路有效，三阶段确实执行并落盘。
- 对沱沱河实例而言，中等强度搜索没有解决冰源抢峰和退水段接管。
- 在冰川面积诊断已基本通过、1 km binary 模式不依赖 fraction/elevation tif 的前提下，更可能的问题是参数/过程代偿：固态降水或雪储量释放不足、温度指数冰融强度偏强、退水结构无法承接慢响应，或外部入流/观测误差导致模型用冰源标签补偿。
- known limitation：本次为 100 样本中等强度复核，不是 200-500 样本大规模重率定；但已足够说明异常不是 5 样本偶然暴露。

## 2026-04-27 追加：旧参数邻域澄清与 wide/no_init_shrink 对照

### 重新定性 medium run

上一轮：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\staged_calibration_v1_tuotuohe_medium_20260427_223836
```

不是完整宽参数空间重率定。它使用：

```powershell
--init-params-file F:\HBV成勘院代码\memories\demo_staged_run\tuotuohe_init_params_from_20260427_002549.json
--init-bound-shrink 0.05
```

因此它的结论应改写为：旧参数邻域内，流量拟合可接受，但冰源抢峰和退水段冰源接管仍然存在。它不能证明 `staged_calibration_v1` 在完整宽参数空间下无效。

### wide/no_init_shrink run

新 run：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\staged_calibration_v1_tuotuohe_wide_no_init_shrink_20260427_230744
```

实际命令：

```powershell
python -u HBV-Studio\profile_runner.py `
  --config F:\HBV成勘院代码\HBVStudio_Demo\HBV-Studio\workspaces\tuotuohe_test.json `
  --calibration-mode daily `
  --objective-mode daily_unified_professional_v1 `
  --calibration-workflow staged_calibration_v1 `
  --prec-source custom_tif `
  --prec-dir F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\数据\模型输入\降水_本地导入 `
  --method mc_only `
  --mc-samples 100 `
  --maxiter 1 `
  --popsize 1 `
  --workers 4 `
  --seed 20260428
```

运行说明：

- 未传旧参数 `init_params_file`。
- `init_bound_shrink=0.0`。
- 完整 2009-2020 时段，非 `debug-days`。
- Phase 1 / Phase 2 / Phase 3 均真实执行，Phase 2/3 从上一阶段 seed 继承，最终参数来自 `glacier_refinement`。
- 前台运行退出码 0，耗时约 1138.8 s。
- `metadata.json` 与 `simulation.csv` 已落盘，Studio metadata parser 可读取。

### 指标对比

| run | 搜索口径 | 率定 NSE | 率定 KGE | 率定 PBIAS | 验证 NSE | 验证 KGE | 验证 PBIAS | 冰源占比 | flow_guard | ice_guard | peak_guard | recession |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| old `002549` | 非 staged 旧结果 | 0.7127 | 0.7410 | -3.46% | 0.6589 | 0.6994 | 5.14% | 32.15% | ok | ok | 未写出 | 未写出 |
| medium `223836` | 旧参数邻域，shrink=0.05 | 0.7140 | 0.7404 | -2.84% | 0.6579 | 0.6928 | 5.37% | 32.25% | ok | above_guard | above_guard | takeover |
| wide `230744` | 无旧 init，无 shrink | 0.5788 | 0.6388 | 1.23% | 0.6484 | 0.6559 | 8.39% | 31.89% | penalized | ok | above_guard | takeover |

wide run 参数变化明显：`ICE_FACTOR` 从旧参数约 1.74 升至约 2.05，`K` 从约 0.33 降至约 0.21，`K2` 从约 0.0198 降至约 0.0099，`PERC` 从约 2.08 升至约 5.01。说明它不是旧参数邻域小扰动；但它牺牲了率定期流量拟合，且没有降低冰源抢峰。

### 异常年份过程诊断

说明：`simulation.csv` 不输出 SWE 状态量，下表“雪耗尽代理”依据峰日雪源流量占比低且冰源主导判断，只作为过程线索；降水和气温来自缓存栅格堆栈的流域均值。

| run | 年份 | 类别 | 峰日 | 雨% | 雪% | 冰% | 前7天P(mm) | 前15天P(mm) | 前7天T(℃) | 退水冰均% | 接管天 | 诊断 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| old | 2010 | 对照 | 2010-08-13 | 38.7 | 1.7 | 59.6 | 52.3 | 60.2 | 7.0 | 43.7 | 9 | 晚融季冰峰，退水未接管 |
| old | 2012 | 对照 | 2012-08-11 | 38.0 | 6.5 | 55.4 | 32.4 | 53.5 | 7.0 | 38.9 | 9 | 晚融季冰峰，退水未接管 |
| old | 2014 | 对照 | 2014-08-08 | 43.4 | 4.6 | 52.1 | 52.5 | 77.5 | 6.7 | 27.7 | 1 | 晚融季冰峰，退水未接管 |
| old | 2013 | 可疑 | 2013-07-17 | 22.3 | 6.5 | 71.2 | 25.9 | 59.0 | 7.7 | 59.7 | 30 | 冰源峰值偏强且退水接管 |
| old | 2015 | 可疑 | 2015-08-05 | 23.3 | 14.5 | 62.2 | 8.5 | 10.3 | 7.3 | 43.1 | 13 | 前期降水很少，退水接管 |
| old | 2016 | 可疑 | 2016-08-17 | 27.3 | 3.9 | 68.7 | 33.3 | 48.5 | 7.1 | 51.5 | 20 | 冰源峰值偏强且退水接管 |
| old | 2017 | 可疑 | 2017-08-22 | 31.5 | 5.5 | 62.9 | 27.1 | 42.2 | 6.9 | 30.0 | 8 | 冰源峰值偏强但退水未接管 |
| medium | 2013 | 可疑 | 2013-07-17 | 22.8 | 6.5 | 70.7 | 25.9 | 59.0 | 7.7 | 59.6 | 17 | 局部搜索后仍接管 |
| medium | 2015 | 可疑 | 2015-08-05 | 23.8 | 13.5 | 62.7 | 8.5 | 10.3 | 7.3 | 43.7 | 13 | 局部搜索后仍接管 |
| medium | 2016 | 可疑 | 2016-08-17 | 27.7 | 3.9 | 68.4 | 33.3 | 48.5 | 7.1 | 51.3 | 20 | 局部搜索后仍接管 |
| wide | 2010 | 对照 | 2010-08-13 | 30.8 | 2.1 | 67.1 | 52.3 | 60.2 | 7.0 | 40.9 | 9 | wide 下也转为可疑冰峰 |
| wide | 2012 | 对照 | 2012-08-11 | 27.1 | 5.6 | 67.3 | 32.4 | 53.5 | 7.0 | 35.0 | 10 | wide 下也转为可疑冰峰 |
| wide | 2014 | 对照 | 2014-08-07 | 30.9 | 4.0 | 65.1 | 45.0 | 67.0 | 6.7 | 26.0 | 5 | wide 下也转为可疑冰峰 |
| wide | 2013 | 可疑 | 2013-07-16 | 14.0 | 3.5 | 82.6 | 22.6 | 55.0 | 7.5 | 60.5 | 12 | 冰源峰值更强且退水接管 |
| wide | 2015 | 可疑 | 2015-08-05 | 19.1 | 13.5 | 67.4 | 8.5 | 10.3 | 7.3 | 35.6 | 6 | 峰值冰源更强，退水未接管 |
| wide | 2016 | 可疑 | 2016-08-17 | 17.4 | 3.0 | 79.6 | 33.3 | 48.5 | 7.1 | 53.2 | 19 | 冰源峰值更强且退水接管 |
| wide | 2017 | 可疑 | 2017-08-21 | 21.4 | 5.4 | 73.2 | 25.5 | 40.6 | 6.8 | 30.5 | 9 | 峰值冰源更强但退水未接管 |

核心发现：

- 可疑年与对照年都集中在 7-8 月暖季，峰日雪源占比普遍偏低。因此“晚融季 + 高温 + 低雪源”只能解释冰融出现，不能证明峰值归因合理。
- 2013 和 2016 的差异最明确：峰日冰源占比极高，峰后 30 天退水窗口仍由冰源持续主导，更像冰川标签代偿退水结构或供水不足。
- 2015 的峰前 7/15 天降水只有约 8.5/10.3 mm，但峰日冰源仍超过 60%，提示可能存在降水/固态降水不足或观测/外部入流问题被冰融补偿。
- wide run 没有改善过程解释，反而把 2010/2012/2014 这些原本相对可解释的晚融季冰峰也推成可疑冰峰。

### ICE_FACTOR limited 实验

本轮未做 ICE_FACTOR limited 实验。原因是当前正式 CLI 没有现成的“只覆盖 ICE_FACTOR 上界”的参数；若临时改 runner 或 objective 会超出本轮“不新增复杂验收体系、不改 objective/forward core”的边界。建议下一轮只新增一个开发侧最小参数边界覆盖配置，专门用于控制实验，不接入普通 UI。

## 2026-04-28 追加：production staged run

### 运行目的

本轮停止围绕旧 run 做局部优化和 ICE_FACTOR 控制实验。原因是 medium run 只是旧参数邻域，wide100 只是轻/中等探索，都不能作为最新三阶段逻辑的主要判断对象。本轮改为用当前正式源码和最新 `staged_calibration_v1` 进行接近正式的重新率定。

### 命令与输出

新 run：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\staged_calibration_v1_tuotuohe_production_20260427_233809
```

实际命令：

```powershell
python -u HBV-Studio\profile_runner.py `
  --config F:\HBV成勘院代码\HBVStudio_Demo\HBV-Studio\workspaces\tuotuohe_test.json `
  --calibration-mode daily `
  --objective-mode daily_unified_professional_v1 `
  --calibration-workflow staged_calibration_v1 `
  --prec-source custom_tif `
  --prec-dir F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\数据\模型输入\降水_本地导入 `
  --method mc_screen_de `
  --mc-samples 300 `
  --maxiter 3 `
  --popsize 2 `
  --workers 4 `
  --seed 20260428
```

运行记录：

- 完整 2009-2020 时段，非 `debug-days`。
- 未使用旧 run 参数作为 init，`init_bound_shrink=0.0`。
- 每个 phase 执行 MC 300 + DE + refine，最终采用 `refine` 结果。
- 总评价次数 3679。
- 前台运行耗时约 8943.2 s，metadata 记录 `elapsed_seconds=8919.6`。
- `metadata.json` 与 `simulation.csv` 已落盘。
- Studio metadata parser 可读取。

### 阶段结果

| phase | released | seed_from_previous | best objective | NSE_cal | PBIAS_cal | flow_guard | ice_guard | peak_guard | recession |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| hydrologic_skeleton | RFCF/FC/BETA/LP/K/K1/K2/UZL/PERC | false | 2.678881 | 0.6078 | 15.87% | penalized | above_guard | above_guard | takeover |
| snow_process | TT/SFCF/CFR/CWH/CFMAX_low/CFMAX_high | true | 1.412895 | 0.5894 | 3.82% | penalized | above_guard | above_guard | takeover |
| glacier_refinement | ICE_FACTOR | true | 1.412874 | 0.5894 | 3.83% | penalized | above_guard | above_guard | takeover |

最终参数来自 `glacier_refinement`。关键参数：`ICE_FACTOR=2.000377`，`K=0.262186`，`K1=0.144124`，`K2=0.009521`，`PERC=4.321249`，`TT=-0.054431`，`CFMAX_low=3.5528`，`CFMAX_high=7.471967`。

### 指标与诊断

| run | 搜索口径 | 率定 NSE | 率定 KGE | 率定 PBIAS | 验证 NSE | 验证 KGE | 验证 PBIAS | 冰源占比 | flow_guard | ice_guard | peak_guard | recession |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| old `002549` | 非 staged 旧结果 | 0.7127 | 0.7410 | -3.46% | 0.6589 | 0.6994 | 5.14% | 32.15% | ok | ok | 未写出 | 未写出 |
| medium `223836` | 旧参数邻域，shrink=0.05 | 0.7140 | 0.7404 | -2.84% | 0.6579 | 0.6928 | 5.37% | 32.25% | ok | above_guard | above_guard | takeover |
| wide100 `230744` | 无旧 init，MC 100 | 0.5788 | 0.6388 | 1.23% | 0.6484 | 0.6559 | 8.39% | 31.89% | penalized | ok | above_guard | takeover |
| production `233809` | 无旧 init，MC 300 + DE + refine | 0.5894 | 0.6425 | 3.83% | 0.6422 | 0.6467 | 10.04% | 32.31% | penalized | above_guard | above_guard | takeover |

production run 的 `peak_source_guard=above_guard`，2009-2017 全部率定年均为 suspicious ice peak；`recession_takeover_diagnostic=takeover`，2013、2016 仍退水接管。2013 峰日冰源占比约 81.8%，2016 约 78.8%，2015 约 68.9%，2017 约 72.5%。

### 结论

- 本次 production staged run 是当前最新三阶段逻辑的主要判断对象，旧 run / medium / wide100 只作为对比。
- 搜索链路完整执行，metadata 和结果页读取链路正常。
- 结果没有改善：流量拟合低于旧 run 和 medium，过程诊断仍提示冰源抢峰和退水接管。
- `staged_calibration_v1` 的阶段化运行、metadata 和 peak/recession diagnostics 值得保留；但当前参数范围和目标函数组合没有在沱沱河上自动产生更合理的水文过程解。
- 下一步不应继续旧参数局部优化。最关键方向是检查参数范围/过程结构和输入约束，尤其是雪过程、退水结构、固态降水或外部入流。

## 2026-04-28 追加：staged 降级、GM 审计与 default workflow 复核

### 决策

`staged_calibration_v1` 已降级为 experimental / diagnostic workflow，不再作为日尺度默认正式 workflow。默认日尺度 workflow 恢复为 `single_pass`，metadata 写出：

- `calibration_workflow=single_pass`
- `calibration_workflow_status=default_production`
- `objective_family=daily_unified_professional_v1`

显式调用 staged 时仍保留三阶段执行和 metadata，但写出 `calibration_workflow_status=experimental`。本轮未调 BM-02、未改 frozen benchmark、未改 translator、未恢复 legacy objective、未新增 daily objective selector、未重写 forward core、未把 dev_tools 接入普通 UI。

### GM / 度日因子实现审计

源码中已有 GM / 度日因子链路：

- `公共/内部实现/生成冰川融水.py`：使用温度阈值、`CFMAX_GLACIER=5.5`、辐射修正生成 `GM_YYYY.MM.DD.tif`。
- `HBV-Cryo/率定核心.py`：`load_glacier_melt_reference_series()` 从 `数据/模型输入/冰川融水` 或 `glacier_melt` 读取 GM 参考序列，并输出 `q_ice_reference_raw` / `q_ice_reference`。
- `HBV-Cryo/daily_unified_objective.py`：`_build_evidence_registry()` 与 `_compute_external_evidence_terms()` 已将 `q_ice_reference_raw` 接入 `external_evidence.gm`，权重 0.12，并受 `nonflow_cap` 限制。

本轮没有新造复杂约束系统。当前减负后的主线明确为：GM / 度日因子约束暂不启用；`gm_constraint` 只保留可读状态字段，默认 `disabled_by_default` 或 `skipped_inactive`，不参与正式主线评分。

### BM-02 过程复核

只读取旧 BM-02 PASS run，不重新率定、不调参数：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\正式测试\结果\日尺度\运行记录\hbv_cryo_mswep_inline_20260406_220120
```

流量指标确实较好：率定 NSE=0.7674，验证 NSE=0.6781，验证 KGE=0.7907，验证 PBIAS=-2.82%。但用当前 peak/recession 诊断链回放 `simulation.csv` 后，`peak_source_guard=above_guard`，2016 为 suspicious ice peak，`recession_takeover_diagnostic=takeover`，2016 存在退水段冰源接管。

结论：BM-02 PASS 主要是 discharge PASS，不等于 cryo process attribution PASS。本轮不因该诊断结果调 BM-02 参数。

### 沱沱河 default workflow run

新 run：

```text
F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\tuotuohe_default_workflow_gm_constraint_skipped_production_20260428_093629
```

实际命令：

```powershell
python -u HBV-cryo\HBV-Studio\profile_runner.py `
  --配置 F:\HBV成勘院代码\HBVStudio_Demo\HBV-Studio\workspaces\tuotuohe_test.json `
  --率定模式 daily `
  --method mc_screen_de `
  --workers 4 `
  --maxiter 3 `
  --popsize 2 `
  --seed 20260428 `
  --mc-samples 300 `
  --目标函数 daily_unified_professional_v1 `
  --降水源 custom_tif `
  --prec-dir F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\数据\模型输入\降水_本地导入 `
  --冰川模式 inline
```

说明：

- 未传 `--calibration-workflow`，使用默认 `single_pass`。
- 未使用旧 run 参数 init，`init_bound_shrink=0.0`。
- 完整 2009-2020 时段，非 `debug-days`。
- 搜索强度为 `mc_screen_de`、`mc_samples=300`、`maxiter=3`、`popsize=2`、`workers=4`。
- 前台耗时约 3361.3 s，metadata 记录 `elapsed_seconds=3333.3`，总评价次数 1268。
- `metadata.json` 与 `simulation.csv` 已落盘，Studio `load_run_detail()` parser 可读取。

GM 状态：

- 沱沱河当前 `数据/模型输入/冰川融水` 目录没有 `GM_*.tif`。
- 因此本次 `gm_constraint=skipped_inactive`，`reference_available=false`，`reference_used_in_objective=false`。
- 这说明源码已有 GM 参考序列入口，但当前主线暂不启用 GM 约束，且当前 Demo 工作目录没有可用 GM reference；本次不是外部 GM 真正生效的 run。

指标与诊断：

| run | workflow | 率定 NSE | 率定 KGE | 率定 PBIAS | 验证 NSE | 验证 KGE | 验证 PBIAS | 冰源占比 | flow_guard | ice_guard | peak_guard | recession |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| old `002549` | 非 staged 旧结果 | 0.7127 | 0.7410 | -3.46% | 0.6589 | 0.6994 | 5.14% | 32.15% | ok | ok | 未写出 | 未写出 |
| staged production `233809` | staged experimental | 0.5894 | 0.6425 | 3.83% | 0.6422 | 0.6467 | 10.04% | 32.31% | penalized | above_guard | above_guard，2009-2017 全部可疑 | takeover，2013/2016 |
| default `093629` | single_pass default | 0.7335 | 0.8132 | -12.76% | 0.6349 | 0.8160 | 1.34% | 21.15% | ok | ok | above_guard，2013/2016 | takeover，2016 |

关键过程判断：

- default workflow 使流量恢复到旧 run 附近，验证 KGE 更好。
- 总冰源占比从约 32.3% 降至约 21.1%，回到软诊断窗口内。
- suspicious ice peak 从 staged production 的 2009-2017 全部率定年，减少为 2013、2016。
- recession takeover 从 staged production 的 2013、2016，减少为 2016。
- 2015 峰值不再由冰源主导，改为雪源主导；2017 为晚融季可解释冰峰。
- 仍需复核 2013/2016，尤其 2016 同时存在峰日冰源偏强和退水段冰源接管。

当前结论：默认稳定单流程 + peak/recession/ice diagnostics 是当前更可靠主线。`staged_calibration_v1` 保留为实验诊断流程，不作为正式默认。GM / 度日因子约束暂不启用。后续如研究过程归因，只做小范围、问题导向分析，不再盲目加框架。

### 最低验证

已运行：

```powershell
python dev_tools\check_staged_calibration_metadata.py
python dev_tools\check_peak_recession_diagnostics.py
node --check HBV-Studio\web\app.js
```

结果：

- `check_staged_calibration_metadata.py` 通过，当前 `daily_default=single_pass`，显式 staged 仍可调用且 `staged_status=experimental`，legacy metadata 兼容仍通过。
- `check_peak_recession_diagnostics.py` 通过，`daily_unified_professional_v1`、`flow_guard`、`secondary_terms`、`ice_dominance_guard`、`peak_source_guard`、`recession_takeover_diagnostic` 仍可生成。
- `node --check` 通过。
- Python `ast.parse` 通过，覆盖 `HBV-Studio/profile_runner.py`、`HBV-Studio/studio_service.py`、`HBV-Cryo/率定核心.py`、`HBV-Cryo/daily_unified_objective.py`、`dev_tools/check_staged_calibration_metadata.py`。
- `index.html` 仍只有一个 objective option：`daily_unified_professional_v1`。
- 新 run 的 `metadata.json`、`simulation.csv` 存在，metadata 中 `objective_family=daily_unified_professional_v1`、`calibration_workflow=single_pass`、`calibration_workflow_status=default_production`、`peak_source_report`、`recession_takeover_diagnostic`、`gm_constraint` 均存在。
- 未发现 BM-02 调参、translator 改动、legacy objective 回退、新 objective selector、dev_tools UI 暴露或产品代码硬编码本机临时验收路径。

## 2026-04-28 追加：前端结果页减负与本地诊断归档

本轮进入系统收尾阶段，不再新增水文过程模块，不再调整 objective 结构，不再开展新的参数率定试验。当前主线固定为：

- 默认日尺度率定流程：`single_pass`。
- 唯一正式日尺度目标函数：`daily_unified_professional_v1`。
- `staged_calibration_v1` 保留为 experimental / diagnostic workflow，不作为默认生产流程。
- GM / 度日因子冰川融水约束暂不启用，不作为当前系统组成。
- `peak_source_guard`、`recession_takeover_diagnostic`、`ice_dominance_guard`、`glacier_fraction_report` 继续保留在 metadata 和开发侧诊断链中，但不再集中展示在前端结果页。

前端结果页已改为中文水文摘要表达，只显示：

- 率定流程：单流程参数率定 / 历史率定结果 / 实验性过程诊断结果。
- 目标函数：统一日尺度综合水文目标函数。
- 径流拟合：径流拟合良好 / 需进一步复核。
- 冰川融水贡献：贡献合理 / 偏高需关注。
- 洪峰成因：未见明显异常 / 存在异常年份。
- 退水过程：退水过程正常 / 存在异常控制。
- 诊断说明与本地诊断报告路径。

前端不再渲染完整 JSON、逐年洪峰/退水表、`objective_terms`、`secondary_terms`、`external_evidence`、`nonflow_cap`、`calibration_workflow_status`、`gm_constraint` 等工程内部字段。上述字段仍完整保存在 `metadata.json` 中。

每次打开结果详情时，后端会在对应结果目录生成或刷新 `水文诊断摘要.md`。该文件包含原始 workflow / objective、径流拟合约束、冰川融水贡献、洪峰逐年诊断、退水过程诊断、冰川面积与分布诊断、GM 当前未启用状态和专家复核建议。示例验收路径为：

`F:\HBV成勘院代码\HBVStudio_Demo\运行目录\沱沱河\结果\日尺度\运行记录\tuotuohe_default_workflow_gm_constraint_skipped_production_20260428_093629\水文诊断摘要.md`

该路径为本机验收环境路径，仅用于记录，不写入产品代码。

本轮没有重构 Demo，没有重打包 exe，没有调 BM-02，没有改 translator，没有恢复 legacy objective，也没有把 dev_tools 接入普通用户 UI。

最低验证：

- `ast.parse` 覆盖 `HBV-Studio/studio_service.py`：通过。
- `node --check HBV-Studio\web\app.js`：通过。
- `HBV-Studio\web\index.html`：仍只有一个目标函数选项 `daily_unified_professional_v1`。
- workflow 解析：日尺度默认 `single_pass`；显式 `staged_calibration_v1` 仍可调用且状态为 `experimental`。
- GM / 度日因子：当前默认不启用，synthetic objective 检查中 `gm.active=false`。
- Studio result parser：现有沱沱河 default run 可由 `load_run_detail()` 读取，返回中文 `hydrology_summary`，并生成 `水文诊断摘要.md`；metadata 中 `peak_source_report` 与 `recession_takeover_diagnostic` 原始字段仍保留。
