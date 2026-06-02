import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendDataPrepViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_data_prep_step_list_renders_status_actions_and_dependencies(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/dataPrepView.js", "utf8"), context);

            const view = context.window.HBVStudioDataPrepView;
            if (!view?.formatPrepDisplayTitle || !view?.formatPrepBlockedMessage || !view?.prepTaskUiState || !view?.renderBootstrapStatus || !view?.renderInputCheckError || !view?.renderInputCheckImportBlock || !view?.renderInputCheckProgress || !view?.renderInputCheckResults || !view?.renderPrepStepList) {
              throw new Error("data prep view exports are missing");
            }
            const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              "\"": "&quot;",
              "'": "&#39;",
            }[ch]));
            const helpers = { escapeHtml, isGisStepId: id => id === "gis_base" };

            if (view.formatPrepDisplayTitle(2, "01. 下载 ERA5") !== "2. 下载 ERA5") {
              throw new Error("display title should strip stale numbering");
            }
            const blockedText = view.formatPrepBlockedMessage(
              { blocked_by: ["gis_base", "download_era5"] },
              [{ id: "download_era5", displayTitle: "1. 下载 ERA5" }],
              [],
              helpers,
            );
            if (blockedText !== "依赖未满足：请先完成 第 5 步地理数据、下载 ERA5。") {
              throw new Error(`blocked message mismatch: ${blockedText}`);
            }

            const html = view.renderPrepStepList({
              workspaceSelected: true,
              steps: [
                {
                  id: "download_era5",
                  displayTitle: "1. 下载 ERA5 <raw>",
                  displayDescription: "下载气象驱动 & 校验",
                  supports_overwrite: true,
                },
                {
                  id: "align_inputs",
                  displayTitle: "2. 写入工程目录",
                  displayDescription: "裁剪对齐到 DEM",
                },
                {
                  id: "manual_station",
                  displayTitle: "3. 补充站点资料",
                  displayDescription: "人工补充",
                  manual: true,
                },
              ],
              allSteps: [
                { id: "download_era5", title: "下载 ERA5" },
                { id: "gis_base", title: "基础地理数据" },
              ],
              prepStatus: {
                download_era5: { done: true, message: "已完成，可重跑" },
                align_inputs: { blocked_by: ["gis_base", "download_era5"] },
                manual_station: { manual: true, message: "请补充站点表" },
              },
            }, helpers);

            if (!html.includes("1. 下载 ERA5 &lt;raw&gt;") || html.includes("1. 下载 ERA5 <raw>")) {
              throw new Error(`step title should be escaped: ${html}`);
            }
            if (!html.includes("下载气象驱动 &amp; 校验")) throw new Error("description should be escaped");
            if (!html.includes("status-badge status-ok") || !html.includes(">已完成<")) throw new Error("done status missing");
            if (!html.includes('data-run-step="download_era5"') || !html.includes(">重新运行<")) throw new Error("rerun button missing");
            if (!html.includes('data-run-step-overwrite="download_era5"') || !html.includes(">覆盖重跑<")) throw new Error("overwrite button missing");
            if (!html.includes("status-badge status-fail") || !html.includes("依赖未满足：请先完成 第 5 步地理数据、下载 ERA5 &lt;raw&gt;。")) {
              throw new Error(`blocked step missing: ${html}`);
            }
            if (!html.includes('data-run-step="align_inputs" disabled')) throw new Error("blocked step should be disabled");
            if (html.includes('data-run-step="manual_station"')) throw new Error("manual step should not render run button");
            if (!html.includes(">需补充资料<")) throw new Error("manual status missing");

            const noWorkspace = view.renderPrepStepList({ workspaceSelected: false, emptyText: "请选择 <workspace>" }, helpers);
            if (!noWorkspace.includes("请选择 &lt;workspace&gt;")) throw new Error("empty workspace text should be escaped");
            const noSteps = view.renderPrepStepList({ workspaceSelected: true, steps: [], noStepsText: "无步骤 <ok>" }, helpers);
            if (!noSteps.includes("无步骤 &lt;ok&gt;")) throw new Error("no steps text should be escaped");

            const bootstrapHtml = view.renderBootstrapStatus([
              { id: "dem", title: "裁剪 DEM <1>", done: true, message: "已完成 & 可复核" },
              { id: "flow_acc", title: "生成流向", done: false, message: "等待执行" },
              { id: "glacier", title: "冰川高程", done: false, optional: true, message: "当前未启用冰川边界" },
            ], helpers);
            if (!bootstrapHtml.includes("bootstrap-item done") || !bootstrapHtml.includes("status-badge status-ok") || !bootstrapHtml.includes(">已完成<")) {
              throw new Error(`bootstrap done item missing: ${bootstrapHtml}`);
            }
            if (!bootstrapHtml.includes("裁剪 DEM &lt;1&gt;") || bootstrapHtml.includes("裁剪 DEM <1>")) {
              throw new Error("bootstrap title should be escaped");
            }
            if (!bootstrapHtml.includes("已完成 &amp; 可复核")) throw new Error("bootstrap message should be escaped");
            if (!bootstrapHtml.includes("status-badge status-warn") || !bootstrapHtml.includes(">待执行<")) {
              throw new Error("bootstrap pending item missing");
            }
            if (!bootstrapHtml.includes("status-badge \">未启用<")) throw new Error("bootstrap optional disabled item missing");
            const emptyBootstrap = view.renderBootstrapStatus([], helpers);
            if (!emptyBootstrap.includes("暂无 GIS 步骤状态信息。")) throw new Error("empty bootstrap state missing");

            const prepTaskState = view.prepTaskUiState({
              status: "running",
              label: "默认标签",
              ui_progress: { stage: "裁剪栅格", label: "DEM <tile>", current: 3, total: 9 },
              output: Array.from({ length: 122 }, (_, index) => `日志 ${index}`),
            });
            if (prepTaskState.hint.text !== "裁剪栅格：DEM <tile>（3/9）" || prepTaskState.hint.className !== "hint-box status-warn") {
              throw new Error(`running prep task state mismatch: ${JSON.stringify(prepTaskState)}`);
            }
            if (!prepTaskState.log.visible || prepTaskState.log.lines.length !== 120 || prepTaskState.log.lines[0] !== "日志 2" || prepTaskState.log.key !== "wizard:pipeline-log") {
              throw new Error(`prep task logs should be capped: ${JSON.stringify(prepTaskState.log)}`);
            }
            const completedPrepState = view.prepTaskUiState({ status: "completed", step_title: "写入工程目录" });
            if (completedPrepState.hint.text !== "已完成：写入工程目录" || completedPrepState.hint.className !== "hint-box status-ok" || completedPrepState.log.visible) {
              throw new Error(`completed prep task state mismatch: ${JSON.stringify(completedPrepState)}`);
            }
            const failedPrepState = view.prepTaskUiState({ status: "failed" });
            if (failedPrepState.hint.text !== "执行失败：数据处理" || failedPrepState.hint.className !== "hint-box status-fail") {
              throw new Error(`failed prep task fallback mismatch: ${JSON.stringify(failedPrepState)}`);
            }

            const importBlock = view.renderInputCheckImportBlock({
              ui_progress: {
                stage: "导入 ERA5 <daily>",
                current: 2,
                total: 5,
                label: "降水 & 气温",
                item_current: 3,
                item_total: 8,
                timestamp: "2026-06-03 <09:00>",
              },
              output: Array.from({ length: 22 }, (_, index) => `日志 ${index} <raw>`),
            }, helpers);
            if (!importBlock.includes("当前正在导入气象驱动") || !importBlock.includes("导入 ERA5 &lt;daily&gt;：总进度 2/5")) {
              throw new Error(`import block progress missing: ${importBlock}`);
            }
            if (!importBlock.includes("降水 &amp; 气温 3/8") || !importBlock.includes("2026-06-03 &lt;09:00&gt;")) {
              throw new Error("import block detail should be escaped");
            }
            if (!importBlock.includes("task-output-box") || !importBlock.includes("日志 21 &lt;raw&gt;") || importBlock.includes("日志 1 &lt;raw&gt;")) {
              throw new Error("import block should show only the latest escaped logs");
            }

            const progressHtml = view.renderInputCheckProgress({ stage: "基础配置检查 <A>", elapsed: 4 }, helpers);
            if (!progressHtml.includes("基础配置检查 &lt;A&gt;") || !progressHtml.includes("已用时 4 秒") || progressHtml.includes("status-warn")) {
              throw new Error(`short input check progress failed: ${progressHtml}`);
            }
            const longProgressHtml = view.renderInputCheckProgress({ stage: "详细输入检查", elapsed: 31 }, helpers);
            if (!longProgressHtml.includes("status-warn") || !longProgressHtml.includes("数据量较大时可能需要数分钟")) {
              throw new Error(`long input check progress failed: ${longProgressHtml}`);
            }
            const errorHtml = view.renderInputCheckError({ message: "缺少文件 <dem>", stage: "详细输入检查 <B>", elapsed: 9 }, helpers);
            if (!errorHtml.includes("检查失败：缺少文件 &lt;dem&gt;") || !errorHtml.includes("失败阶段：详细输入检查 &lt;B&gt;；已用时 9 秒")) {
              throw new Error(`input check error should be escaped: ${errorHtml}`);
            }

            const checkHelpers = {
              ...helpers,
              inferIssueTarget(detail, targetStep) {
                return String(detail || "").includes("第 3 步")
                  ? { step: targetStep, selector: "#wz-boundary <bad>" }
                  : null;
              },
              renderEngineeringFocusChecks(checks, options) {
                return `<div class="focus-checks">${escapeHtml(options.title)}:${checks.length}</div>`;
              },
              renderIssueJumpButton(item, step) {
                return `<button data-jump="${escapeHtml(item)}" data-step="${escapeHtml(step)}">定位</button>`;
              },
              renderValidationEventSections(validation) {
                return `<section class="event-section">${escapeHtml(validation.eventName || "事件 <x>")}</section>`;
              },
            };
            const checkHtml = view.renderInputCheckResults({
              validation: { valid: false, eventName: "洪水 <A>", focus_checks: [{ id: "range" }] },
              comp: {
                ready: false,
                missing: ["缺少 DEM <tif>"],
                warnings: ["站点偏少 & 待确认"],
              },
              detail: true,
              stage: "calibration",
              detailData: {
                reasonableness_checks: [{ id: "flow" }],
                summary: [
                  { group: "水文 <组>", label: "流量 & 单位", value: "m3/s <bad>", ok: true },
                  { group: "水文 <组>", label: "缺项", value: "空", ok: false },
                ],
              },
              advice: {
                recommendations: [
                  { title: "补充资料 <A>", detail: "回到第 3 步 & 导入", target_step: 3 },
                  { title: "检查站点", detail: "核对雨量站" },
                  { title: "检查边界", detail: "核对边界" },
                  { title: "检查气象", detail: "核对气象" },
                  { title: "第五条不显示", detail: "不应渲染" },
                ],
              },
            }, checkHelpers);
            if (!checkHtml.includes("洪水 &lt;A&gt;") || checkHtml.includes("洪水 <A>")) {
              throw new Error(`event section should be escaped: ${checkHtml}`);
            }
            if (!checkHtml.includes("以下数据缺失或配置不完整") || !checkHtml.includes("缺少 DEM &lt;tif&gt;")) {
              throw new Error(`missing item section failed: ${checkHtml}`);
            }
            if (!checkHtml.includes("站点偏少 &amp; 待确认") || !checkHtml.includes('data-jump="站点偏少 &amp; 待确认"')) {
              throw new Error(`warning section failed: ${checkHtml}`);
            }
            if (!checkHtml.includes("专项工程检查") || !checkHtml.includes("专项工程检查:1")) {
              throw new Error("focus checks should be rendered");
            }
            if (!checkHtml.includes("数值合理性检查") || !checkHtml.includes("数值合理性检查:1")) {
              throw new Error("reasonableness checks should be rendered");
            }
            if (!checkHtml.includes("智能建议") || !checkHtml.includes("补充资料 &lt;A&gt;") || !checkHtml.includes('data-go-step="3"')) {
              throw new Error(`recommendations failed: ${checkHtml}`);
            }
            if (!checkHtml.includes('data-go-selector="#wz-boundary &lt;bad&gt;"')) {
              throw new Error("recommendation selector should be escaped");
            }
            if (checkHtml.includes("第五条不显示")) throw new Error("recommendations should be limited to four items");
            if (!checkHtml.includes("水文 &lt;组&gt;") || !checkHtml.includes("流量 &amp; 单位") || !checkHtml.includes("m3/s &lt;bad&gt;")) {
              throw new Error(`detail table should be escaped: ${checkHtml}`);
            }
            if (!checkHtml.includes("check-row status-ok") || !checkHtml.includes("check-row status-fail")) {
              throw new Error("detail table status classes missing");
            }

            const overviewHtml = view.renderInputCheckResults({
              validation: { valid: true },
              comp: { ready: true, missing: [], warnings: [] },
              detail: false,
              stage: "quick_test",
            }, checkHelpers);
            if (!overviewHtml.includes("输入预核算所需数据已就位") || !overviewHtml.includes("当前显示的是输入检查概览")) {
              throw new Error(`overview input check state failed: ${overviewHtml}`);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
