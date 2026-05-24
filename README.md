# HBV-Cryo

当前工程分成两条主线：

- `HBV-Cryo/`：HBV 主干、两分区 `CFMAX`、冰川融冰、组分追踪、边界入流、马斯京根汇流、差分进化率定
- `HBV-Studio/`：独立 GUI 子系统，提供配置管理、任务调度、结果可视化与诊断面板

当前模型设定：

- `CFMAX` 采用单阈值两分区
- `UZL` 参与率定
- 温度修正固定关闭
- 冰川模块和上游边界入流均为可选模块
- 若存在 `glacier_melt` 参考序列，结果会自动输出融冰对比指标
- 核心已支持可配置时间步长，默认 `24 h`，可切换到 `1 h`

常用入口：

1. 修改 `配置/流域配置模板.json`
2. 按 `数据准备/数据准备说明.md` 准备输入
3. 运行 `HBV-Cryo/01_训练率定.py`
4. 或运行 `python HBV-Studio/launch.py`

## 开发与交接说明

给后续 Codex / 开发者先读这一段：

- 本目录 `HBV-cryo\` 是唯一源码仓库；远端为 `git@github.com:ding-ni/HBV-cryo.git`。
- 当前主要工作分支是 `feature/meteo-workflow-cleanup`。
- 上层 `HBVStudio_Demo\`、`hbvstudio_packaging\`、`_build_temp\` 和安装目录 `F:\HBVStudio` 都是派生/打包/安装产物，除非明确要求，不要把它们当源码直接改。
- `基础数据\`、`运行目录\`、`用户数据\`、安装包、压缩包、栅格、NetCDF、shp 等本地大文件不提交到 GitHub。
- 新对话接手时，先看 `README.md`、`git status --short --branch`、`git log --oneline -n 8`，再决定修改位置。
- 改完源码后，先在本仓库内验证，再 `git add`、`git commit`、`git push origin feature/meteo-workflow-cleanup`。
- 需要给用户测试安装版时，从本目录运行打包脚本，例如：`python HBV-Studio\build_windows_installer.py --version 2026.05.24-meteo-shp-staging`。

2026-05-24 的当前状态：

- 已接入 ERA5 降水下载、处理、对齐和率定入口；新工程默认降水源为 ERA5。
- 新工作区默认创建 `数据/模型输入/降水`、`气温`、`蒸散发`，不再默认创建 `降水_MSWEP` 和 `冰川融水`。
- MSWEP/CMFD 当前按“本地原始文件”处理，不再在界面备注里暗示已有自动下载链路或固定 1 km 尺度。
- 向导第 2 步会归档观测 Excel/CSV 到 `数据/观测数据`。
- 向导第 2 步会归档流域 shp 到 `数据/地理数据/basin.shp`，归档冰川 shp 到 `数据/地理数据/glacier_shp/glacier.shp`，并同步复制 `.dbf`、`.shx`、`.prj`、`.cpg` 等旁路文件。
- 最新安装包为 `_build_temp\installer_packaging\output\HBVStudio_Setup_2026.05.24-meteo-shp-staging.exe`，SHA256 为 `4ABB85923C437C8CDFCFF2DC5F9A583F7F45BC73FC5875B7C4DE18F74447D48F`。
