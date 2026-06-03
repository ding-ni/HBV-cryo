import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendWorkspaceLayoutTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_workspace_layout_html_embeds_geo_preview_and_actions(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/workspaceLayout.js", "utf8"), context);

            const layout = context.window.HBVStudioWorkspaceLayout;
            if (!layout?.workspaceLayoutHtml || !layout?.workspaceLayoutQueryState || !layout?.render) {
              throw new Error("workspace layout exports are missing");
            }
            const layoutQuery = layout.workspaceLayoutQueryState({ configPath: " F:/工作区/A & B " });
            const encodedPath = encodeURIComponent("F:/工作区/A & B");
            if (!layoutQuery.ready || layoutQuery.configPath !== "F:/工作区/A & B" || layoutQuery.layoutPath !== `/api/workspace/layout?config_path=${encodedPath}`) {
              throw new Error(`workspace layout query mismatch: ${JSON.stringify(layoutQuery)}`);
            }
            const missingLayoutQuery = layout.workspaceLayoutQueryState({ configPath: " " });
            if (missingLayoutQuery.ready || missingLayoutQuery.message !== "请选择工作区。" || !missingLayoutQuery.layoutPath.includes("config_path=")) {
              throw new Error(`missing workspace layout query mismatch: ${JSON.stringify(missingLayoutQuery)}`);
            }
            const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              "\"": "&quot;",
              "'": "&#39;",
            }[ch]));
            const model = {
              flow_name: "玛曲<A>",
              profile_label: "日尺度",
              config_path: "C:/ws/config.json",
              workspace_root: "C:/ws/root",
              results_root: "C:/ws/results",
              headline: "目录结构已建立",
              next_focus: { label: "地理数据", reason: "先完成 DEM 与高程分区。" },
              geo_overview: { available_layer_count: 3 },
              groups: [
                {
                  title: "输入资料",
                  items: [
                    {
                      label: "地理资料",
                      path: "C:/ws/data/gis",
                      display_path: "C:/ws/data/gis",
                      exists: true,
                      kind: "dir",
                      count: 4,
                      status: "已创建",
                      purpose: "流域边界、DEM、高程带和冰川图层。",
                      stage_hint: "第 5 步生成",
                      target_step: 5,
                    },
                  ],
                },
              ],
              notes: ["不要在这里放内部调试文件 <debug>"],
            };
            const helpers = {
              escapeHtml,
              slashPath: value => String(value || "").replace(/\\/g, "/"),
              renderGeoOverview: overview => `<section class="geo-preview-card" data-layer-count="${escapeHtml(overview.available_layer_count)}">空间预览</section>`,
            };

            const html = layout.workspaceLayoutHtml(model, { title: "工作区目录结构", subtitle: "当前工程" }, helpers);
            if (!html.includes("玛曲&lt;A&gt; · 工作区目录结构")) throw new Error(`title was not escaped: ${html}`);
            if (!html.includes("当前工程")) throw new Error("explicit subtitle missing");
            if (!html.includes('class="geo-preview-card" data-layer-count="3"')) throw new Error("geo preview was not embedded");
            if (!html.includes('data-layout-view-runs="C:/ws/config.json"')) throw new Error("view runs action missing");
            if (!html.includes('data-layout-open-path="C:/ws/root"')) throw new Error("open workspace action missing");
            if (!html.includes('data-layout-jump-step="5"')) throw new Error("wizard jump action missing");
            if (!html.includes("目录映射：地理数据目录")) throw new Error("GIS directory alias missing");
            if (!html.includes("不要在这里放内部调试文件 &lt;debug&gt;")) throw new Error("notes should be escaped");
            if (html.includes("玛曲<A>") || html.includes("<debug>")) throw new Error("raw unsafe text leaked");

            const empty = layout.workspaceLayoutHtml(null, { emptyText: "尚未选择 <workspace>" }, { escapeHtml });
            if (!empty.includes("尚未选择 &lt;workspace&gt;")) throw new Error("empty layout text should be escaped");

            const host = { innerHTML: "" };
            layout.render(model, "#host", {}, { ...helpers, select: selector => selector === "#host" ? host : null });
            if (!host.innerHTML.includes("geo-preview-card") || !host.innerHTML.includes("地理资料")) {
              throw new Error(`render wrapper did not write layout html: ${host.innerHTML}`);
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


if __name__ == "__main__":
    unittest.main()
