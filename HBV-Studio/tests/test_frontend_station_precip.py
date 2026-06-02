import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendStationPrecipTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_mode_labels_descriptions_and_validation_lookup(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/stationPrecip.js", "utf8"), context);

            const station = context.window.HBVStudioStationPrecip;
            if (!station) throw new Error("station precipitation module was not exported");

            if (station.stationPrecipModeLabel("grid_only") !== "格点直接使用") {
              throw new Error("grid-only label mismatch");
            }
            if (station.stationPrecipModeLabel("grid_plus_station_bias") !== "格点 + 站点偏差订正") {
              throw new Error("station-bias label mismatch");
            }
            if (station.stationPrecipModeLabel("thiessen_station_only") !== "纯泰森多边形插值") {
              throw new Error("thiessen label mismatch");
            }
            if (station.stationPrecipModeLabel("unknown_mode") !== "格点直接使用") {
              throw new Error("unknown mode should fall back to grid-only label");
            }

            const biasDescription = station.stationPrecipModeDescription("grid_plus_station_bias");
            if (!biasDescription.includes("修正格点降水")) throw new Error(`unexpected bias description: ${biasDescription}`);
            const thiessenDescription = station.stationPrecipModeDescription("thiessen_station_only");
            if (!thiessenDescription.includes("站点降水直接生成面降水")) throw new Error(`unexpected thiessen description: ${thiessenDescription}`);
            const gridDescription = station.stationPrecipModeDescription("grid_only");
            if (!gridDescription.includes("当前格点数据源")) throw new Error(`unexpected grid description: ${gridDescription}`);

            const byId = { id: "station_precip", title: "其他标题" };
            const byTitle = { id: "other", title: "站点降水专项检查" };
            const validation = { focus_checks: [{ id: "glacier" }, byId, byTitle] };
            if (station.stationPrecipCheckFromValidation(validation) !== byId) {
              throw new Error("station check should prefer canonical id");
            }
            const titleOnly = { focus_checks: [{ id: "glacier" }, byTitle] };
            if (station.stationPrecipCheckFromValidation(titleOnly) !== byTitle) {
              throw new Error("station check should fall back to title match");
            }
            if (station.stationPrecipCheckFromValidation({ focus_checks: [{ id: "glacier" }] }) !== null) {
              throw new Error("missing station check should return null");
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_strategy_status_cards_render_selected_mode_and_station_files(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/stationPrecip.js", "utf8"), context);

            const station = context.window.HBVStudioStationPrecip;
            const gridHtml = station.renderPrecipStrategyStatusCards({ mode: "grid_only" });
            if (!gridHtml.includes("格点直接使用")) throw new Error("grid mode label missing");
            if (!gridHtml.includes("未启用站点资料")) throw new Error("grid mode status missing");
            if ((gridHtml.match(/不需要/g) || []).length !== 2) {
              throw new Error(`grid mode should mark both station files as unnecessary: ${gridHtml}`);
            }

            const stationHtml = station.renderPrecipStrategyStatusCards(
              {
                mode: "grid_plus_station_bias",
                stationPrec: "C:/input/prec.csv",
                stationMeta: "C:/input/meta.csv",
              },
              {
                shortPath: value => String(value).split("/").pop(),
              },
            );
            if (!stationHtml.includes("格点 + 站点偏差订正")) throw new Error("station mode label missing");
            if (!stationHtml.includes("站点资料已登记")) throw new Error("station ready status missing");
            if (!stationHtml.includes(">prec.csv<")) throw new Error("station precipitation short path missing");
            if (!stationHtml.includes(">meta.csv<")) throw new Error("station metadata short path missing");
            if ((stationHtml.match(/status-ok/g) || []).length < 3) {
              throw new Error(`station-ready mode should render all cards as ok: ${stationHtml}`);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_fallback_check_summarizes_station_precip_readiness(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/stationPrecip.js", "utf8"), context);

            const station = context.window.HBVStudioStationPrecip;
            const grid = station.stationPrecipFallbackCheck({ mode: "grid_only" });
            if (grid.status !== "ok") throw new Error(`grid fallback status mismatch: ${grid.status}`);
            if (!grid.summary.includes("不会执行站点降水订正专项分析")) {
              throw new Error(`grid summary mismatch: ${grid.summary}`);
            }
            if (grid.items[0].status !== "warn" || grid.items[0].value !== "格点直接使用") {
              throw new Error(`grid mode item mismatch: ${JSON.stringify(grid.items[0])}`);
            }
            if (grid.items[1].value !== "不需要" || grid.items[2].value !== "不需要") {
              throw new Error(`grid station file items mismatch: ${JSON.stringify(grid.items)}`);
            }

            const missing = station.stationPrecipFallbackCheck({ mode: "grid_plus_station_bias" });
            if (missing.status !== "fail") throw new Error(`missing station files should fail: ${missing.status}`);
            if (missing.items[1].value !== "缺失" || missing.items[1].status !== "fail") {
              throw new Error(`missing station precipitation item mismatch: ${JSON.stringify(missing.items[1])}`);
            }
            if (missing.items[2].value !== "缺失" || missing.items[2].status !== "fail") {
              throw new Error(`missing station metadata item mismatch: ${JSON.stringify(missing.items[2])}`);
            }

            const ready = station.stationPrecipFallbackCheck(
              {
                mode: "thiessen_station_only",
                stationPrec: "D:/data/prec.csv",
                stationMeta: "D:/data/meta.csv",
              },
              {
                shortPath: value => String(value).split("/").pop(),
              },
            );
            if (ready.status !== "warn") throw new Error(`ready station files should await validation: ${ready.status}`);
            if (!ready.summary.includes("输入检查会判断资料是否可用")) {
              throw new Error(`ready summary mismatch: ${ready.summary}`);
            }
            if (ready.items[0].value !== "纯泰森多边形插值" || ready.items[0].status !== "ok") {
              throw new Error(`ready mode item mismatch: ${JSON.stringify(ready.items[0])}`);
            }
            if (ready.items[1].value !== "prec.csv" || ready.items[2].value !== "meta.csv") {
              throw new Error(`ready station file short paths mismatch: ${JSON.stringify(ready.items)}`);
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_station_event_coverage_combines_scope_and_problem_events(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/stationPrecip.js", "utf8"), context);

            const station = context.window.HBVStudioStationPrecip;
            const html = station.renderStationEventCoverage({
              status: "warn",
              task_context: {
                status: "warn",
                headline: "检查 2 场洪水事件的站点资料",
                detail: "覆盖率不足的事件会单独列出。",
                station_time_range: { start: "2000-01-01", end: "2001-01-01" },
                items: [
                  { label: "任务尺度", value: "小时", status: "ok" },
                ],
              },
              event_coverage_summary: { ok_count: 1, event_count: 2 },
              event_coverage: [
                {
                  event_id: "EVT-001",
                  name: "一号洪水",
                  status: "fail",
                  coverage_ratio: 0.5,
                  available_station_min: 0,
                  available_station_mean: 1.25,
                  zero_available_steps: 2,
                  max_consecutive_zero_steps: 1,
                },
                {
                  event_id: "EVT-002",
                  name: "二号洪水",
                  status: "ok",
                  coverage_ratio: 1,
                  available_station_min: 3,
                  available_station_mean: 4,
                },
              ],
            });
            if (!html.includes("站点降水检查口径")) throw new Error("task scope block missing");
            if (!html.includes("检查 2 场洪水事件的站点资料")) throw new Error("scope headline missing");
            if (!html.includes("2000-01-01 至 2001-01-01")) throw new Error("station time range missing");
            if (!html.includes("洪水事件站点覆盖")) throw new Error("event coverage block missing");
            if (!html.includes("1/2 场可用")) throw new Error("event coverage summary missing");
            if (!html.includes("一号洪水")) throw new Error("problem event row missing");
            if (!html.includes("50.0%")) throw new Error("coverage percent missing");
            if (html.includes("二号洪水")) throw new Error("ok event should not be listed as a problem row");
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=STUDIO_DIR,
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
