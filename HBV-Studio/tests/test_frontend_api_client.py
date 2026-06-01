import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendApiClientTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_api_client_response_handling_and_request_guard(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = {
              window: {},
              console,
              fetch: async () => ({
                ok: true,
                status: 200,
                text: async () => "{\"ok\":true,\"data\":{\"value\":7}}",
              }),
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/apiClient.js", "utf8"), context);

            (async () => {
              const client = context.window.HBVStudioApiClient;
              if (!client) throw new Error("api client was not exported");

              const payload = await client.apiGet("/api/health");
              if (payload.data.value !== 7) throw new Error("apiGet did not parse payload");

              context.fetch = async () => ({
                ok: true,
                status: 200,
                text: async () => "not-json",
              });
              let parseFailed = false;
              try {
                await client.apiGet("/api/bad-json");
              } catch (err) {
                parseFailed = String(err.message || "").includes("无法识别");
              }
              if (!parseFailed) throw new Error("invalid JSON response was not rejected");

              const guard = client.createLatestRequestGuard();
              const first = guard.next();
              if (!guard.isActive(first)) throw new Error("first token should be active");
              const second = guard.next();
              if (guard.isActive(first)) throw new Error("older token should be inactive");
              if (!guard.isActive(second)) throw new Error("latest token should be active");
              guard.cancel();
              if (guard.isActive(second)) throw new Error("cancel should invalidate latest token");
            })().catch(err => {
              console.error(err && err.stack ? err.stack : err);
              process.exit(1);
            });
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
