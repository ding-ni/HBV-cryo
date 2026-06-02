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

  function defaultSlashPath(value) {
    return String(value || "").replace(/\\/g, "/");
  }

  function defaultLayoutStatusClass(item) {
    if (!item?.exists) return "status-fail";
    if (item.kind === "file") return "status-ok";
    return Number(item.count || 0) > 0 ? "status-ok" : "status-warn";
  }

  function aliasForPath(path, helpers = {}) {
    const slashPath = helpers.slashPath || defaultSlashPath;
    const text = slashPath(path);
    if (!text) return "";
    const rules = [
      { matches: ["/数据/地理数据", "/data/gis"], label: "地理数据目录" },
      { matches: ["/数据/观测数据", "/data/observed"], label: "观测与对比资料目录" },
      { matches: ["/数据/原始气象/降水", "/data/raw/precipitation"], label: "原始降水资料目录" },
      { matches: ["/数据/原始气象/气温", "/data/raw/temperature"], label: "原始气温资料目录" },
      { matches: ["/数据/原始气象/蒸散发", "/data/raw/evaporation"], label: "原始蒸散发资料目录" },
      { matches: ["/数据/原始气象", "/data/raw"], label: "原始气象资料目录" },
      { matches: ["/数据/模型输入/降水_本地导入_站点订正", "/data/aligned_masked/prec_custom_corrected"], label: "本地导入降水运行目录（站点订正后）" },
      { matches: ["/数据/模型输入/降水_ERA5_站点订正", "/data/aligned_masked/precipitation_corrected"], label: "ERA5 运行降水目录（站点订正后）" },
      { matches: ["/数据/模型输入/降水_CMFD_站点订正", "/data/aligned_masked/prec_cmfd_corrected"], label: "CMFD 运行降水目录（站点订正后）" },
      { matches: ["/数据/模型输入/降水_MSWEP_站点订正", "/data/aligned_masked/prec_corrected"], label: "MSWEP 运行降水目录（站点订正后）" },
      { matches: ["/数据/模型输入/降水_本地导入", "/data/aligned_masked/prec_custom"], label: "本地导入降水基线目录" },
      { matches: ["/数据/模型输入/降水_CMFD", "/data/aligned_masked/prec_cmfd"], label: "CMFD 基线降水目录" },
      { matches: ["/数据/模型输入/降水_MSWEP", "/data/aligned_masked/prec"], label: "MSWEP 基线降水目录" },
      { matches: ["/数据/模型输入/降水", "/data/aligned_masked/precipitation"], label: "工程降水目录" },
      { matches: ["/数据/模型输入/冰川融水", "/data/aligned_masked/glacier_melt"], label: "冰川融水参考目录" },
      { matches: ["/数据/模型输入", "/data/aligned_masked"], label: "标准气象驱动目录" },
      { matches: ["/结果/日尺度/运行记录", "/results/daily/runs"], label: "日尺度结果目录" },
      { matches: ["/结果/小时尺度/运行记录", "/results/hourly/runs"], label: "小时尺度结果目录" },
      { matches: ["/结果/日尺度/日志", "/results/daily/logs"], label: "日尺度日志目录" },
      { matches: ["/结果/小时尺度/日志", "/results/hourly/logs"], label: "小时尺度日志目录" },
      { matches: ["/结果/日尺度/缓存", "/results/daily/cache"], label: "日尺度加速缓存目录" },
      { matches: ["/结果/小时尺度/缓存", "/results/hourly/cache"], label: "小时尺度加速缓存目录" },
      { matches: ["/结果/日尺度", "/results/daily"], label: "日尺度结果主目录" },
      { matches: ["/结果/小时尺度", "/results/hourly"], label: "小时尺度结果主目录" },
      { matches: ["/结果", "/results"], label: "结果主目录" },
    ];
    const hit = rules.find(item => item.matches.some(match => text.includes(match)));
    return hit?.label || "";
  }

  function workspaceLayoutHtml(layout, options = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const slashPath = helpers.slashPath || defaultSlashPath;
    const layoutStatusClass = helpers.layoutStatusClass || defaultLayoutStatusClass;
    const renderGeoOverview = helpers.renderGeoOverview || (() => "");
    const {
      emptyText = "尚未选择工作区。",
      title = "工作区目录结构",
      subtitle = "",
    } = options;
    if (!layout) {
      return `<div class="hint-box">${escapeHtml(emptyText)}</div>`;
    }
    const layoutTitle = layout.flow_name ? `${layout.flow_name} · ${title}` : title;
    const canOperate = layout.allow_operations !== false;
    const canJump = layout.allow_jump !== false;
    const headerActions = canOperate ? `
      <div class="workspace-layout-actions">
        ${layout.config_path ? `<button class="ghost-button" data-layout-view-runs="${escapeHtml(layout.config_path)}">查看该工程结果</button>` : ""}
        ${layout.workspace_root ? `<button class="ghost-button" data-layout-open-path="${escapeHtml(layout.workspace_root)}" data-layout-label="工程目录">打开工程目录</button>` : ""}
        ${layout.results_root ? `<button class="ghost-button" data-layout-open-path="${escapeHtml(layout.results_root)}" data-layout-label="结果目录">打开结果目录</button>` : ""}
        ${layout.config_path ? `<button class="ghost-button" data-layout-copy-path="${escapeHtml(layout.config_path)}" data-layout-label="配置文件路径">复制配置路径</button>` : ""}
      </div>
    ` : "";
    const groupsHtml = (layout.groups || []).map(group => `
      <section class="workspace-layout-group">
        <h4>${escapeHtml(group.title || "")}</h4>
        ${(group.items || []).map(item => {
          const itemPath = item.path || item.display_path || "";
          const alias = aliasForPath(itemPath, { slashPath });
          return `
            <article class="workspace-layout-item">
              <div class="workspace-layout-item-head">
                <strong>${escapeHtml(item.label || "")}</strong>
                <span class="status-badge ${layoutStatusClass(item)}">${escapeHtml(item.status || "\u2014")}</span>
              </div>
              <div class="workspace-layout-path">${escapeHtml(item.display_path || item.path || "\u2014")}</div>
              ${alias && alias !== item.label ? `<div class="workspace-layout-stage">目录映射：${escapeHtml(alias)}</div>` : ""}
              <div class="workspace-layout-purpose">${escapeHtml(item.purpose || "")}</div>
              <div class="workspace-layout-stage">${escapeHtml(item.stage_hint || "")}</div>
              <div class="workspace-layout-actions">
                ${item.path && canOperate ? `<button class="ghost-button" data-layout-copy-path="${escapeHtml(item.path)}" data-layout-label="${escapeHtml(item.label || "路径")}">复制路径</button>` : ""}
                ${item.path && item.exists && canOperate ? `<button class="ghost-button" data-layout-open-path="${escapeHtml(item.path)}" data-layout-label="${escapeHtml(item.label || "目录")}">打开</button>` : ""}
                ${item.target_step && layout.config_path && canJump ? `<button class="ghost-button" data-layout-jump-step="${escapeHtml(String(item.target_step))}" data-layout-config="${escapeHtml(layout.config_path)}">转到第 ${escapeHtml(String(item.target_step))} 步</button>` : ""}
              </div>
            </article>
          `;
        }).join("")}
      </section>
    `).join("");
    const notes = (layout.notes || []).map(note => `<li>${escapeHtml(note)}</li>`).join("");
    return `
      <div class="workspace-layout-head">
        <div>
          <div class="workspace-layout-title">${escapeHtml(layoutTitle)}</div>
          <div class="workspace-layout-subtitle">${escapeHtml(subtitle || layout.profile_label || "")}</div>
        </div>
        <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px">
          <span class="status-badge">${escapeHtml(layout.profile_label || "\u2014")}</span>
          ${headerActions}
        </div>
      </div>
      <div class="workspace-layout-summary">
        <div class="hint-box">${escapeHtml(layout.headline || "")}</div>
        <div class="workspace-layout-focus">
          <strong>当前建议先看：</strong>${escapeHtml(layout.next_focus?.label || "\u2014")}<br>
          ${escapeHtml(layout.next_focus?.reason || "")}
        </div>
      </div>
      ${renderGeoOverview(layout.geo_overview || null)}
      <div class="workspace-layout-grid">${groupsHtml}</div>
      ${notes ? `<ul class="workspace-layout-notes">${notes}</ul>` : ""}
    `;
  }

  function render(layout, hostSelector, options = {}, helpers = {}) {
    const select = helpers.select || (sel => document.querySelector(sel));
    const host = select(hostSelector);
    if (!host) return;
    host.innerHTML = workspaceLayoutHtml(layout, options, helpers);
  }

  window.HBVStudioWorkspaceLayout = {
    aliasForPath,
    workspaceLayoutHtml,
    render,
  };
})();
