(function () {
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
    pathModalOpenState,
    preferredPathForTarget,
    pathListingQueryState,
    pathListingState,
    selectedPathState,
  };
})();
