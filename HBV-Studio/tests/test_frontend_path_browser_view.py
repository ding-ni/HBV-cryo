import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendPathBrowserViewTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_path_browser_query_and_listing_state(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/pathBrowserView.js", "utf8"), context);

            const view = context.window.HBVStudioPathBrowserView;
            for (const name of ["configDirectory", "normalizeExtensions", "openPathRequestState", "pathModalOpenState", "preferredPathForTarget", "pathListingQueryState", "pathListingState"]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing path browser export: ${name}`);
            }

            const normalizedArray = view.normalizeExtensions([" .csv ", "", ".xlsx"]);
            if (normalizedArray.join("|") !== ".csv|.xlsx") {
              throw new Error(`array extensions not normalized: ${JSON.stringify(normalizedArray)}`);
            }
            const normalizedString = view.normalizeExtensions(" .tif, .shp ,, ");
            if (normalizedString.join("|") !== ".tif|.shp") {
              throw new Error(`string extensions not normalized: ${JSON.stringify(normalizedString)}`);
            }
            if (view.configDirectory(" C:\\ws\\A\\workspace.json ") !== "C:/ws/A") {
              throw new Error("config directory should normalize backslashes and remove file name");
            }
            if (view.configDirectory("workspace.json") !== "") {
              throw new Error("config directory should be empty without a directory separator");
            }
            const currentPreferred = view.preferredPathForTarget({
              target: "wz-import-dem",
              currentValue: " C:/current/file.tif ",
              runtimeRoot: "D:/runtime",
              configPath: "C:/ws/A/workspace.json",
            });
            if (currentPreferred !== "C:/current/file.tif") {
              throw new Error(`current value should win preferred path: ${currentPreferred}`);
            }
            const rememberedPreferred = view.preferredPathForTarget({
              target: "wz-import-dem",
              lastVisited: { "wz-import-dem": " D:/remembered " },
              runtimeRoot: "D:/runtime",
              configPath: "C:/ws/A/workspace.json",
            });
            if (rememberedPreferred !== "D:/remembered") {
              throw new Error(`remembered path should win preferred path: ${rememberedPreferred}`);
            }
            const runtimeDirPreferred = view.preferredPathForTarget({
              target: "wz-import-prec-dir",
              kind: "file",
              runtimeRoot: "D:/runtime",
              configPath: "C:/ws/A/workspace.json",
            });
            if (runtimeDirPreferred !== "D:/runtime") {
              throw new Error(`runtime root should be preferred for meteo dirs: ${runtimeDirPreferred}`);
            }
            const configFallbackPreferred = view.preferredPathForTarget({
              target: "wz-import-dem",
              kind: "file",
              runtimeRoot: "D:/runtime",
              configPath: "C:/ws/A/workspace.json",
            });
            if (configFallbackPreferred !== "C:/ws/A") {
              throw new Error(`config directory should be preferred before runtime for file targets: ${configFallbackPreferred}`);
            }
            const modalOpen = view.pathModalOpenState({
              target: "wz-import-prec-dir",
              kind: "dir",
              extensions: " .tif, .csv ",
              runtimeRoot: "D:/runtime",
              configPath: "C:/ws/A/workspace.json",
            });
            if (modalOpen.startPath !== "D:/runtime" ||
                !modalOpen.statePatch.open ||
                modalOpen.statePatch.target !== "wz-import-prec-dir" ||
                modalOpen.statePatch.kind !== "dir" ||
                modalOpen.statePatch.extensions.join("|") !== ".tif|.csv") {
              throw new Error(`path modal open state mismatch: ${JSON.stringify(modalOpen)}`);
            }

            const query = view.pathListingQueryState({
              pathValue: " C:/工作区/资料 A&B ",
              kind: "dir",
              extensions: [" .tif ", ".csv"],
            });
            if (query.path !== "C:/工作区/资料 A&B" ||
                query.kind !== "dir" ||
                query.extensions.join("|") !== ".tif|.csv" ||
                query.listingPath !== "/api/fs/list?path=C%3A%2F%E5%B7%A5%E4%BD%9C%E5%8C%BA%2F%E8%B5%84%E6%96%99%20A%26B&extensions=.tif%2C.csv&kind=dir") {
              throw new Error(`path listing query mismatch: ${JSON.stringify(query)}`);
            }

            const emptyQuery = view.pathListingQueryState({ path: " ", kind: " ", extensions: "" });
            if (emptyQuery.path !== "" ||
                emptyQuery.kind !== "file" ||
                emptyQuery.extensions.length !== 0 ||
                emptyQuery.listingPath !== "/api/fs/list?path=&kind=file") {
              throw new Error(`empty path listing query mismatch: ${JSON.stringify(emptyQuery)}`);
            }
            const openRequest = view.openPathRequestState({
              path: " C:/结果/运行 A&B ",
              label: "结果目录",
            });
            if (!openRequest.ready ||
                openRequest.message !== "" ||
                openRequest.path !== "C:/结果/运行 A&B" ||
                openRequest.label !== "结果目录" ||
                openRequest.requestPath !== "/api/fs/open-path" ||
                openRequest.payload.path !== "C:/结果/运行 A&B" ||
                openRequest.toastText !== "已打开结果目录。") {
              throw new Error(`open path request mismatch: ${JSON.stringify(openRequest)}`);
            }
            const missingOpenRequest = view.openPathRequestState({ path: " ", label: "导出文件" });
            if (missingOpenRequest.ready ||
                missingOpenRequest.message !== "没有可打开的导出文件。" ||
                missingOpenRequest.requestPath !== "/api/fs/open-path" ||
                missingOpenRequest.payload.path !== "" ||
                missingOpenRequest.toastText !== "已打开导出文件。") {
              throw new Error(`missing open path request mismatch: ${JSON.stringify(missingOpenRequest)}`);
            }

            const listing = view.pathListingState({
              current_path: "C:/ws",
              parent_path: "C:/",
              roots: ["C:/", "D:/"],
              directories: [{ name: "data", path: "C:/ws/data" }],
              files: [{ name: "a.csv", path: "C:/ws/a.csv" }],
              file_count: 12,
              shown_file_count: 1,
              files_truncated: true,
            }).statePatch;
            if (listing.currentPath !== "C:/ws" ||
                listing.parentPath !== "C:/" ||
                listing.roots.length !== 2 ||
                listing.directories[0].name !== "data" ||
                listing.files[0].name !== "a.csv" ||
                listing.fileCount !== 12 ||
                listing.shownFileCount !== 1 ||
                listing.filesTruncated !== true) {
              throw new Error(`listing state mismatch: ${JSON.stringify(listing)}`);
            }

            const emptyListing = view.pathListingState({}).statePatch;
            if (emptyListing.currentPath !== "" ||
                emptyListing.parentPath !== null ||
                emptyListing.roots.length !== 0 ||
                emptyListing.directories.length !== 0 ||
                emptyListing.files.length !== 0 ||
                emptyListing.fileCount !== 0 ||
                emptyListing.shownFileCount !== 0 ||
                emptyListing.filesTruncated !== false) {
              throw new Error(`empty listing state mismatch: ${JSON.stringify(emptyListing)}`);
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
