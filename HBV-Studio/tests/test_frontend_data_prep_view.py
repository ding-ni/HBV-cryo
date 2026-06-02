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
            if (!view?.formatPrepDisplayTitle || !view?.formatPrepBlockedMessage || !view?.renderPrepStepList) {
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
