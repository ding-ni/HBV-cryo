import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]


class FrontendAppRuntimeTests(unittest.TestCase):
    @unittest.skipIf(shutil.which("node") is None, "node is required for frontend JavaScript tests")
    def test_app_runtime_builds_lifecycle_request_states(self) -> None:
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            const context = { window: {}, console };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/js/appRuntime.js", "utf8"), context);

            const runtime = context.window.HBVStudioAppRuntime;
            if (!runtime?.healthQueryState || !runtime?.quitRequestState || !runtime?.servicePillState || !runtime?.windowUnloadRequestState) {
              throw new Error("app runtime module exports are missing");
            }

            const unload = runtime.windowUnloadRequestState();
            if (!unload.ready ||
                unload.method !== "POST" ||
                unload.requestPath !== "/api/app/window-unload" ||
                unload.body !== "{}" ||
                unload.contentType !== "application/json" ||
                unload.headers["Content-Type"] !== "application/json" ||
                unload.keepalive !== true ||
                Object.keys(unload.payload).length !== 0) {
              throw new Error(`window unload request state mismatch: ${JSON.stringify(unload)}`);
            }

            const unloadWithPayload = runtime.windowUnloadRequestState({ reason: "pagehide" });
            if (unloadWithPayload.body !== '{"reason":"pagehide"}' ||
                unloadWithPayload.payload.reason !== "pagehide") {
              throw new Error(`window unload payload should serialize JSON: ${JSON.stringify(unloadWithPayload)}`);
            }

            const unloadFallback = runtime.windowUnloadRequestState("bad-payload");
            if (unloadFallback.body !== "{}" || Object.keys(unloadFallback.payload).length !== 0) {
              throw new Error(`invalid unload payload should fall back to empty object: ${JSON.stringify(unloadFallback)}`);
            }

            const quit = runtime.quitRequestState();
            if (!quit.ready || quit.requestPath !== "/api/app/quit" || Object.keys(quit.payload).length !== 0) {
              throw new Error(`quit request state mismatch: ${JSON.stringify(quit)}`);
            }

            const health = runtime.healthQueryState();
            if (!health.ready || health.healthPath !== "/api/health") {
              throw new Error(`health query state mismatch: ${JSON.stringify(health)}`);
            }

            const connectedPill = runtime.servicePillState(true, "本地服务已连接");
            if (!connectedPill.connected ||
                connectedPill.text !== "本地服务已连接" ||
                connectedPill.className !== "service-pill connected" ||
                connectedPill.domUpdates[0].selector !== "#service-pill" ||
                connectedPill.domUpdates[0].text !== "本地服务已连接" ||
                connectedPill.domUpdates[0].className !== "service-pill connected") {
              throw new Error(`connected service pill state mismatch: ${JSON.stringify(connectedPill)}`);
            }

            const errorPill = runtime.servicePillState(false, "连接失败");
            if (errorPill.connected ||
                errorPill.text !== "连接失败" ||
                errorPill.className !== "service-pill error" ||
                errorPill.domUpdates[0].className !== "service-pill error") {
              throw new Error(`error service pill state mismatch: ${JSON.stringify(errorPill)}`);
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
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
