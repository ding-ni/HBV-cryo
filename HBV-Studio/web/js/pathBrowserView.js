(function () {
  function normalizeExtensions(value = []) {
    const items = Array.isArray(value)
      ? value
      : String(value || "").split(",");
    return items
      .map(item => String(item || "").trim())
      .filter(Boolean);
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
    normalizeExtensions,
    openPathRequestState,
    pathListingQueryState,
    pathListingState,
  };
})();
