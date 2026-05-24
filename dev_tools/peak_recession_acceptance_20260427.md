# 峰日/退水段诊断验收记录

日期：2026-04-27

## 验收范围

本记录用于固化 Studio 端峰日/退水段诊断链路的收口验收结果，覆盖后端目标函数输出、API 元数据兼容、结果页渲染数据链路和开发侧回归检查。

本轮验收未改动 BM-02 参数、translator 逻辑、目标函数调参/搜索逻辑，也未新增或恢复产品侧多目标函数选择器。

## 可写根目录启动方式

Studio 已通过显式指定可写目录完成启动验收，不依赖默认 AppData 写入路径：

```powershell
python HBV-Studio\launch.py `
  --no-browser `
  --host 127.0.0.1 `
  --port 8799 `
  --user-root <writable_user_root> `
  --runtime-root <writable_runtime_root> `
  --temp-root <writable_temp_root>
```

最终验收运行使用：

- 用户根目录：`F:\HBV成勘院代码\memories\studio_acceptance\20260427_171137\user_root`
- 运行根目录：`F:\HBV成勘院代码\memories\studio_acceptance\20260427_171137\runtime_root`
- 临时根目录：`F:\HBV成勘院代码\memories\studio_acceptance\20260427_171137\temp_root`
- 启动日志：`F:\HBV成勘院代码\memories\studio_acceptance\20260427_171137\user_root\logs\launch_20260427_171138.log`

启动日志已记录实际用户根目录、工作区目录、运行根目录、日志目录、Web 根目录、临时根目录、发现的运行根目录，以及发现的结果元数据目录。

## 验收结果

已通过：

- Studio 服务启动和 `/api/health`。
- `/api/runs` 能返回当前统一目标函数验收结果和旧 weighted 验收结果。
- `/api/run` 能加载当前结果和旧元数据的详情。
- 页面资源 `/` 和 `/app.js` 可正常服务。
- 紧凑结果卡片能显示目标函数族、PBIAS 和 `flow_guard` 状态。
- 当前统一目标函数结果详情包含 `peak_source_report` 和 `recession_takeover_diagnostic`。
- 旧 `weighted_daily_universal` 元数据可兼容加载，并标记为历史/旧目标结果。
- 缺少 glacier elevation 等证据时，冰源分解可信度 warning 路径可触发。

截图级浏览器断言未完成，原因是本机 Windows 权限拦截了 Playwright 进程启动（`[WinError 5]`），同时 Chrome/Edge CDP 也未能开放 `/json/version`。这是本机浏览器自动化权限阻断，不是 Studio 服务、API 或页面资源链路失败。

## 回归检查

已通过：

```powershell
python dev_tools\check_peak_recession_diagnostics.py
node --check HBV-Studio\web\app.js
```

`check_peak_recession_diagnostics.py` 已确认合成统一目标函数输出包含：

- `daily_unified_professional_v1`
- `flow_guard`
- `secondary_terms`
- `ice_dominance_guard`
- `glacier_fraction_report`
- `peak_source_report`
- `recession_takeover_diagnostic`

该脚本同时确认：旧 Demo 元数据在缺少新保护项字段时仍能兼容加载，并保持旧目标函数族为 `weighted_daily_universal`。

相关后端和开发工具 Python 文件已通过 `ast.parse` 语法检查。

## 产品边界

开发侧检查工具保留在 `dev_tools`：

- `dev_tools/check_peak_recession_diagnostics.py`
- `dev_tools/studio_ui_acceptance.py`

上述工具未接入普通 Studio UI。BM-02 调参/搜索脚本未通过产品 Web UI 暴露。

产品目标函数选择器仍保持单一选项：`daily_unified_professional_v1`。旧目标函数名称只用于历史结果标记和兼容显示。

产品运行时代码中未硬编码 `memories\studio_acceptance\...` 这类验收临时路径。该路径只出现在本记录、生成的日志/验收产物，以及开发侧验收工具的默认输出位置。
