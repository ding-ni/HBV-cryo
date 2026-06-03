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
            for (const name of ["normalizeExtensions", "pathListingQueryState", "pathListingState"]) {
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
