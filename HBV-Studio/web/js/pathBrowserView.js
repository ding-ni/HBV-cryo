(function () {
  function defaultEscapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function normalizeExtensions(value = []) {
    const items = Array.isArray(value)
      ? value
      : String(value || "").split(",");
    return items
      .map(item => String(item || "").trim())
      .filter(Boolean);
  }

  function configDirectory(configPath = "") {
    const raw = String(configPath || "").trim().replace(/\\/g, "/");
    if (!raw.includes("/")) return "";
    return raw.slice(0, raw.lastIndexOf("/"));
  }

  function preferredPathForTarget(model = {}) {
    const target = String(model.target || "").trim();
    const kind = String(model.kind || "file").trim() || "file";
    const currentValue = String(model.currentValue || "").trim();
    if (currentValue) return currentValue;
    const lastVisited = model.lastVisited || {};
    const remembered = target ? String(lastVisited[target] || "").trim() : "";
    if (remembered) return remembered;
    const runtimeRoot = String(model.runtimeRoot || "").trim();
    if (kind === "dir" && runtimeRoot) return runtimeRoot;
    if (/^wz-import-(prec|temp|evap)-dir$/.test(target) && runtimeRoot) return runtimeRoot;
    if (/^wz-custom-/.test(target) && runtimeRoot) return runtimeRoot;
    if (target === "wz-hourly-prec-dir" && runtimeRoot) return runtimeRoot;
    return configDirectory(model.configPath) || runtimeRoot || "";
  }

  function pathModalOpenState(model = {}) {
    const target = String(model.target || "").trim();
    const kind = String(model.kind || "file").trim() || "file";
    const extensions = normalizeExtensions(model.extensions);
    return {
      startPath: preferredPathForTarget({ ...model, target, kind }),
      statePatch: {
        open: true,
        target,
        kind,
        extensions,
      },
    };
  }

  function pathModalCloseState() {
    return {
      statePatch: { open: false },
    };
  }

  function pathListingQueryState(model = {}) {
    const path = String(model.path || model.pathValue || "").trim();
    const kind = String(model.kind || "file").trim() || "file";
    const extensions = normalizeExtensions(model.extensions);
    const extParam = extensions.length
      ? `&extensions=${encodeURIComponent(extensions.join(","))}`
      : "";
    return {
      path,
      kind,
      extensions,
      listingPath: `/api/fs/list?path=${encodeURIComponent(path)}${extParam}&kind=${encodeURIComponent(kind)}`,
    };
  }

  function pathListingState(data = {}) {
    const files = Array.isArray(data?.files) ? data.files : [];
    return {
      statePatch: {
        currentPath: data?.current_path || "",
        parentPath: data?.parent_path || null,
        roots: Array.isArray(data?.roots) ? data.roots : [],
        directories: Array.isArray(data?.directories) ? data.directories : [],
        files,
        fileCount: Number(data?.file_count || 0),
        shownFileCount: Number(data?.shown_file_count || files.length || 0),
        filesTruncated: Boolean(data?.files_truncated),
      },
    };
  }

  function pathListingDomState(model = {}, helpers = {}) {
    const escapeHtml = typeof helpers.escapeHtml === "function" ? helpers.escapeHtml : defaultEscapeHtml;
    const kind = String(model.kind || "file").trim() || "file";
    const isDir = kind === "dir";
    const roots = Array.isArray(model.roots) ? model.roots : [];
    const directories = Array.isArray(model.directories) ? model.directories : [];
    const files = Array.isArray(model.files) ? model.files : [];
    const currentPath = String(model.currentPath || "");
    const fileCount = Number(model.fileCount || 0);
    const shownFileCount = Number(model.shownFileCount || files.length || 0);
    const filesTruncated = Boolean(model.filesTruncated);

    const title = isDir ? "选择文件夹" : "选择文件";
    const rootsHtml = roots.map(r =>
      `<button class="browser-entry" data-root-path="${escapeHtml(r)}">${escapeHtml(r)}</button>`
    ).join("");
    const directoriesHtml = directories.map(d =>
      `<div class="browser-entry-row">
      <button class="browser-entry browser-entry-nav" data-dir-path="${escapeHtml(d.path)}">${escapeHtml(d.name)}</button>
      ${isDir ? `<button class="browser-entry-select" data-select-dir="${escapeHtml(d.path)}" title="选取此文件夹">✓</button>` : ""}
    </div>`
    ).join("") || '<div class="hint-box">当前目录下没有子文件夹。</div>';

    let filesHtml = "";
    if (isDir) {
      const previewFiles = files.map(f =>
        `<div class="browser-entry browser-entry-preview">${escapeHtml(f.name)}</div>`
      ).join("");
      const previewHint = files.length
        ? `<div class="hint-box ${filesTruncated ? "status-warn" : ""}">当前为文件夹选择模式，仅预览前 ${shownFileCount} 个文件${fileCount ? `（共识别 ${fileCount} 个）` : ""}，不会展开完整文件列表，因此大栅格目录仍会更快。</div>`
        : '<div class="hint-box">当前为文件夹选择模式。这里仅做内容预览，不会展开完整文件列表，因此大栅格目录会更快。</div>';
      filesHtml = `${previewHint}${previewFiles}`;
    } else {
      const fileButtons = files.map(f =>
        `<button class="browser-entry" data-file-path="${escapeHtml(f.path)}">${escapeHtml(f.name)}</button>`
      ).join("");
      const truncateHint = filesTruncated
        ? `<div class="hint-box status-warn">当前目录文件较多，仅显示前 ${shownFileCount} 个，共 ${fileCount} 个。</div>`
        : "";
      filesHtml = `${truncateHint}${fileButtons}` || '<div class="hint-box">当前目录下没有符合条件的文件。</div>';
    }

    return {
      title,
      currentPath,
      rootsHtml,
      directoriesHtml,
      filesHtml,
      useCurrentVisible: isDir,
      domUpdates: [
        { selector: "#path-modal-title", text: title },
        { selector: "#path-modal-use-current", visible: isDir },
        { selector: "#path-modal-current", value: currentPath },
        { selector: "#path-modal-roots", html: rootsHtml },
        { selector: "#path-modal-directories", html: directoriesHtml },
        { selector: "#path-modal-files", html: filesHtml },
      ],
    };
  }

  function selectedPathState(pathValue = "", model = {}) {
    const selectedPath = String(pathValue || "");
    const target = String(model.target || "").trim();
    const kind = String(model.kind || "file").trim() || "file";
    const lastVisited = model.lastVisited && typeof model.lastVisited === "object"
      ? model.lastVisited
      : {};
    const rememberedPath = kind === "dir"
      ? selectedPath
      : selectedPath.replace(/\\/g, "/").replace(/\/[^/]+$/, "");
    const nextLastVisited = target
      ? { ...lastVisited, [target]: rememberedPath }
      : { ...lastVisited };
    return {
      selectedPath,
      rememberedPath,
      statePatch: { lastVisited: nextLastVisited },
    };
  }

  function openPathRequestState(model = {}) {
    const path = String(model.path || model.pathValue || "").trim();
    const label = String(model.label || "目录").trim() || "目录";
    return {
      ready: Boolean(path),
      message: path ? "" : `没有可打开的${label}。`,
      path,
      label,
      requestPath: "/api/fs/open-path",
      payload: { path },
      toastText: `已打开${label}。`,
    };
  }

  window.HBVStudioPathBrowserView = {
    configDirectory,
    normalizeExtensions,
    openPathRequestState,
    pathModalCloseState,
    pathModalOpenState,
    preferredPathForTarget,
    pathListingQueryState,
    pathListingDomState,
    pathListingState,
    selectedPathState,
  };
})();
