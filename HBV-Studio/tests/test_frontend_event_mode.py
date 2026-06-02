import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendEventModeTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_flood_event_summary_rows_and_labels(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/eventMode.js", "utf8"), context);

            const eventMode = context.window.HBVStudioEventMode;
            if (!eventMode) throw new Error("event mode module was not exported");

            const evaluation = {
              enabled: true,
              objective_enabled: true,
              valid_event_count: 2,
              event_count: 3,
              summary: { all: { mean_diagnostic_objective: 0.123456 } },
              events: Array.from({ length: 13 }, (_, index) => ({
                name: index === 0 ? "2020-07 洪水" : "",
                peak_error_percent: index + 0.125,
                peak_time_error_hours: index + 0.5,
                volume_error_percent: index + 0.75,
                nse: 0.8 + index / 100,
                kge: 0.7 + index / 100,
              })),
            };
            const meta = {
              diagnostics: { flood_event_evaluation: evaluation },
              event_mode: {
                enabled: true,
                runtime_mode: "independent_event_windows",
                event_count: 3,
                initial_state_policy: "source_state",
              },
            };

            if (eventMode.floodEventEvaluation(meta) !== evaluation) {
              throw new Error("evaluation fallback path mismatch");
            }
            if (eventMode.floodEventStatusText(evaluation) !== "事件目标函数：2/3 场有效") {
              throw new Error("status text mismatch");
            }
            if (eventMode.floodEventObjectiveText(evaluation) !== "0.1235") {
              throw new Error("objective text mismatch");
            }
            if (eventMode.initialStatePolicyLabel("source_state") !== "来源状态") {
              throw new Error("initial state policy label mismatch");
            }

            const rows = eventMode.floodEventRows(meta);
            if (rows.length !== 16) throw new Error(`unexpected row count: ${rows.length}`);
            if (rows[0][0] !== "事件评价" || rows[0][1] !== "事件目标函数：2/3 场有效") {
              throw new Error(`unexpected first row: ${JSON.stringify(rows[0])}`);
            }
            if (rows[1][0] !== "事件目标值" || rows[1][1] !== "0.1235") {
              throw new Error(`unexpected objective row: ${JSON.stringify(rows[1])}`);
            }
            if (rows[2][0] !== "事件资料模式" || rows[2][1] !== "事件窗口独立运行，3 场" || rows[2][2] !== "初始条件：来源状态") {
              throw new Error(`unexpected event runtime row: ${JSON.stringify(rows[2])}`);
            }
            if (rows[3][0] !== "2020-07 洪水" || rows[3][1] !== "洪峰 0.13% / 峰现 0.5 h / 洪量 0.75%") {
              throw new Error(`unexpected event metric row: ${JSON.stringify(rows[3])}`);
            }
            const more = rows[rows.length - 1];
            if (more[0] !== "更多事件" || more[1] !== "还有 1 场") {
              throw new Error(`unexpected overflow row: ${JSON.stringify(more)}`);
            }

            const metricItems = eventMode.floodEventMetricItems(meta);
            if (metricItems.length !== 2) throw new Error(`unexpected metric item count: ${metricItems.length}`);
            if (metricItems[0].l !== "洪水事件" || metricItems[0].v !== "事件目标函数：2/3 场有效") {
              throw new Error(`unexpected flood event metric item: ${JSON.stringify(metricItems[0])}`);
            }
            if (metricItems[1].l !== "事件目标值" || metricItems[1].v !== "0.1235") {
              throw new Error(`unexpected flood event objective metric item: ${JSON.stringify(metricItems[1])}`);
            }
            if (eventMode.floodEventMetricItems({}).length !== 0) {
              throw new Error("disabled event evaluation should not add metric strip items");
            }

            if (eventMode.floodEventStatusText({ enabled: false }) !== "未启用") {
              throw new Error("disabled status mismatch");
            }
            if (eventMode.floodEventRows({}).length !== 0) {
              throw new Error("disabled rows should be empty");
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

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_wizard_event_and_input_time_summaries_render_safely(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/eventMode.js", "utf8"), context);

            const eventMode = context.window.HBVStudioEventMode;
            for (const name of ["eventModeHintState", "renderWizardEventSummary", "wizardEventSummaryState", "renderInputTimeSummary"]) {
              if (typeof eventMode?.[name] !== "function") throw new Error(`missing event export: ${name}`);
            }
            const helpers = {
              escapeHtml(value) {
                return String(value ?? "").replace(/[&<>"']/g, ch => ({
                  "&": "&amp;",
                  "<": "&lt;",
                  ">": "&gt;",
                  "\"": "&quot;",
                  "'": "&#39;",
                }[ch]));
              },
              statusClass(status) {
                return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
              },
              shortPath(value) { return String(value || "").split(/[\\/]/).pop() || ""; },
            };

            const continuousHint = eventMode.eventModeHintState({ basis: "continuous" });
            if (continuousHint.className !== "hint-box" || !continuousHint.text.includes("连续时段要求完整覆盖")) {
              throw new Error(`continuous event hint mismatch: ${JSON.stringify(continuousHint)}`);
            }
            const missingEventFileHint = eventMode.eventModeHintState({ basis: "event_windows", eventFile: "" });
            if (missingEventFileHint.className !== "hint-box status-warn" || !missingEventFileHint.text.includes("请提供事件表")) {
              throw new Error(`missing event file hint mismatch: ${JSON.stringify(missingEventFileHint)}`);
            }
            const eventFileHint = eventMode.eventModeHintState({ basis: "event_windows", eventFile: "C:/events/flood.csv" });
            if (eventFileHint.className !== "hint-box status-ok" || !eventFileHint.text.includes("当前按洪水事件组织资料")) {
              throw new Error(`event file hint mismatch: ${JSON.stringify(eventFileHint)}`);
            }

            const html = eventMode.renderWizardEventSummary({
              event_count: 2,
              valid_event_count: 1,
              source_file: "C:/events/floods.csv",
              events: [
                { event_id: "E1", name: "洪水<一>", valid: true, score_start: "2020-07-01", score_end: "2020-07-02" },
                { event_id: "E2", name: "洪水二", valid: false, score_start: "2020-08-01", score_end: "2020-08-02" },
              ],
              warnings: ["第二场缺少退水段"],
            }, {
              enabled: true,
              status: "fail",
              event_count: 2,
              complete_event_count: 1,
              events: [
                {
                  event_id: "E1",
                  name: "洪水<一>",
                  status: "ok",
                  expected_steps: 24,
                  covered_steps: 24,
                  score_start: "2020-07-01",
                  score_end: "2020-07-02",
                },
                {
                  event_id: "E2",
                  name: "洪水二",
                  status: "fail",
                  expected_steps: 24,
                  covered_steps: 12,
                  missing_steps: 12,
                  missing_preview: ["2020-08-02"],
                  score_start: "2020-08-01",
                  score_end: "2020-08-02",
                },
              ],
            }, helpers);
            if (!html.includes("洪水事件表") || !html.includes("事件流量覆盖")) {
              throw new Error(`event and observation summaries should be combined: ${html}`);
            }
            if (!html.includes("洪水&lt;一&gt;") || html.includes("洪水<一>")) {
              throw new Error(`event names should be escaped: ${html}`);
            }
            if (!html.includes("1/2 场完整") || !html.includes("缺 12")) {
              throw new Error(`observation coverage details missing: ${html}`);
            }
            const stateHtml = eventMode.renderWizardEventSummary({
              event_count: 1,
              valid_event_count: 1,
              source_file: "C:/events/floods.csv",
              events: [
                { event_id: "E1", name: "洪水<一>", valid: true, score_start: "2020-07-01", score_end: "2020-07-02" },
              ],
            }, null, helpers);
            const summaryState = eventMode.wizardEventSummaryState({
              event_count: 1,
              valid_event_count: 1,
              source_file: "C:/events/floods.csv",
              events: [
                { event_id: "E1", name: "洪水<一>", valid: true, score_start: "2020-07-01", score_end: "2020-07-02" },
              ],
            }, null, helpers);
            const summaryDom = Object.fromEntries(summaryState.domUpdates.map(update => [update.selector, update]));
            if (summaryState.html !== stateHtml || summaryDom["#wz-event-file-summary"].html !== stateHtml) {
              throw new Error(`unexpected wizard event DOM updates: ${JSON.stringify(summaryState)}`);
            }

            const inputHtml = eventMode.renderInputTimeSummary({
              status: "warn",
              headline: "资料时段需复核<A>",
              detail: "事件之间允许间断&连续模式不同",
              items: [
                { label: "事件数", value: "2" },
                { label: "窗口", value: "2020-07-01 ~ 2020-08-02" },
              ],
            }, helpers);
            if (!inputHtml.includes("input-time-summary status-warn") || !inputHtml.includes("资料时段需复核&lt;A&gt;")) {
              throw new Error(`input time summary status or headline wrong: ${inputHtml}`);
            }
            if (!inputHtml.includes("事件之间允许间断&amp;连续模式不同") || !inputHtml.includes("<strong>事件数</strong>2")) {
              throw new Error(`input time summary details missing: ${inputHtml}`);
            }
            if (eventMode.renderInputTimeSummary({}, helpers) !== "") {
              throw new Error("empty input time summary should render empty string");
            }
            if (eventMode.renderWizardEventSummary(null, null, helpers) !== "") {
              throw new Error("empty wizard event summary should render empty string");
            }
            const emptySummaryState = eventMode.wizardEventSummaryState(null, null, helpers);
            const emptySummaryDom = Object.fromEntries(emptySummaryState.domUpdates.map(update => [update.selector, update]));
            if (emptySummaryState.html !== "" || emptySummaryDom["#wz-event-file-summary"].html !== "") {
              throw new Error(`empty wizard event summary DOM updates wrong: ${JSON.stringify(emptySummaryState)}`);
            }

            const validationHtml = eventMode.renderValidationEventSections({
              input_time_summary: {
                status: "warn",
                headline: "事件资料时段需复核",
                detail: "事件窗口可以不连续",
              },
              event_windows: {
                event_count: 1,
                valid_event_count: 1,
                source_file: "C:/events/flood.csv",
                events: [
                  { event_id: "E1", name: "一号洪水", valid: true, score_start: "2020-07-01", score_end: "2020-07-02" },
                ],
              },
              event_forcing_coverage: {
                enabled: true,
                status: "warn",
                event_count: 1,
                complete_event_count: 0,
                events: [
                  {
                    event_id: "E1",
                    name: "一号洪水",
                    status: "warn",
                    run_start: "2020-07-01",
                    run_end: "2020-07-02",
                    variables: {
                      prec: { label: "降水", covered_steps: 20, expected_steps: 24, missing_steps: 4 },
                    },
                  },
                ],
              },
              event_observation_coverage: {
                enabled: true,
                status: "ok",
                event_count: 1,
                complete_event_count: 1,
                events: [
                  {
                    event_id: "E1",
                    name: "一号洪水",
                    status: "ok",
                    score_start: "2020-07-01",
                    score_end: "2020-07-02",
                    expected_steps: 24,
                    covered_steps: 24,
                  },
                ],
              },
            }, helpers);
            for (const text of ["事件资料时段需复核", "洪水事件表", "事件内气象覆盖", "事件流量覆盖"]) {
              if (!validationHtml.includes(text)) {
                throw new Error(`validation event section missing ${text}: ${validationHtml}`);
              }
            }
            if (!validationHtml.includes("flood.csv") || !validationHtml.includes("降水 20/24，缺 4")) {
              throw new Error(`validation event section details missing: ${validationHtml}`);
            }
            if (eventMode.renderValidationEventSections(null, helpers) !== "") {
              throw new Error("empty validation event sections should render empty string");
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
