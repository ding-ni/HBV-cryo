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
            for (const name of ["configDirectory", "normalizeExtensions", "openPathRequestState", "pathModalCloseState", "pathModalOpenState", "preferredPathForTarget", "pathListingQueryState", "pathListingDomState", "pathListingState", "selectedPathState"]) {
              if (typeof view?.[name] !== "function") throw new Error(`missing path browser export: ${name}`);
            }
            const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              "\"": "&quot;",
              "'": "&#39;",
            }[ch]));

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
            const modalClose = view.pathModalCloseState();
            if (modalClose.statePatch.open !== false || Object.keys(modalClose.statePatch).length !== 1) {
              throw new Error(`path modal close state mismatch: ${JSON.stringify(modalClose)}`);
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

            const dirDom = view.pathListingDomState({
              kind: "dir",
              currentPath: "C:/ws",
              roots: ["C:/", "D:/"],
              directories: [{ name: "data<raw>", path: "C:/ws/data&raw" }],
              files: [{ name: "a.csv" }],
              fileCount: 12,
              shownFileCount: 1,
              filesTruncated: true,
            }, { escapeHtml });
            const dirDomBySelector = Object.fromEntries(dirDom.domUpdates.map(update => [update.selector, update]));
            if (dirDom.title !== "选择文件夹" ||
                !dirDom.useCurrentVisible ||
                dirDom.currentPath !== "C:/ws" ||
                !dirDom.rootsHtml.includes('data-root-path="C:/"') ||
                !dirDom.directoriesHtml.includes("data&lt;raw&gt;") ||
                !dirDom.directoriesHtml.includes("data-select-dir") ||
                !dirDom.filesHtml.includes("仅预览前 1 个文件") ||
                !dirDom.filesHtml.includes("browser-entry-preview") ||
                dirDomBySelector["#path-modal-title"].text !== "选择文件夹" ||
                dirDomBySelector["#path-modal-use-current"].visible !== true ||
                dirDomBySelector["#path-modal-current"].value !== "C:/ws" ||
                dirDomBySelector["#path-modal-files"].html !== dirDom.filesHtml) {
              throw new Error(`directory DOM state mismatch: ${JSON.stringify(dirDom)}`);
            }
            const fileDom = view.pathListingDomState({
              kind: "file",
              currentPath: "C:/ws",
              directories: [],
              files: [{ name: "a<raw>.csv", path: "C:/ws/a&raw.csv" }],
              fileCount: 1,
              shownFileCount: 1,
              filesTruncated: false,
            }, { escapeHtml });
            if (fileDom.title !== "选择文件" ||
                fileDom.useCurrentVisible ||
                !fileDom.directoriesHtml.includes("当前目录下没有子文件夹") ||
                !fileDom.filesHtml.includes('data-file-path="C:/ws/a&amp;raw.csv"') ||
                !fileDom.filesHtml.includes("a&lt;raw&gt;.csv")) {
              throw new Error(`file DOM state mismatch: ${JSON.stringify(fileDom)}`);
            }
            const emptyFileDom = view.pathListingDomState({ kind: "file", files: [] }, { escapeHtml });
            if (!emptyFileDom.filesHtml.includes("当前目录下没有符合条件的文件")) {
              throw new Error(`empty file DOM state mismatch: ${JSON.stringify(emptyFileDom)}`);
            }

            const selectedDir = view.selectedPathState("D:/runtime/forcing", {
              target: "wz-import-prec-dir",
              kind: "dir",
              lastVisited: { other: "C:/old" },
            });
            if (selectedDir.selectedPath !== "D:/runtime/forcing" ||
                selectedDir.rememberedPath !== "D:/runtime/forcing" ||
                selectedDir.statePatch.lastVisited["wz-import-prec-dir"] !== "D:/runtime/forcing" ||
                selectedDir.statePatch.lastVisited.other !== "C:/old") {
              throw new Error(`selected directory state mismatch: ${JSON.stringify(selectedDir)}`);
            }
            const selectedFile = view.selectedPathState("D:\\runtime\\forcing\\prec.tif", {
              target: "wz-import-prec",
              kind: "file",
              lastVisited: {},
            });
            if (selectedFile.selectedPath !== "D:\\runtime\\forcing\\prec.tif" ||
                selectedFile.rememberedPath !== "D:/runtime/forcing" ||
                selectedFile.statePatch.lastVisited["wz-import-prec"] !== "D:/runtime/forcing") {
              throw new Error(`selected file state mismatch: ${JSON.stringify(selectedFile)}`);
            }
            const untargetedSelection = view.selectedPathState("D:/runtime/forcing/prec.tif", {
              kind: "file",
              lastVisited: { other: "C:/old" },
            });
            if (untargetedSelection.statePatch.lastVisited.other !== "C:/old" ||
                Object.keys(untargetedSelection.statePatch.lastVisited).length !== 1) {
              throw new Error(`untargeted selection should preserve existing last visited map: ${JSON.stringify(untargetedSelection)}`);
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
