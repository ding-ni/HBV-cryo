# HBV-Studio

`HBV-Studio` 现在按两类对象工作：

- `templates/`：内置模板，只读
- `workspaces/`：用户工作区，可编辑

并且在工作区内部再区分三种项目对象：

- `回归验证样例`
- `区间流域 + 上游边界入流`
- `完整上游流域`

当前入口：

```bash
python HBV-Studio/launch.py
```

默认地址：

- `http://127.0.0.1:8765/`

当前工作流：

1. 在总览页复制内置模板，或导入新的 `shp + 径流 csv`
2. 生成工作区配置并自动启动 GIS bootstrap
3. 在“输入准备”页继续 daily / hourly 的 forcing 准备
4. 在“率定任务”页按 `daily` 或 `hourly` profile 启动率定
5. 在“结果分析”页查看过程线、组分和参数

率定说明：

- `daily` 与 `hourly` 是两套独立 profile，手动切换
- `时间步长_小时` 必须与 `率定模式` 一致
- 观测径流时间步会在导入和校验时自动识别

沱沱河模板：

- `templates/tuotuohe_daily_builtin.template.json`
- 轻量输入资产保存在 `templates/assets/tuotuohe/`
- 若本地存在任一盘符下的旧工作区 `Hapi/data`，可在界面中触发“同步沱沱河历史数据”

对象专用模板：

- `templates/full_upstream_daily.template.json`
- `templates/interbasin_daily.template.json`
- `templates/interbasin_hourly.template.json`

降水方案脚本：

- `precipitation_strategy_runner.py`

补充文档：

- `docs/project_framework.md`
- `docs/data_request_checklist.md`
- `docs/precipitation_strategy.md`
