/* ============================================================
   HBV-Studio  –  app.js  (complete rewrite)
   ============================================================ */

// --------------- constants ---------------

const objectLabels = {
  regression_validation: "回归验证样例",
  interbasin_with_boundary: "区间流域 + 上游边界入流",
  full_upstream_basin: "完整上游流域",
};

const viewMeta = {
  dashboard: { title: "项目管理", subtitle: "管理工作区与内置模板" },
  wizard:    { title: "建模向导", subtitle: "按步骤配置流域模型" },
  calibration: { title: "率定运行", subtitle: "配置并启动率定任务" },
  forecast: { title: "连续状态预报", subtitle: "复用率定参数与保存状态，接入未来气象驱动" },
  results:   { title: "结果分析", subtitle: "查看率定结果与诊断图表" },
};

const GIS_STEP_IDS = new Set(["clip_dem", "flow_acc", "masked_flow", "elevation_zone", "glacier_mask", "glacier_elev"]);
const CHECK_STEP_IDS = new Set(["check_inputs"]);

const colors = {
  qSim: "#1d6d74",
  qObs: "#b36a28",
  qRain: "#317f95",
  qSnow: "#b7ced8",
  qIce: "#2d7c52",
  residual: "#b54538",
};

const wizardStepLabels = {
  1: "基本设置",
  2: "流域与观测",
  3: "边界条件",
  4: "气象来源",
  5: "地理数据",
  6: "气象导入/处理",
  7: "输入检查",
};

const CALIBRATION_PARAM_COUNT = 18;
const PARAM_BOUNDS_PROFILE_LABELS = {
  qtp_alpine_default: "青藏高原高寒区默认",
  generic_wide: "通用宽范围",
  hourly_step: "小时尺度稳定范围",
};

const PARAM_LABELS = {
  TT: "温度阈值 (°C)",
  FC: "田间持水量 (mm)",
  BETA: "土壤形状系数",
  LP: "蒸散系数",
  RFCF: "降雨校正",
  SFCF: "降雪校正",
  CFR: "再冻结系数",
  CWH: "持水能力",
  CFMAX_low: "低海拔融雪因子",
  CFMAX_high: "高海拔融雪因子",
  K: "上层出流系数",
  K1: "中层出流系数",
  K2: "深层出流系数",
  UZL: "上层阈值 (mm)",
  PERC: "渗透速率 (mm/d)",
  ICE_FACTOR: "冰川因子",
  K_MUSK: "马斯京根 K",
  X_MUSK: "马斯京根 X",
};

const MANUAL_GROUP_PARAMS = {
  all: [],
  snow: ["TT", "RFCF", "SFCF", "CFR", "CWH", "CFMAX_low", "CFMAX_high"],
  soil: ["FC", "BETA", "LP"],
  response: ["K", "K1", "K2", "UZL", "PERC"],
  routing: ["K_MUSK", "X_MUSK"],
  glacier: ["ICE_FACTOR"],
};

const MANUAL_GROUP_META = {
  all: {
    title: "全部参数",
    guide: "推荐三阶段：先稳住土壤、产流和退水参数，避免冰川替代地下水；再识别雪过程；最后只释放冰川参数解释晚融季额外径流。",
  },
  snow: {
    title: "雪过程",
    guide: "第二阶段再看雨雪分相、春季起涨和融雪季体积。优先盯 TT、SFCF、CFR、CWH、CFMAX_low、CFMAX_high。",
  },
  soil: {
    title: "土壤过程",
    guide: "第一阶段先稳住土壤蓄水和季节湿润记忆。优先看 FC、BETA、LP 是否让全年水量和枯水季合理。",
  },
  response: {
    title: "产汇流",
    guide: "第一阶段重点约束快慢流和退水骨架。优先看 K、K1、K2、PERC、UZL，防止冰川分量接管退水。",
  },
  routing: {
    title: "河道路由",
    guide: "汇流参数更像波形修饰器，建议放在 snow/soil/response 基本稳定之后再调。",
  },
  glacier: {
    title: "冰川过程",
    guide: "第三阶段才释放 ICE_FACTOR 和冰川温度修正相关项，只允许其解释晚融季、暖季、雪耗尽后的额外径流。",
  },
};

const RUN_TYPE_LABELS = {
  manual_starter: "手调起点",
  manual_result: "手调结果",
  forecast_restart: "连续状态预报",
  calibration: "正式率定",
  legacy: "历史结果",
};

const RUN_EXPORT_FIELDS = [
  { key: "q_sim", label: "模拟总流量", checked: true },
  { key: "q_obs", label: "观测流量", checked: true },
  { key: "q_rain", label: "降雨产流", checked: true },
  { key: "q_snow", label: "融雪流量", checked: true },
  { key: "q_ice", label: "裸冰融化流量", checked: true },
  { key: "q_boundary_inflow", label: "边界入流", checked: false },
];

const CURRENT_OBJECTIVE_FAMILY = "daily_unified_professional_v1";
const FLOOD_EVENT_OBJECTIVE_FAMILY = "flood_event_calibration_v1";
const LEGACY_OBJECTIVE_FAMILIES = new Set(["weighted_daily_universal", "weighted_multi_criteria"]);

// --------------- state ---------------

const state = {
  currentView: "dashboard",
  wizardStep: 1,
  wizardWorkspacePath: "",
  currentWorkspace: null,
  currentWorkspaceWorkflow: null,
  currentWorkspaceAdvice: null,
  currentWorkspaceLayout: null,
  currentWorkspaceLayoutPath: "",
  dashboardWorkspaceLayout: null,
  dashboardLayoutPath: "",
  runWorkspaceFilterPath: "",
  runProfileFilter: "",
  runTypeFilter: "",
  runEditabilityFilter: "all",
  taskWorkspaceFilterMode: "current",
  taskStatusFilter: "active",
  taskTypeFilter: "all",
  manualParamGroup: "all",
  templates: [],
  workspaces: [],
  runs: [],
  tasks: [],
  taskDebugOpen: {},
  logViewState: {},
  currentRun: null,
  selectedRunPath: "",
  activeRunRequestId: 0,
  compareSeries: null,
  compareMetrics: null,
  compareLabel: "",
  comparePresetId: "",
  compareAdjusted: false,
  runManualPresets: [],
  runManualPresetConfigPath: "",
  activeRunManualPresetRequestId: 0,
  taskManualPresets: [],
  taskManualPresetConfigPath: "",
  activeTaskManualPresetRequestId: 0,
  forecastSourceRunPath: "",
  forecastResultRunPath: "",
  forecastResultData: null,
  forecastResultLoadingPath: "",
  activeForecastResultRequestId: 0,
  lastForecastExportPath: "",
  activeCompareRequestId: 0,
  prepSteps: [],
  prepStatus: {},
  cdsApiStatus: null,
  cdsApiNeedSignature: "",
  activeCdsApiRequestId: 0,
  obsInfo: null,
  lastInputCheck: {
    configPath: "",
    precipSource: "",
    stage: "calibration",
    checkedAt: 0,
    result: null,
    html: "",
  },
  activeMeteoImportTaskId: "",
  meteoImportPollTimer: null,
  activePrepTaskId: "",
  prepTaskPollTimer: null,
  activeForwardSimTaskId: "",
  activeForwardSimSourceRunPath: "",
  forwardSimPollTimer: null,
  lastRunExportPath: "",
  pathModal: {
    open: false,
    target: "",
    kind: "file",
    extensions: [],
    currentPath: "",
    parentPath: "",
    roots: [],
    directories: [],
    files: [],
    fileCount: 0,
    shownFileCount: 0,
    filesTruncated: false,
    lastVisited: {},
  },
};

// --------------- utilities ---------------

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }

function escapeHtml(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function showToast(message, isError = false) {
  const t = $("#toast");
  t.textContent = message;
  t.style.borderColor = isError ? "rgba(181,69,56,0.32)" : "rgba(20,79,84,0.28)";
  t.classList.add("visible");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.remove("visible"), 2800);
}

function formatNumber(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "\u2014";
  return Number(v).toFixed(digits);
}

function finiteNumber(v) {
  const numeric = Number(v);
  return Number.isFinite(numeric) ? numeric : null;
}

function compareMetricSummary(label, currentValue, baselineValue, digits = 4) {
  const current = finiteNumber(currentValue);
  const baseline = finiteNumber(baselineValue);
  const currentText = formatNumber(current, digits);
  if (current === null && baseline === null) return `${label}：${currentText}（当前结果和对比参数集都没有该指标）`;
  if (current === null) return `${label}：${currentText}（该参数集未产生该指标）`;
  if (baseline === null) return `${label}：${currentText}（当前结果无可比指标）`;
  const delta = current - baseline;
  return `${label}：${currentText}（较当前 ${delta >= 0 ? "+" : ""}${formatNumber(delta, digits)}）`;
}

function formatDateTime(v) {
  if (!v) return "\u2014";
  const d = new Date(Number(v) * 1000 || v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString("zh-CN", { hour12: false });
}

function shortPath(v) {
  if (!v) return "\u2014";
  return String(v).replace(/\\/g, "/").replace(/^.*\/([^/]+)$/, "$1");
}

function slashPath(v) {
  return String(v || "").replace(/\\/g, "/");
}

function normalizePath(v) {
  return slashPath(v).trim().toLowerCase();
}

function samePath(a, b) {
  const left = normalizePath(a);
  const right = normalizePath(b);
  return Boolean(left && right && left === right);
}

function workspaceEntryByPath(path) {
  return state.workspaces.find(item => samePath(item.path, path)) || null;
}

function workspaceLabelByPath(path) {
  const item = workspaceEntryByPath(path);
  return item?.flow_name || item?.name || shortPath(path) || "未命名工作区";
}

function runTypeValue(run) {
  const direct = String(run?.run_type || "").trim().toLowerCase();
  if (direct) return direct;
  return run?.studio_compatible ? "calibration" : "legacy";
}

function runTypeLabel(value, fallback = "") {
  const key = String(value || "").trim().toLowerCase();
  return RUN_TYPE_LABELS[key] || fallback || "结果";
}

function runDisplayName(run) {
  return String(run?.display_name || run?.name || shortPath(run?.path) || "未命名结果")
    .replace(/状态接续预报/g, "连续状态预报")
    .trim();
}

function runDisplaySubtitle(run) {
  return String(run?.display_subtitle || "").trim();
}

function runWorkspaceName(run) {
  return String(run?.workspace_name || "").trim() || workspaceLabelByPath(run?.workspace_config);
}

function runTimeText(run) {
  return String(run?.run_time_label || run?.run_time || "").trim() || formatDateTime(run?.updated_at);
}

function compactTimeText(value, stepHours = 24) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (stepHours <= 1.5) return text.replace("T", " ");
  return text.slice(0, 10);
}

function timeRangeText(start, end, stepHours = 24) {
  const left = compactTimeText(start, stepHours);
  const right = compactTimeText(end, stepHours);
  if (left && right) return `${left} ~ ${right}`;
  return left || right || "\u2014";
}

function runEditabilityLabel(run) {
  return run?.studio_compatible ? "可继续手调" : "仅查看";
}

function runMetricsText(run) {
  const cfg = run?.time_config || {};
  const stepHours = Number(cfg.time_step_hours || run?.time_step_hours || 24);
  const start = String(cfg.warmup_start || cfg.calib_start || "").trim();
  const end = String(cfg.valid_end || cfg.calib_end || "").trim();
  if (!start && !end) return "";
  return `全时段${cfg.warmup_start ? "（含预热）" : ""}：${timeRangeText(start, end, stepHours)}`;
}

function runTypeBadge(run) {
  const label = runTypeLabel(runTypeValue(run), String(run?.run_type_label || "").trim());
  return `<span class="status-badge status-type">${escapeHtml(label)}</span>`;
}

function objectiveFamilyKey(metaOrRun = {}) {
  return String(
    metaOrRun?.recorded_objective_family
    || metaOrRun?.objective_family
    || metaOrRun?.effective_objective_mode
    || metaOrRun?.optimization?.effective_objective_mode
    || metaOrRun?.objective_profile?.type
    || metaOrRun?.objective?.type
    || ""
  ).trim().toLowerCase();
}

function objectiveVersionStatus(metaOrRun = {}) {
  const family = objectiveFamilyKey(metaOrRun);
  if (family === CURRENT_OBJECTIVE_FAMILY) {
    return {
      state: "current",
      label: "当前口径",
      value: "当前综合评价口径",
      detail: "该结果使用当前统一日尺度水文评价口径，可用于径流拟合与冰雪融水过程复核。",
      badgeClass: "status-ok",
    };
  }
  if (family === FLOOD_EVENT_OBJECTIVE_FAMILY) {
    return {
      state: "current",
      label: "事件口径",
      value: "事件洪水率定结果",
      detail: "该结果按洪水事件窗口评价；事件资料模式下每场事件独立预热。",
      badgeClass: "status-ok",
    };
  }
  if (LEGACY_OBJECTIVE_FAMILIES.has(family)) {
    return {
      state: "legacy",
      label: "历史口径",
      value: "历史计算结果",
      detail: "该结果来自旧版计算口径，适合兼容查看；冰雪融水解释应以当前口径重新计算结果为准。",
      badgeClass: "status-warn",
    };
  }
  return {
    state: "unknown",
    label: "口径未明",
    value: "评价口径未记录",
    detail: "结果未记录评价口径，冰雪融水解释仅作兼容查看。",
    badgeClass: "status-warn",
  };
}

function objectiveVersionBadge(run) {
  const status = objectiveVersionStatus(run);
  return `<span class="status-badge ${status.badgeClass}">${escapeHtml(status.label)}</span>`;
}

function visibleRuns() {
  return state.runs.filter(run => {
    if (state.runWorkspaceFilterPath && !samePath(run.workspace_config, state.runWorkspaceFilterPath)) {
      return false;
    }
    if (state.runProfileFilter) {
      const profile = String(run.calibration_profile || (run.time_step_hours === 1 ? "hourly" : "daily") || "").trim().toLowerCase();
      if (profile !== state.runProfileFilter) return false;
    }
    if (state.runTypeFilter) {
      if (runTypeValue(run) !== state.runTypeFilter) return false;
    }
    if (state.runEditabilityFilter === "editable" && !run.studio_compatible) {
      return false;
    }
    if (state.runEditabilityFilter === "readonly" && run.studio_compatible) {
      return false;
    }
    return true;
  });
}

function runsForWorkspace(path) {
  return state.runs.filter(run => samePath(run.workspace_config, path));
}

function currentSelectedRunPath() {
  return String(state.selectedRunPath || state.currentRun?.run?.path || state.currentRun?.path || "").trim();
}

function nextRunRequestId() {
  state.activeRunRequestId = Number(state.activeRunRequestId || 0) + 1;
  return state.activeRunRequestId;
}

function nextRunManualPresetRequestId() {
  state.activeRunManualPresetRequestId = Number(state.activeRunManualPresetRequestId || 0) + 1;
  return state.activeRunManualPresetRequestId;
}

function nextTaskManualPresetRequestId() {
  state.activeTaskManualPresetRequestId = Number(state.activeTaskManualPresetRequestId || 0) + 1;
  return state.activeTaskManualPresetRequestId;
}

function nextForecastResultRequestId() {
  state.activeForecastResultRequestId = Number(state.activeForecastResultRequestId || 0) + 1;
  return state.activeForecastResultRequestId;
}

function nextCompareRequestId() {
  state.activeCompareRequestId = Number(state.activeCompareRequestId || 0) + 1;
  return state.activeCompareRequestId;
}

function normalizeCalibrationProfile(value, fallback = "") {
  const profile = String(value || "").trim().toLowerCase();
  return profile || fallback;
}

function workspaceHasEditableRun(path) {
  return runsForWorkspace(path).some(run => run.studio_compatible);
}

function visibleTasks() {
  return state.tasks.filter(task => {
    if (state.taskWorkspaceFilterMode === "current" && state.wizardWorkspacePath) {
      if (!samePath(task.config_path, state.wizardWorkspacePath)) {
        return false;
      }
    }
    if (state.taskStatusFilter === "active" && task.status !== "running") {
      return false;
    }
    if (state.taskStatusFilter === "unfinished" && task.status === "completed") {
      return false;
    }
    if (state.taskStatusFilter === "failed" && task.status !== "failed") {
      return false;
    }
    if (state.taskTypeFilter !== "all") {
      if (state.taskTypeFilter === "calibration" && task.task_type !== "calibration") {
        return false;
      }
      if (state.taskTypeFilter === "prep" && !["data_prep", "bootstrap", "meteo_import"].includes(task.task_type)) {
        return false;
      }
      if (state.taskTypeFilter === "simulate" && !["forward_sim", "manual_start", "forecast_restart"].includes(task.task_type)) {
        return false;
      }
      if (state.taskTypeFilter === "support" && !["self_check", "sync"].includes(task.task_type)) {
        return false;
      }
    }
    return true;
  });
}

function latestEditableRunPath(runs = visibleRuns()) {
  const editable = runs.find(run => run.studio_compatible);
  return editable?.path || runs[0]?.path || "";
}

function renderTaskFilterToolbar() {
  const host = $("#task-filter-toolbar");
  const hint = $("#task-filter-hint");
  if (!host || !hint) return;
  const workspaceOptions = [
    { value: "current", label: state.wizardWorkspacePath ? `当前工作区：${workspaceLabelByPath(state.wizardWorkspacePath)}` : "当前工作区（未选择）", disabled: !state.wizardWorkspacePath },
    { value: "all", label: "全部工作区任务", disabled: false },
  ];
  const statusOptions = [
    { value: "active", label: "只看运行中" },
    { value: "unfinished", label: "看未完成/失败" },
    { value: "failed", label: "只看失败" },
    { value: "all", label: "全部状态" },
  ];
  const typeOptions = [
    { value: "all", label: "全部类型" },
    { value: "calibration", label: "率定" },
    { value: "prep", label: "数据准备" },
    { value: "simulate", label: "手调/预报" },
    { value: "support", label: "自检/辅助" },
  ];
  host.innerHTML = `
    <div class="results-filter-group">
      <span class="results-filter-label">范围</span>
      ${workspaceOptions.map(item => `
        <button class="phase-chip ${item.value === state.taskWorkspaceFilterMode ? "active" : ""}" data-task-filter-workspace="${escapeHtml(item.value)}" ${item.disabled ? "disabled" : ""}>
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
    <div class="results-filter-group">
      <span class="results-filter-label">状态</span>
      ${statusOptions.map(item => `
        <button class="phase-chip ${item.value === state.taskStatusFilter ? "active" : ""}" data-task-filter-status="${escapeHtml(item.value)}">
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
    <div class="results-filter-group">
      <span class="results-filter-label">类型</span>
      ${typeOptions.map(item => `
        <button class="phase-chip ${item.value === state.taskTypeFilter ? "active" : ""}" data-task-filter-type="${escapeHtml(item.value)}">
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
  `;
  const shown = visibleTasks();
  const running = shown.filter(task => task.status === "running").length;
  const failed = shown.filter(task => task.status === "failed").length;
  const total = state.tasks.length;
  const scopeText = state.taskWorkspaceFilterMode === "current" && state.wizardWorkspacePath
    ? `当前工作区“${workspaceLabelByPath(state.wizardWorkspacePath)}”`
    : "全部工作区";
  hint.textContent = `当前显示 ${shown.length}/${total} 个任务 · 运行中 ${running} · 失败 ${failed} · 范围：${scopeText}`;
  hint.className = `hint-box ${failed > 0 && state.taskStatusFilter !== "active" ? "status-warn" : ""}`.trim();
}

function setTaskWorkspaceFilterMode(value = "current") {
  state.taskWorkspaceFilterMode = String(value || "current").trim().toLowerCase() || "current";
  renderTasks();
}

function setTaskStatusFilter(value = "active") {
  state.taskStatusFilter = String(value || "active").trim().toLowerCase() || "active";
  renderTasks();
}

function setTaskTypeFilter(value = "all") {
  state.taskTypeFilter = String(value || "all").trim().toLowerCase() || "all";
  renderTasks();
}

function renderResultsFilterToolbar() {
  const host = $("#results-filter-toolbar");
  const hint = $("#results-filter-hint");
  if (!host || !hint) return;
  const workspaceOptions = [{ label: "全部结果", path: "" }];
  if (state.wizardWorkspacePath) {
    workspaceOptions.push({ label: `当前工作区：${workspaceLabelByPath(state.wizardWorkspacePath)}`, path: state.wizardWorkspacePath });
  }
  if (state.runWorkspaceFilterPath && !workspaceOptions.some(item => samePath(item.path, state.runWorkspaceFilterPath))) {
    workspaceOptions.push({ label: `筛选：${workspaceLabelByPath(state.runWorkspaceFilterPath)}`, path: state.runWorkspaceFilterPath });
  }
  const profileOptions = [
    { label: "全部尺度", value: "" },
    { label: "日尺度", value: "daily" },
    { label: "小时尺度", value: "hourly" },
  ];
  const stageOptions = [
    { label: "全部阶段", value: "" },
    { label: "正式率定", value: "calibration" },
    { label: "手调起点", value: "manual_starter" },
    { label: "手调结果", value: "manual_result" },
    { label: "连续状态预报", value: "forecast_restart" },
    { label: "历史结果", value: "legacy" },
  ];
  const editabilityOptions = [
    { label: "全部结果", value: "all" },
    { label: "可继续手调", value: "editable" },
    { label: "仅查看", value: "readonly" },
  ];
  host.innerHTML = `
    <div class="results-filter-group">
      <span class="results-filter-label">工作区</span>
      ${workspaceOptions.map(item => `
        <button class="phase-chip ${samePath(item.path, state.runWorkspaceFilterPath) || (!item.path && !state.runWorkspaceFilterPath) ? "active" : ""}" data-run-filter-path="${escapeHtml(item.path)}">
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
    <div class="results-filter-group">
      <span class="results-filter-label">率定方案</span>
      ${profileOptions.map(item => `
        <button class="phase-chip ${String(item.value) === String(state.runProfileFilter || "") ? "active" : ""}" data-run-filter-profile="${escapeHtml(item.value)}">
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
    <div class="results-filter-group">
      <span class="results-filter-label">结果阶段</span>
      ${stageOptions.map(item => `
        <button class="phase-chip ${String(item.value) === String(state.runTypeFilter || "") ? "active" : ""}" data-run-filter-type="${escapeHtml(item.value)}">
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
    <div class="results-filter-group">
      <span class="results-filter-label">手调能力</span>
      ${editabilityOptions.map(item => `
        <button class="phase-chip ${String(item.value) === String(state.runEditabilityFilter || "all") ? "active" : ""}" data-run-filter-editability="${escapeHtml(item.value)}">
          ${escapeHtml(item.label)}
        </button>
      `).join("")}
    </div>
  `;
  const shown = visibleRuns();
  const workspaceText = state.runWorkspaceFilterPath ? `工作区“${workspaceLabelByPath(state.runWorkspaceFilterPath)}”` : "全部工作区";
  const profileText = state.runProfileFilter ? profileLabel(state.runProfileFilter) : "全部尺度";
  const stageText = state.runTypeFilter ? runTypeLabel(state.runTypeFilter) : "全部阶段";
  const abilityText = state.runEditabilityFilter === "editable" ? "可继续手调" : state.runEditabilityFilter === "readonly" ? "仅查看" : "全部手调能力";
  const counts = shown.reduce((acc, run) => {
    const key = runTypeValue(run);
    acc[key] = Number(acc[key] || 0) + 1;
    return acc;
  }, {});
  const breakdown = [
    counts.calibration ? `正式率定 ${counts.calibration}` : "",
    counts.manual_starter ? `手调起点 ${counts.manual_starter}` : "",
    counts.manual_result ? `手调结果 ${counts.manual_result}` : "",
    counts.forecast_restart ? `连续状态预报 ${counts.forecast_restart}` : "",
    counts.legacy ? `历史结果 ${counts.legacy}` : "",
  ].filter(Boolean).join(" / ");
  if (!state.runWorkspaceFilterPath && !state.runProfileFilter && !state.runTypeFilter && state.runEditabilityFilter === "all") {
    hint.textContent = `当前显示全部结果，共 ${state.runs.length} 组。${breakdown ? ` 其中 ${breakdown}。` : ""}`;
    hint.className = "hint-box";
  } else {
    hint.textContent = `当前筛选：${workspaceText} / ${profileText} / ${stageText} / ${abilityText}，共 ${shown.length} 组。${breakdown ? ` 其中 ${breakdown}。` : ""}`;
    hint.className = shown.length ? "hint-box status-ok" : "hint-box status-warn";
  }
}

function clearRunDetail(message = "请先从左侧选择一个结果。") {
  nextRunRequestId();
  nextRunManualPresetRequestId();
  nextCompareRequestId();
  state.currentRun = null;
  state.selectedRunPath = "";
  state._runData = null;
  state._runParams = null;
  state._runOrigParams = null;
  state.compareSeries = null;
  state.compareMetrics = null;
  state.compareLabel = "";
  state.comparePresetId = "";
  state.compareAdjusted = false;
  state.lastRunExportPath = "";
  state.runManualPresets = [];
  state.runManualPresetConfigPath = "";
  $("#results-metric-strip").innerHTML = "";
  $("#run-engineering-summary").innerHTML = "";
  $("#run-engineering-actions").innerHTML = "";
  $("#run-engineering-note").textContent = "";
  $("#run-engineering-note").className = "hint-box";
  if ($("#run-export-fields")) {
    renderRunExportFields();
  }
  if ($("#run-export-start")) $("#run-export-start").value = "";
  if ($("#run-export-end")) $("#run-export-end").value = "";
  if ($("#btn-run-export")) $("#btn-run-export").disabled = true;
  if ($("#btn-open-export-file")) $("#btn-open-export-file").disabled = true;
  if ($("#run-export-hint")) {
    $("#run-export-hint").textContent = "选择一个结果后，可按时间范围导出 Excel。";
    $("#run-export-hint").className = "hint-box";
  }
  $("#metadata-grid").innerHTML = "";
  $("#param-sliders").innerHTML = '<div class="hint-box">当前尚未选择结果。</div>';
  $("#btn-resimulate").disabled = true;
  $("#btn-reset-params").disabled = true;
  $("#resim-hint").style.display = "";
  $("#resim-hint").textContent = "请选择一个可调结果后再进行保存并重算。";
  $("#resim-hint").className = "hint-box status-warn";
  if ($("#manual-preset-name")) $("#manual-preset-name").value = "";
  if ($("#manual-preset-select")) $("#manual-preset-select").value = "";
  renderManualPresetOptions();
  updateManualPresetControls();
  renderManualPresetDiff();
  updateCompareSummary();
  if ($("#resim-log")) {
    $("#resim-log").textContent = "";
    $("#resim-log").style.display = "none";
  }
  const eventChartPanel = document.getElementById("flood-event-chart-panel");
  if (eventChartPanel) eventChartPanel.style.display = "none";
  ["hydrograph-chart", "component-chart", "residual-chart", "flood-event-chart"].forEach(id => {
    if (window.Plotly) {
      try { window.Plotly.purge(id); } catch {}
    }
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<div class="hint-box">当前没有可显示的结果图表。</div>';
  });
  const entryHint = $("#results-entry-hint");
  if (entryHint) {
    entryHint.textContent = message;
    entryHint.className = "hint-box status-warn";
  }
  updateManualStarterButtons();
  updateSidebar();
}

function manualStarterWorkspacePath() {
  return String(state.runWorkspaceFilterPath || state.wizardWorkspacePath || "").trim();
}

function findCurrentManualStartTask({ workspacePath = "", runningOnly = false } = {}) {
  const target = String(workspacePath || manualStarterWorkspacePath()).trim();
  if (!target) return null;
  return state.tasks.find(task =>
    task.task_type === "manual_start" &&
    samePath(task.config_path, target) &&
    (!runningOnly || task.status === "running")
  ) || null;
}

function updateManualStarterButtons() {
  const calibrationWorkspacePath = String(state.wizardWorkspacePath || "").trim();
  const resultsWorkspacePath = manualStarterWorkspacePath();
  const runningCalibrationTask = findCurrentManualStartTask({ workspacePath: calibrationWorkspacePath, runningOnly: true });
  const runningResultsTask = findCurrentManualStartTask({ workspacePath: resultsWorkspacePath, runningOnly: true });
  const resultsWorkspaceRunCount = resultsWorkspacePath ? runsForWorkspace(resultsWorkspacePath).length : 0;
  const calibrationBtn = $("#start-manual-starter");
  if (calibrationBtn) {
    calibrationBtn.disabled = !calibrationWorkspacePath || Boolean(runningCalibrationTask);
    calibrationBtn.textContent = runningCalibrationTask ? "正在生成手调起点..." : "生成手调起点";
  }
  const resultsWrap = $("#results-empty-actions");
  const resultsBtn = $("#results-generate-manual-starter");
  const showResultsStarter = Boolean(resultsWorkspacePath) && (!state.runs.length || (Boolean(state.runWorkspaceFilterPath) && resultsWorkspaceRunCount === 0));
  if (resultsWrap) {
    resultsWrap.style.display = showResultsStarter ? "" : "none";
  }
  if (resultsBtn) {
    resultsBtn.disabled = !resultsWorkspacePath || Boolean(runningResultsTask);
    resultsBtn.textContent = runningResultsTask ? "正在生成手调起点..." : "生成手调起点";
  }
}

async function ensureWorkspaceReadyForExecution(workspacePath, { restoreView = "", stage = "calibration" } = {}) {
  const targetPath = String(workspacePath || "").trim();
  if (!targetPath) return false;
  if (!samePath(state.wizardWorkspacePath, targetPath)) {
    await loadWorkspace(targetPath);
  }
  if (samePath(state.wizardWorkspacePath, targetPath) && hasRecentInputCheck({ requireReady: true, maxAgeMs: 5 * 60 * 1000, stage })) {
    return true;
  }
  try {
    const validation = await apiGet(`/api/config/validate?config_path=${encodeURIComponent(targetPath)}&stage=${encodeURIComponent(stage)}&prec_source=${encodeURIComponent(getTaskRuntimePrecipSource())}`);
    if (validation.data?.valid) {
      return true;
    }
  } catch {}
  setView("wizard");
  navigateWizardStep(7);
  const result = await runInputCheck({ force: true, detail: false, stage });
  const ready = Boolean(result?.ready);
  if (ready && restoreView) {
    setView(restoreView);
  }
  return ready;
}

async function startManualStarterResult({ workspacePath = "", openWhenDone = false } = {}) {
  const targetPath = String(workspacePath || manualStarterWorkspacePath() || "").trim();
  if (!targetPath) {
    showToast("请先选择工作区。", true);
    return null;
  }
  const ready = await ensureWorkspaceReadyForExecution(targetPath, { stage: "forward" });
  if (!ready) {
    showToast("当前工作区尚未满足手调/重算条件，已跳转到第 7 步。", true);
    return null;
  }
  const payload = await apiPost("/api/manual-start/start", {
    config_path: targetPath,
    calibration_mode: state.currentWorkspace?.率定模式 || "daily",
    objective_mode: $("#task-objective-mode")?.value || "daily_unified_professional_v1",
    prec_source: getTaskRuntimePrecipSource(),
    glacier_mode: $("#task-glacier-mode")?.value || "inline",
  });
  setRunWorkspaceFilter(targetPath);
  if (openWhenDone) {
    setView("results");
    clearRunDetail(`正在为工作区“${workspaceLabelByPath(targetPath)}”生成手调起点。首次运行会先装载气象与地理数据并写缓存，请看任务列表中的阶段和最新日志。`);
  }
  showToast(`已启动：${payload.task.label}`);
  await loadTasks();
  return payload.task;
}

function setRunWorkspaceFilter(path = "") {
  state.runWorkspaceFilterPath = String(path || "").trim();
  const shown = visibleRuns();
  if (currentSelectedRunPath() && !shown.some(run => samePath(run.path, currentSelectedRunPath()))) {
    clearRunDetail(
      state.runWorkspaceFilterPath
        ? `当前已切换为工作区“${workspaceLabelByPath(state.runWorkspaceFilterPath)}”结果视图，请从左侧重新选择结果。`
        : "已切换回全部结果，请从左侧重新选择结果。"
    );
  }
  renderResultsFilterToolbar();
  renderRunList();
}

function setRunProfileFilter(value = "") {
  state.runProfileFilter = String(value || "").trim().toLowerCase();
  const shown = visibleRuns();
  if (currentSelectedRunPath() && !shown.some(run => samePath(run.path, currentSelectedRunPath()))) {
    clearRunDetail("当前已切换结果筛选条件，请从左侧重新选择结果。");
  }
  renderResultsFilterToolbar();
  renderRunList();
}

function setRunTypeFilter(value = "") {
  state.runTypeFilter = String(value || "").trim().toLowerCase();
  const shown = visibleRuns();
  if (currentSelectedRunPath() && !shown.some(run => samePath(run.path, currentSelectedRunPath()))) {
    clearRunDetail("当前已切换结果阶段筛选，请从左侧重新选择结果。");
  }
  renderResultsFilterToolbar();
  renderRunList();
}

function setRunEditabilityFilter(value = "all") {
  state.runEditabilityFilter = String(value || "all").trim().toLowerCase() || "all";
  const shown = visibleRuns();
  if (currentSelectedRunPath() && !shown.some(run => samePath(run.path, currentSelectedRunPath()))) {
    clearRunDetail("当前已切换结果筛选条件，请从左侧重新选择结果。");
  }
  renderResultsFilterToolbar();
  renderRunList();
}

function runProfileValue(run) {
  return String(run?.calibration_profile || (Number(run?.time_step_hours) === 1 ? "hourly" : "daily") || "").trim().toLowerCase();
}

function alignRunFiltersForSelection(run) {
  if (!run) return false;
  let changed = false;
  const workspacePath = String(run.workspace_config || "").trim();
  const currentSelection = String(run.path || "").trim();
  if (workspacePath && state.runWorkspaceFilterPath && !samePath(workspacePath, state.runWorkspaceFilterPath)) {
    state.runWorkspaceFilterPath = workspacePath;
    changed = true;
  } else if (workspacePath && !state.runWorkspaceFilterPath) {
    const currentlyVisible = visibleRuns();
    if (currentSelection && !currentlyVisible.some(item => samePath(item.path, currentSelection))) {
      state.runWorkspaceFilterPath = workspacePath;
      changed = true;
    }
  }
  const profile = runProfileValue(run);
  if (state.runProfileFilter && profile && profile !== state.runProfileFilter) {
    state.runProfileFilter = "";
    changed = true;
  }
  const type = runTypeValue(run);
  if (state.runTypeFilter && type && type !== state.runTypeFilter) {
    state.runTypeFilter = "";
    changed = true;
  }
  if ((state.runEditabilityFilter === "editable" && !run.studio_compatible) || (state.runEditabilityFilter === "readonly" && run.studio_compatible)) {
    state.runEditabilityFilter = "all";
    changed = true;
  }
  return changed;
}

function layoutStatusClass(item) {
  if (!item?.exists) return "status-fail";
  if (item.kind === "file") return "status-ok";
  return Number(item.count || 0) > 0 ? "status-ok" : "status-warn";
}

async function copyTextToClipboard(text, successLabel = "路径") {
  const value = String(text || "").trim();
  if (!value) {
    showToast(`没有可复制的${successLabel}。`, true);
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      showToast(`${successLabel}已复制。`);
      return;
    }
  } catch {}
  try {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "readonly");
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (copied) {
      showToast(`${successLabel}已复制。`);
      return;
    }
  } catch {}
  showToast(`当前环境不支持自动复制，请手动复制${successLabel}。`, true);
}

function rememberLogViewport(element) {
  const key = String(element?.dataset?.logKey || "").trim();
  if (!key || !element) return;
  const maxScroll = Math.max(0, element.scrollHeight - element.clientHeight);
  state.logViewState[key] = {
    scrollTop: Number(element.scrollTop || 0),
    stickBottom: maxScroll <= 8 || (maxScroll - Number(element.scrollTop || 0)) <= 18,
  };
}

function restoreLogViewport(element, { defaultStickBottom = false } = {}) {
  const key = String(element?.dataset?.logKey || "").trim();
  if (!key || !element) return;
  const saved = state.logViewState[key];
  const maxScroll = Math.max(0, element.scrollHeight - element.clientHeight);
  if (saved) {
    element.scrollTop = saved.stickBottom ? maxScroll : Math.min(Number(saved.scrollTop || 0), maxScroll);
    return;
  }
  if (defaultStickBottom) {
    element.scrollTop = maxScroll;
  }
}

function setLogBoxContent(element, lines, key, { defaultStickBottom = true } = {}) {
  if (!element) return;
  element.dataset.logKey = key;
  element.dataset.logDefaultStickBottom = defaultStickBottom ? "1" : "0";
  element.tabIndex = 0;
  const text = Array.isArray(lines) ? lines.join("\n") : String(lines || "");
  rememberLogViewport(element);
  element.textContent = text;
  restoreLogViewport(element, { defaultStickBottom });
}

function restoreVisibleLogViewports(selector = "[data-log-key]") {
  document.querySelectorAll(selector).forEach(element => {
    const defaultStickBottom = element.dataset.logDefaultStickBottom === "1";
    restoreLogViewport(element, { defaultStickBottom });
  });
}

function taskLogText(taskId) {
  const task = state.tasks.find(item => String(item.id || "") === String(taskId || ""));
  return task ? (task.output || []).join("\n") : "";
}

function notifyWindowUnload() {
  const payload = "{}";
  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: "application/json" });
      navigator.sendBeacon("/api/app/window-unload", blob);
      return;
    }
  } catch {}
  try {
    fetch("/api/app/window-unload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      keepalive: true,
    }).catch(() => {});
  } catch {}
}

async function requestQuitApp() {
  await apiPost("/api/app/quit", {});
  showToast("本地服务正在退出，可关闭当前页面。");
}

async function openLocalPath(path, label = "目录") {
  const value = String(path || "").trim();
  if (!value) {
    showToast(`没有可打开的${label}。`, true);
    return;
  }
  await apiPost("/api/fs/open-path", { path: value });
  showToast(`已打开${label}。`);
}

async function jumpToWorkspaceTarget(configPath, step) {
  const targetStep = Number(step || 0);
  if (!configPath || !targetStep) return;
  if (String(state.wizardWorkspacePath || "") !== String(configPath || "")) {
    await loadWorkspace(configPath);
  }
  navigateWizardStep(targetStep);
  setView("wizard");
}

function renderWorkspaceLayout(layout, hostSelector, { emptyText = "尚未选择工作区。", title = "工作区目录结构", subtitle = "" } = {}) {
  const host = $(hostSelector);
  if (!host) return;
  if (!layout) {
    host.innerHTML = `<div class="hint-box">${escapeHtml(emptyText)}</div>`;
    return;
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
      ${(group.items || []).map(item => `
        <article class="workspace-layout-item">
          <div class="workspace-layout-item-head">
            <strong>${escapeHtml(item.label || "")}</strong>
            <span class="status-badge ${layoutStatusClass(item)}">${escapeHtml(item.status || "\u2014")}</span>
          </div>
          <div class="workspace-layout-path">${escapeHtml(item.display_path || item.path || "\u2014")}</div>
          ${directoryAliasLabel(item.path || item.display_path || "") && directoryAliasLabel(item.path || item.display_path || "") !== item.label
        ? `<div class="workspace-layout-stage">目录映射：${escapeHtml(directoryAliasLabel(item.path || item.display_path || ""))}</div>`
            : ""}
          <div class="workspace-layout-purpose">${escapeHtml(item.purpose || "")}</div>
          <div class="workspace-layout-stage">${escapeHtml(item.stage_hint || "")}</div>
          <div class="workspace-layout-actions">
            ${item.path && canOperate ? `<button class="ghost-button" data-layout-copy-path="${escapeHtml(item.path)}" data-layout-label="${escapeHtml(item.label || "路径")}">复制路径</button>` : ""}
            ${item.path && item.exists && canOperate ? `<button class="ghost-button" data-layout-open-path="${escapeHtml(item.path)}" data-layout-label="${escapeHtml(item.label || "目录")}">打开</button>` : ""}
            ${item.target_step && layout.config_path && canJump ? `<button class="ghost-button" data-layout-jump-step="${escapeHtml(String(item.target_step))}" data-layout-config="${escapeHtml(layout.config_path)}">转到第 ${escapeHtml(String(item.target_step))} 步</button>` : ""}
          </div>
        </article>
      `).join("")}
    </section>
  `).join("");
  const notes = (layout.notes || []).map(note => `<li>${escapeHtml(note)}</li>`).join("");
  host.innerHTML = `
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
    <div class="workspace-layout-grid">${groupsHtml}</div>
    ${notes ? `<ul class="workspace-layout-notes">${notes}</ul>` : ""}
  `;
}

function directoryAliasLabel(path) {
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

function buildWizardWorkspacePreviewModel() {
  if (state.currentWorkspace && state.currentWorkspaceLayout && state.currentWorkspaceLayoutPath === state.wizardWorkspacePath) {
    return state.currentWorkspaceLayout;
  }
  const name = $("#wz-name")?.value.trim() || "新流域工作区";
  const profile = getSelectedRadio("wz-timescale") || "daily";
  const profileDir = profile === "hourly" ? "小时尺度" : "日尺度";
  const configPath = state.wizardWorkspacePath || workspacePathForName(name);
  const runtimePath = String(state.currentWorkspace?.运行目录 || "").trim();
  const runtimeDisplay = runtimePath ? slashPath(runtimePath) : "保存第 1 步后自动生成工程目录";
  const resultsRoot = runtimePath
    ? `${slashPath(runtimePath)}/结果/${profileDir}`
    : `运行目录/<工程目录>/结果/${profileDir}`;
  return {
    config_path: slashPath(configPath),
    workspace_root: runtimePath ? slashPath(runtimePath) : "",
    results_root: runtimePath ? slashPath(resultsRoot) : "",
    allow_operations: false,
    allow_jump: false,
    flow_name: name,
    profile_label: profileLabel(profile),
    headline: "保存第 1 步后，系统会在本地同时维护“工作区配置文件 + 工程目录”；后续所有地理数据、气象驱动和率定结果都放在工程目录里。",
    next_focus: {
      label: "先保存第 1 步",
      reason: "保存后会自动创建目录骨架，后续第 5 步和第 6 步的数据都会写入这些目录。",
    },
    groups: [
      {
        title: "保存后会固定下来的入口",
        items: [
          {
            label: "工作区配置文件",
            display_path: slashPath(configPath),
            purpose: "保存流域名称、时间尺度、输入路径和参数配置，是整个工程的入口文件。",
            stage_hint: "第 1 步保存后固定",
            status: state.wizardWorkspacePath ? "已确定" : "待保存",
            exists: Boolean(state.wizardWorkspacePath),
            kind: "file",
            path: slashPath(configPath),
            target_step: 1,
          },
          {
            label: "工程根目录",
            display_path: runtimeDisplay,
            purpose: "这个目录下面统一放数据、过程产物、日志和率定结果。",
            stage_hint: "第 1 步保存后自动创建",
            status: runtimePath ? "已确定" : "待创建",
            exists: Boolean(runtimePath),
            kind: "dir",
            count: 0,
            path: runtimePath ? slashPath(runtimePath) : "",
            target_step: 1,
          },
        ],
      },
      {
        title: "你最需要知道的核心目录",
        items: [
          {
            label: "地理数据目录",
            display_path: runtimePath ? `${slashPath(runtimePath)}/数据/地理数据` : "工程根目录/数据/地理数据",
            purpose: "第 5 步生成 DEM、流量累积、流域掩膜和高程分区后的结果目录。",
            stage_hint: "地理数据主目录",
            status: "保存后可用",
            exists: Boolean(runtimePath),
            kind: "dir",
            count: 0,
            path: runtimePath ? `${slashPath(runtimePath)}/数据/地理数据` : "",
            target_step: 5,
          },
          {
            label: "标准气象驱动目录",
            display_path: runtimePath ? `${slashPath(runtimePath)}/数据/模型输入` : "工程根目录/数据/模型输入",
            purpose: "模型真正读取的标准气象驱动目录，排查输入问题优先看这里。",
            stage_hint: "模型运行真实输入",
            status: "保存后可用",
            exists: Boolean(runtimePath),
            kind: "dir",
            count: 0,
            path: runtimePath ? `${slashPath(runtimePath)}/数据/模型输入` : "",
            target_step: 6,
          },
          {
            label: `${profileLabel(profile)}结果目录`,
            display_path: resultsRoot,
            purpose: "率定结果、日志和缓存都会按率定方案写入这里。",
            stage_hint: "结果输出主目录",
            status: "保存后可用",
            exists: Boolean(runtimePath),
            kind: "dir",
            count: 0,
            path: runtimePath ? slashPath(resultsRoot) : "",
          },
        ],
      },
    ],
    notes: [
      "真正排查模型输入时，优先查看“标准气象驱动目录”，而不是原始气象目录。",
      "删除工作区配置文件不会自动删除工程目录中的历史数据。",
    ],
  };
}

function refreshWizardWorkspacePreview() {
  renderWorkspaceLayout(
    buildWizardWorkspacePreviewModel(),
    "#wz-workspace-layout-preview",
    {
      emptyText: "尚未生成工作区预览。",
      title: "工作区目录预览",
      subtitle: "先看清本地目录分工，再继续配置后续步骤",
    }
  );
}

function renderDashboardWorkspaceLayout() {
  renderWorkspaceLayout(
    state.dashboardWorkspaceLayout,
    "#workspace-layout-panel",
    {
      emptyText: "点击某个工作区右下角的“目录结构”，查看该工程在本地的目录分工与当前状态。",
      title: "工作区目录结构",
      subtitle: "这部分直接告诉你：配置文件在哪里、工程目录里最关键的几个子目录是什么",
    }
  );
}

function clearInputCheckCache() {
  state.lastInputCheck = {
    configPath: "",
    precipSource: "",
    stage: "calibration",
    checkedAt: 0,
    result: null,
    html: "",
  };
}

function hasRecentInputCheck({ requireReady = false, maxAgeMs = 45000, stage = "calibration" } = {}) {
  const cache = state.lastInputCheck || {};
  if (!state.wizardWorkspacePath || !cache.configPath) return false;
  if (!samePath(cache.configPath, state.wizardWorkspacePath)) return false;
  if (String(cache.precipSource || "").trim().toLowerCase() !== String(getTaskRuntimePrecipSource()).trim().toLowerCase()) return false;
  if (String(cache.stage || "calibration").trim().toLowerCase() !== String(stage || "calibration").trim().toLowerCase()) return false;
  if (!cache.result) return false;
  if ((Date.now() - Number(cache.checkedAt || 0)) > maxAgeMs) return false;
  if (findCurrentMeteoImportTask({ runningOnly: true })) return false;
  return requireReady ? Boolean(cache.result.ready) : true;
}

function stableHash32(text) {
  let hash = 2166136261;
  for (const ch of String(text || "")) {
    hash ^= ch.codePointAt(0) || 0;
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function workspacePathForName(name) {
  const raw = String(name || "").trim();
  const normalized = (raw || "新工作区").normalize("NFKC");
  const hash = stableHash32(raw || "new_workspace");
  let safe = normalized
    .replace(/[<>:"/\\|?*\x00-\x1f]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[.\s_]+|[.\s_]+$/g, "")
    .slice(0, 48)
    .replace(/^[.\s_]+|[.\s_]+$/g, "");
  if (!safe || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(safe)) {
    safe = `workspace_${hash}`;
  }
  return `workspaces/${safe}.json`;
}

function preferredWorkspaceLandingStep(workflow) {
  if (!workflow) return 1;
  return workflow.ready_for_calibration ? 1 : (workflow.next_step || 1);
}

function workspaceNextStepText(workflow) {
  if (!workflow) return "—";
  if (workflow.ready_for_calibration) return "可直接率定";
  return wizardStepLabels[workflow.next_step] || "—";
}

function formatDurationSeconds(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "\u2014";
  const total = Math.max(0, Math.round(Number(v)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function manualGroupParamNames(group, names) {
  if (group === "all") return names;
  const allowed = new Set(MANUAL_GROUP_PARAMS[group] || []);
  return names.filter(name => allowed.has(name));
}

function updateManualGroupToolbar() {
  $all("[data-manual-group]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.manualGroup === state.manualParamGroup);
  });
}

function updateManualPhaseGuide(paramNames = []) {
  const host = $("#manual-phase-guide");
  if (!host) return;
  const meta = MANUAL_GROUP_META[state.manualParamGroup] || MANUAL_GROUP_META.all;
  const shown = manualGroupParamNames(state.manualParamGroup, paramNames);
  const suffix = shown.length ? ` 当前显示 ${shown.length} 个参数。` : " 当前结果中没有这一组参数。";
  host.textContent = `${meta.title}：${meta.guide}${suffix}`;
  host.className = `hint-box ${shown.length ? "" : "status-warn"}`.trim();
}

function updateManualChangeSummary() {
  const host = $("#manual-change-summary");
  if (!host) return;
  if (!state._runParams || !state._runOrigParams) {
    host.style.display = "none";
    return;
  }
  const changed = Object.keys(state._runParams).filter(name =>
    Math.abs(Number(state._runParams[name]) - Number(state._runOrigParams[name])) > 1e-8
  );
  if (!changed.length) {
    host.style.display = "none";
    return;
  }
  const visibleChanged = manualGroupParamNames(state.manualParamGroup, changed);
  host.style.display = "";
  host.className = "hint-box status-warn";
  host.textContent = `已修改 ${changed.length} 个参数。${visibleChanged.length ? `当前分组中已改动：${visibleChanged.join("、")}` : "当前分组内暂无改动参数。"}`
}

function renderManualPresetDiff() {
  const host = $("#manual-preset-diff");
  if (!host) return;
  const preset = selectedManualPreset();
  const baseline = state._runOrigParams || {};
  if (!preset || !Object.keys(baseline).length) {
    host.style.display = "none";
    return;
  }
  const diffs = Object.entries(preset.params || {})
    .filter(([name, value]) => Number.isFinite(Number(baseline[name])) && Math.abs(Number(value) - Number(baseline[name])) > 1e-8)
    .map(([name, value]) => ({
      name,
      from: Number(baseline[name]),
      to: Number(value),
      delta: Number(value) - Number(baseline[name]),
    }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  if (!diffs.length) {
    host.style.display = "";
    const mismatchText = manualPresetContextWarning(preset);
    host.className = `hint-box ${mismatchText ? "status-warn" : ""}`.trim();
    host.textContent = `参数集“${preset.name}”与当前率定参数一致。${mismatchText ? ` ${mismatchText}` : ""}`;
    return;
  }
  const preview = diffs.slice(0, 8).map(item =>
    `${item.name}: ${formatNumber(item.from, 4)} → ${formatNumber(item.to, 4)} (${item.delta > 0 ? "+" : ""}${formatNumber(item.delta, 4)})`
  ).join("；");
  host.style.display = "";
  const mismatchText = manualPresetContextWarning(preset);
  host.className = `hint-box ${mismatchText ? "status-warn" : ""}`.trim();
  host.textContent = `参数集“${preset.name}”与当前率定值相比有 ${diffs.length} 个参数不同。${preview}${mismatchText ? ` ${mismatchText}` : ""}`;
}

function manualPresetContextWarning(preset, data = state._runData) {
  if (!preset || !data?.metadata) return "";
  const meta = data.metadata || {};
  return window.HBVStudioParameterLibrary?.manualContextWarning(
    preset,
    {
      objective_mode: effectiveObjectiveMode(meta),
      prec_source: String(meta.data_sources?.runtime_prec_source || meta.data_sources?.prec_source || meta.data_sources?.configured_precip_source || "").trim().toLowerCase(),
      glacier_mode: String(meta.data_sources?.glacier_mode || "").trim().toLowerCase(),
      param_bounds_profile: String(meta.param_bounds_profile || meta.parameter_profile?.bounds_profile || "").trim().toLowerCase(),
    },
    {
      objectiveLabel,
      precipSourceLabel: getConfiguredPrecipSourceLabel,
      boundsLabel: value => PARAM_BOUNDS_PROFILE_LABELS[value] || value,
    },
  ) || "";
}

function timeBasisLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  if (key === "event_windows") return "洪水事件窗口";
  if (key === "forecast_window") return "预报窗口";
  return "连续时段";
}

function selectedTaskManualPreset() {
  const presetId = $("#task-init-preset")?.value || "";
  return state.taskManualPresets.find(p => String(p.id || "") === String(presetId)) || null;
}

function currentTaskPresetContext() {
  const profile = normalizeCalibrationProfile(state.currentWorkspace?.率定模式, "daily");
  const meteo = state.currentWorkspace?.气象策略 || {};
  const timeStepHours = Number(state.currentWorkspace?.时间步长_小时 || (profile === "hourly" ? 1 : 24));
  const precipitationMode = getSelectedRadio("wz-precip-mode")
    || meteo.降水方案
    || meteo.precipitation_mode
    || "grid_only";
  return {
    profile,
    time_step_hours: Number.isFinite(timeStepHours) ? timeStepHours : (profile === "hourly" ? 1 : 24),
    objective_mode: $("#task-objective-mode")?.value || CURRENT_OBJECTIVE_FAMILY,
    prec_source: getTaskRuntimePrecipSource(),
    glacier_mode: $("#task-glacier-mode")?.value || "inline",
    param_bounds_profile: profile === "daily" ? ($("#task-param-bounds-profile")?.value || "qtp_alpine_default") : "hourly_step",
    precipitation_mode: precipitationMode,
    task_time_basis: $("#wz-time-basis")?.value || state.currentWorkspace?.任务时段模式 || state.currentWorkspace?.time_basis || "continuous",
  };
}

function taskPresetContextWarnings(preset, current = currentTaskPresetContext()) {
  return window.HBVStudioParameterLibrary?.taskContextWarnings(preset, current, {
    profileLabel,
    objectiveLabel,
    precipSourceLabel: getConfiguredPrecipSourceLabel,
    stationPrecipModeLabel,
    timeBasisLabel,
    formatNumber,
    paramBoundsProfileLabels: PARAM_BOUNDS_PROFILE_LABELS,
  }) || [];
}

function renderTaskPresetContextHint() {
  const host = $("#task-init-preset-context");
  if (!host) return;
  const preset = selectedTaskManualPreset();
  window.HBVStudioParameterLibrary?.renderTaskContextHint(host, preset, currentTaskPresetContext(), {
    escapeHtml,
    profileLabel,
    objectiveLabel,
    precipSourceLabel: getConfiguredPrecipSourceLabel,
    stationPrecipModeLabel,
    timeBasisLabel,
    formatNumber,
    paramBoundsProfileLabels: PARAM_BOUNDS_PROFILE_LABELS,
  });
}

function clearManualPresetComparison({ silent = false } = {}) {
  nextCompareRequestId();
  state.compareSeries = null;
  state.compareMetrics = null;
  state.compareLabel = "";
  state.comparePresetId = "";
  state.compareAdjusted = false;
  const host = $("#manual-compare-summary");
  if (host) {
    host.style.display = "none";
    host.textContent = "";
  }
  if (state._runData) {
    renderCharts(state._runData);
    const meta = state._runData.metadata || {};
    const cal = meta.metrics?.calibration || {};
    const val = meta.metrics?.validation || {};
    updateMetricsStrip(cal, val, meta);
  }
  updateManualPresetControls();
  if (!silent) showToast("已清除参数集对比。");
}

function updateCompareSummary() {
  const host = $("#manual-compare-summary");
  if (!host) return;
  if (!state.compareMetrics || !state.compareLabel || !state._runData) {
    host.style.display = "none";
    host.textContent = "";
    return;
  }
  const baseMeta = state._runData.metadata || {};
  const baseCal = baseMeta.metrics?.calibration || {};
  const baseVal = baseMeta.metrics?.validation || {};
  const cmp = state.compareMetrics;
  const cmpCal = finiteNumber(cmp.nse_cal);
  const cmpVal = finiteNumber(cmp.nse_val);
  const baseCalValue = finiteNumber(baseCal.nse);
  const baseValValue = finiteNumber(baseVal.nse);
  const deltaCal = (cmpCal !== null && baseCalValue !== null) ? (cmpCal - baseCalValue) : null;
  const deltaVal = (cmpVal !== null && baseValValue !== null) ? (cmpVal - baseValValue) : null;
  const adjustedNote = state.compareAdjusted ? "该参数集在运行前已按约束自动修正。" : "";
  let statusClass = "";
  if (deltaCal !== null) statusClass = deltaCal >= 0 ? "status-ok" : "status-warn";
  else if (deltaVal !== null) statusClass = deltaVal >= 0 ? "status-ok" : "status-warn";
  host.style.display = "";
  host.className = `hint-box ${statusClass}`.trim();
  host.textContent = [
    `当前正在对比参数集“${state.compareLabel}”。`,
    `${compareMetricSummary("率定纳什效率系数", cmp.nse_cal, baseCal.nse)}。`,
    `${compareMetricSummary("验证纳什效率系数", cmp.nse_val, baseVal.nse)}。`,
    adjustedNote,
  ].filter(Boolean).join(" ");
}

function clearStaleManualPresetComparison({ silent = true } = {}) {
  if (!state.comparePresetId) return;
  const currentPresetId = String(selectedManualPreset()?.id || "").trim();
  const comparePresetId = String(state.comparePresetId || "").trim();
  if (!comparePresetId) return;
  if (currentPresetId === comparePresetId) return;
  clearManualPresetComparison({ silent });
}

function goToWizardStep(step) {
  goToWizardTarget(Number(step) || 1, "");
}

function flashFocusTarget(target) {
  if (!target) return;
  target.classList.add("smart-focus");
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  if (typeof target.focus === "function") {
    try { target.focus({ preventScroll: true }); } catch { target.focus(); }
  }
  clearTimeout(target._smartFocusTimer);
  target._smartFocusTimer = setTimeout(() => target.classList.remove("smart-focus"), 1800);
}

function inferIssueTarget(message, fallbackStep = 7) {
  const text = String(message || "");
  const rules = [
    { match: ["时间.预热开始"], step: 2, selector: "#wz-warmup-start" },
    { match: ["时间.预热结束"], step: 2, selector: "#wz-warmup-end" },
    { match: ["时间.率定开始"], step: 2, selector: "#wz-calib-start" },
    { match: ["时间.率定结束"], step: 2, selector: "#wz-calib-end" },
    { match: ["时间.验证开始"], step: 2, selector: "#wz-valid-start" },
    { match: ["时间.验证结束"], step: 2, selector: "#wz-valid-end" },
    { match: ["流域边界"], step: 2, selector: "#wz-basin-shp" },
    { match: ["观测径流"], step: 2, selector: "#wz-obs-csv" },
    { match: ["上游边界入流"], step: 3, selector: "#wz-boundary-csv" },
    { match: ["站点降水"], step: 4, selector: "#wz-station-prec" },
    { match: ["站点信息"], step: 4, selector: "#wz-station-meta" },
    { match: ["本地降水栅格", "自带降水 tif", "自带降水"], step: 4, selector: "#wz-custom-prec-dir" },
    { match: ["本地气温栅格", "自带温度 tif", "自带温度"], step: 4, selector: "#wz-custom-temp-dir" },
    { match: ["本地蒸散发栅格", "自带蒸散发 tif", "自带蒸散发"], step: 4, selector: "#wz-custom-pet-dir" },
    { match: ["dem_1km", "dem_0p1deg", "DEM"], step: 5, selector: "#wz-run-bootstrap" },
    { match: ["flow_accumulation_masked", "流量累积", "流域掩膜", "高程分区"], step: 5, selector: "#wz-run-bootstrap" },
    { match: ["降水目录", "降水时间覆盖", "降水目录有", "降水目录存在", "降水时间戳", "降水有"], step: 6, selector: "#wz-import-prec-dir" },
    { match: ["气温目录", "气温时间覆盖", "气温目录有", "气温目录存在", "气温时间戳", "气温有"], step: 6, selector: "#wz-import-temp-dir" },
    { match: ["蒸散发目录", "蒸散发时间覆盖", "蒸散发目录有", "蒸散发目录存在", "蒸散发时间戳", "蒸散发有"], step: 6, selector: "#wz-import-evap-dir" },
    { match: ["气象驱动", "forcing", ".tif"], step: 6, selector: "#wz-import-meteo-btn" },
  ];
  for (const rule of rules) {
    if (rule.match.some(token => text.includes(token))) {
      return { step: rule.step, selector: rule.selector };
    }
  }
  return fallbackStep ? { step: fallbackStep, selector: "" } : null;
}

function renderIssueJumpButton(message, fallbackStep = 7) {
  const target = inferIssueTarget(message, fallbackStep);
  if (!target) return "";
  return ` <button class="ghost-button" data-go-step="${escapeHtml(target.step)}" data-go-selector="${escapeHtml(target.selector || "")}" style="padding:4px 10px;font-size:12px">定位</button>`;
}

function setRadioValue(name, value) {
  const radio = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (!radio) return;
  radio.checked = true;
  const group = radio.closest(".radio-card-group");
  if (group) {
    group.querySelectorAll(".radio-card").forEach(card => card.classList.remove("selected"));
    radio.closest(".radio-card")?.classList.add("selected");
  }
}

function prepareWizardTarget(selector = "") {
  const importGisSelectors = new Set(["#wz-import-dem", "#wz-import-flowacc", "#wz-import-flowdir", "#wz-import-glacier", "#wz-import-gis-btn"]);
  const autoGisSelectors = new Set(["#wz-run-bootstrap"]);
  const importMeteoSelectors = new Set(["#wz-import-prec-dir", "#wz-import-temp-dir", "#wz-import-evap-dir", "#wz-import-meteo-btn"]);
  if (importGisSelectors.has(selector)) {
    setRadioValue("wz-gis-mode", "import");
    updateGisMode();
  } else if (autoGisSelectors.has(selector)) {
    setRadioValue("wz-gis-mode", "auto");
    updateGisMode();
  }
  if (importMeteoSelectors.has(selector)) {
    setRadioValue("wz-meteo-mode", "import");
    updateMeteoMode();
  }
}

function goToWizardTarget(step, selector = "") {
  const targetStep = Number(step) || 1;
  setView("wizard");
  navigateWizardStep(targetStep);
  setTimeout(() => {
    if (selector) {
      prepareWizardTarget(selector);
      const el = $(selector);
      if (el) flashFocusTarget(el);
    }
    if (targetStep === 7) {
      runInputCheck().catch(err => showToast(err.message, true));
    }
  }, 120);
}

function taskStageLabel(stage) {
  const normalized = String(stage || "").toLowerCase();
  return ({
    mc: "快速筛选",
    global: "精细搜索",
    refine: "局部精修",
  })[normalized] || (normalized ? `未知阶段（${normalized}）` : "未知阶段");
}

function taskStatusLabel(status) {
  return ({
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    pending: "等待中",
  })[String(status || "").toLowerCase()] || String(status || "未知");
}

function taskStatusClass(status) {
  return status === "completed" ? "status-ok" : status === "failed" ? "status-fail" : "status-warn";
}

function taskTypeLabel(taskType) {
  return ({
    calibration: "率定任务",
    data_prep: "数据准备",
    bootstrap: "基础地理处理",
    meteo_import: "气象导入",
    manual_start: "手调起点",
    forward_sim: "保存并重算",
    forecast_restart: "连续状态预报",
    self_check: "系统自检",
    sync: "模板同步",
  })[String(taskType || "").toLowerCase()] || "任务";
}

function methodLabel(method) {
  return ({
    manual_adjustment: "手调后重算",
    manual_start: "手调起点",
    mc_screen_de: "快速筛选 + 精细搜索",
    de: "精细搜索（差分进化）",
    mc_only: "仅快速筛选",
  })[String(method || "").toLowerCase()] || String(method || "未设置");
}

function optimizationMethodLabel(optimization) {
  const methodKey = String(optimization?.method || "").trim().toLowerCase();
  const refine = optimization?.stage_stats?.refine || {};
  const refineRequested = Boolean(optimization?.refine_requested || optimization?.refine_enabled || refine?.requested);
  const refineExecuted = Boolean(optimization?.refine_executed || refine?.executed);
  const refineSkipped = Boolean(String(refine?.skipped_reason || "").trim());
  const polishEnabled = Boolean(optimization?.polish);
  if (methodKey === "de") {
    if (refineExecuted) return "精细搜索 + 局部精修";
    if (refineRequested && refineSkipped) return "精细搜索（局部精修已跳过）";
    if (refineRequested) return "精细搜索（局部精修未产出有效结果）";
    if (polishEnabled) return "精细搜索（含末端精修）";
    return "精细搜索（差分进化）";
  }
  if (methodKey === "mc_screen_de") {
    if (refineExecuted) return "快速筛选 + 精细搜索 + 局部精修";
    if (refineRequested && refineSkipped) return "快速筛选 + 精细搜索（局部精修已跳过）";
    if (refineRequested) return "快速筛选 + 精细搜索（局部精修未产出有效结果）";
    if (polishEnabled) return "快速筛选 + 精细搜索（含末端精修）";
    return "快速筛选 + 精细搜索";
  }
  if (methodKey === "mc_only") return "仅快速筛选";
  const explicit = String(optimization?.method_label || "").trim();
  return explicit || methodLabel(methodKey);
}

function objectiveLabel(value) {
  return ({
    auto: "自动选择",
    daily_unified_professional_v1: "统一日尺度专业目标函数",
    flood_event_calibration_v1: "洪水事件率定（次洪）",
    weighted_multi_criteria: "旧版多指标目标函数（历史结果）",
    weighted_daily_universal: "旧版日尺度加权目标函数（历史结果）",
    single_objective_nse: "单指标纳什效率系数",
  })[String(value || "").toLowerCase()] || String(value || "未设置");
}

function effectiveObjectiveMode(meta) {
  const normalizedMode = String(meta?.effective_objective_mode || meta?.optimization?.effective_objective_mode || "").trim().toLowerCase();
  if (normalizedMode) return normalizedMode;
  const profileMode = String(meta?.objective_profile?.type || meta?.objective?.type || "").trim().toLowerCase();
  if (profileMode) return profileMode;
  return String(meta?.optimization?.objective_mode || "").trim().toLowerCase();
}

function requestedObjectiveMode(meta) {
  return String(meta?.requested_objective_mode || meta?.optimization?.requested_objective_mode || meta?.optimization?.objective_mode || "").trim().toLowerCase();
}

function objectiveDetail(meta) {
  const mode = effectiveObjectiveMode(meta) || meta?.objective_family || meta?.objective_profile?.type || meta?.objective?.type;
  if (String(mode || "").toLowerCase() === "daily_unified_professional_v1") {
    return "流量拟合优先，结合融雪、融冰、洪峰和退水过程进行综合评价";
  }
  if (String(mode || "").toLowerCase() === FLOOD_EVENT_OBJECTIVE_FAMILY) {
    return "按洪水事件窗口评价洪峰、峰现时间、洪量、退水和高流量过程；事件资料模式下按场独立预热";
  }
  if (LEGACY_OBJECTIVE_FAMILIES.has(String(mode || "").toLowerCase())) {
    return "历史结果，仅作兼容查看，建议用当前口径重算后再解释冰雪融水过程";
  }
  return "";
}

function objectiveSummary(meta) {
  return [objectiveLabel(effectiveObjectiveMode(meta) || "—"), objectiveDetail(meta)].filter(Boolean).join(" · ");
}

function estimateCalibrationLoad() {
  const method = $("#task-method")?.value || "mc_screen_de";
  const maxiter = Math.max(0, Number($("#task-maxiter")?.value) || 0);
  const popsize = Math.max(1, Number($("#task-popsize")?.value) || 1);
  const mcSamples = Math.max(0, Number($("#task-mc-samples")?.value) || 0);
  const workers = Math.max(1, Number($("#task-workers")?.value) || 1);
  const population = popsize * CALIBRATION_PARAM_COUNT;
  let estimated = 0;
  let label = "";
  if (method === "mc_only") {
    estimated = mcSamples;
    label = "快速筛选";
  } else if (method === "de") {
    estimated = (maxiter + 1) * population;
    label = "精细搜索";
  } else {
    estimated = mcSamples + (maxiter + 1) * population;
    label = "快速筛选 + 精细搜索";
  }
  const perWorker = workers > 0 ? estimated / workers : estimated;
  const level = estimated >= 12000 ? "heavy" : estimated >= 5000 ? "medium" : "light";
  return { method, maxiter, popsize, mcSamples, workers, population, estimated, perWorker, label, level };
}

function updateCalibrationPlainGuide() {
  const host = $("#calibration-plain-guide");
  if (!host) return;
  const kind = $("#task-kind")?.value || "calibration";
  const method = $("#task-method")?.value || "mc_screen_de";
  const objectiveMode = $("#task-objective-mode")?.value || CURRENT_OBJECTIVE_FAMILY;
  const loadInfo = estimateCalibrationLoad();
  if (kind === "self_check") {
    host.textContent = "系统自检仅核对本地环境、依赖和关键脚本状态，不读取率定参数。";
    host.className = "hint-box";
    return;
  }
  if (kind === "quick_test") {
    host.textContent = "输入预核算只执行限定时段前向计算，不做正式参数搜索，用于确认输入资料可用。";
    host.className = "hint-box status-ok";
    return;
  }
  if (kind === "debug_calibration") {
    host.textContent = "快速试算（短窗口）会使用率定开始后的前 N 天进行搜索，仅作为参数敏感性的快速参考，不替代正式率定。";
    host.className = "hint-box status-ok";
    return;
  }
  const methodText = method === "de"
    ? "当前策略直接进入精细搜索，步骤最少，但耗时较长。"
    : method === "mc_only"
      ? "当前策略仅快速筛选，用来快速看参数敏感性和候选区间。"
      : "当前策略先快速筛选，再把更好的候选送入精细搜索，是默认更稳妥的方案。";
  const objectiveText = objectiveMode === FLOOD_EVENT_OBJECTIVE_FAMILY
    ? "当前评分标准为洪水事件率定；连续资料按完整时段运行并在事件窗口评分，事件资料模式按场独立预热并只要求事件内资料完整。"
    : "当前评分标准为综合水文目标函数，优先保证连续径流拟合，并兼顾冰雪融水过程。";
  host.textContent = `运行说明：快速筛选样本数表示前期候选参数组数；搜索轮数表示后续优化轮数；每轮候选数倍率=${loadInfo.popsize}，每轮样本数约为参数数 ${CALIBRATION_PARAM_COUNT} × ${loadInfo.popsize} = ${loadInfo.population}。${objectiveText}${methodText}`;
  host.className = "hint-box";
}

function updateCalibrationGuidance() {
  const smart = $("#calibration-smart-advice");
  const strategy = $("#calibration-strategy-summary");
  const load = $("#calibration-load-summary");
  const startBtn = $("#start-task-button");
  const applyBtn = $("#apply-recommended-calibration");
  const stepBtn = $("#go-recommended-step");
  const precSelect = $("#task-prec-source");
  if (!smart || !strategy || !load) return;
  updateCalibrationPlainGuide();
  syncTaskPrecipSourceControl();
  const kind = $("#task-kind")?.value || "calibration";
  const workflow = state.currentWorkspaceWorkflow;
  const advice = state.currentWorkspaceAdvice;
  const needsWorkspace = kind !== "self_check";
  const hasFreshReadyCheck = hasRecentInputCheck({ requireReady: true, maxAgeMs: 5 * 60 * 1000 });
  const blocked = (needsWorkspace && !state.wizardWorkspacePath) || (kind !== "self_check" && !hasFreshReadyCheck && workflow && !workflow.ready_for_calibration);
  if (startBtn) {
    startBtn.disabled = blocked;
    startBtn.title = !needsWorkspace
      ? ""
      : !state.wizardWorkspacePath
        ? "请先选择工作区"
        : (workflow && !workflow.ready_for_calibration ? "当前工作区仍有输入缺项" : "");
  }
  if (applyBtn) {
    applyBtn.disabled = !state.currentWorkspaceAdvice?.calibration;
  }
  if (stepBtn) {
    stepBtn.disabled = Boolean(workflow?.ready_for_calibration) || !(workflow?.next_step || state.currentWorkspaceAdvice?.recommended_step);
    stepBtn.title = workflow?.ready_for_calibration ? "当前输入检查已通过，无需再回到向导补步骤。" : "";
  }
  if (kind === "self_check") {
    smart.textContent = "智能建议：系统自检只核对环境和脚本状态，不涉及率定策略。";
    smart.className = "hint-box";
    strategy.textContent = "系统自检不会启动率定，仅核对本地运行环境。";
    strategy.className = "hint-box";
    load.textContent = "当前任务不涉及参数搜索负载。";
    load.className = "hint-box";
    return;
  }
  const configuredSource = getConfiguredPrecipSource();
  const objectiveMode = $("#task-objective-mode")?.value || CURRENT_OBJECTIVE_FAMILY;
  if (precSelect) {
    const locked = configuredSource === "custom_tif";
    precSelect.disabled = locked;
    precSelect.title = locked ? "当前工程使用本地降水栅格，运行时直接读取工程独立降水目录。" : "";
  }
  if (kind === "quick_test") {
    smart.textContent = advice?.headline ? `智能建议：${advice.headline}` : "智能建议：先完成输入完整性检查，再启动正式率定。";
    smart.className = "hint-box";
    strategy.textContent = "输入预核算只执行限定时段前向计算，适合核对气象输入、地理数据和参数文件是否可用。";
    strategy.className = "hint-box";
    load.textContent = `当前只计算 ${Number($("#task-quick-days")?.value) || 30} 天，不进行正式精细搜索。`;
    load.className = "hint-box";
    return;
  }
  if (kind === "debug_calibration") {
    const debugDays = Number($("#task-quick-days")?.value) || 30;
    const loadInfo = estimateCalibrationLoad();
    smart.textContent = advice?.headline
      ? `智能建议：${advice.headline} 当前使用快速试算，可先看参数响应。`
      : "智能建议：快速试算适合先确认参数响应，再进入正式率定。";
    smart.className = "hint-box status-ok";
    strategy.textContent = "快速试算会保留预热段，优先使用率定开始后的有效时段参与搜索；如果起始窗口观测变化不足，系统会自动顺延到首个可计算时段。";
    strategy.className = "hint-box status-ok";
    load.textContent = `${loadInfo.label}：当前仅使用率定开始后的前 ${debugDays} 天做快速试算，搜索次数不变，但单次前向模拟会明显缩短。`;
    load.className = "hint-box status-ok";
    return;
  }
  const loadInfo = estimateCalibrationLoad();
  if (advice?.calibration) {
    const reasons = (advice.calibration.reasons || []).slice(0, 2).join(" ");
    const quickText = advice.calibration.quick_test_first ? "建议先完成输入完整性检查，再启动正式率定。" : "";
    smart.textContent = `智能建议：${advice.headline} 推荐使用“${advice.calibration.method_label}”。${quickText}${reasons}`;
    smart.className = `hint-box ${advice.ready_for_calibration ? "status-ok" : "status-warn"}`.trim();
  } else {
    smart.textContent = workflow?.ready_for_calibration
      ? "智能建议：建议先完成输入完整性检查，再手动调一轮雪过程、土壤过程和产汇流，最后启动自动率定。"
      : "智能建议：请先补齐输入缺项，再考虑率定方式。";
    smart.className = `hint-box ${workflow?.ready_for_calibration ? "status-ok" : "status-warn"}`.trim();
  }
  if (workflow && !workflow.ready_for_calibration) {
    strategy.textContent = `当前工作区还未满足率定条件，建议先回向导补齐缺项。下一步：${wizardStepLabels[workflow.next_step] || "输入检查"}。`;
    strategy.className = "hint-box status-warn";
  } else if (workflow?.ready_for_calibration) {
    strategy.textContent = workspaceHasEditableRun(state.wizardWorkspacePath)
      ? "当前工作区已通过输入检查，可直接启动率定。若要自己手动调参，可直接打开本工作区已有结果，在结果页改参数值并重算。"
      : "当前工作区已通过输入检查。若还没有结果，可先生成一个“手调起点”，再在结果页直接改参数值并重算。";
    strategy.className = "hint-box status-ok";
  } else if (loadInfo.method === "mc_only") {
    strategy.textContent = "当前策略仅做快速筛选，用来扫范围、看敏感性和挑候选参数集，不进入精细搜索或局部精修。";
    strategy.className = "hint-box";
  } else if (loadInfo.method === "de") {
    strategy.textContent = "当前策略直接进入精细搜索（差分进化），步骤最少，但在大流域上耗时较长。建议只在参数范围已经收窄后使用。";
    strategy.className = loadInfo.level === "heavy" ? "hint-box status-warn" : "hint-box";
  } else {
    strategy.textContent = "当前策略先做快速筛选，再进入精细搜索，是更稳妥的默认方案。";
    strategy.className = "hint-box status-ok";
  }
  const runtimeSource = getTaskRuntimePrecipSource();
  const taskSource = getTaskPrecipSource();
  const forcingText = runtimeSource === "custom_tif"
    ? `当前工作区使用${getRuntimePrecipDirectoryLabel(configuredSource)}。`
    : `当前“降水源”选择为 ${getConfiguredPrecipSourceLabel(taskSource)}，运行时读取 ${getRuntimePrecipDirectoryLabel(taskSource)}。`;
  const boundsProfile = $("#task-param-bounds-profile")?.value || "qtp_alpine_default";
  const boundsLabel = PARAM_BOUNDS_PROFILE_LABELS[boundsProfile] || boundsProfile;
  const boundsText = (state.currentWorkspace?.率定模式 || "daily") === "daily" ? `参数范围：${boundsLabel}。` : "";
  const objectiveText = `评分标准：${objectiveLabel(objectiveMode)}。`;
  load.textContent = `${loadInfo.label}：参数数约 ${CALIBRATION_PARAM_COUNT}，搜索种群 ${loadInfo.population}，预计总评估约 ${Math.round(loadInfo.estimated)} 次，折算到 ${loadInfo.workers} 线程约每线程 ${Math.round(loadInfo.perWorker)} 次。${objectiveText}${boundsText}${forcingText}`;
  load.className = `hint-box ${loadInfo.level === "heavy" ? "status-warn" : loadInfo.level === "medium" ? "" : "status-ok"}`.trim();
}

function profileLabel(p) {
  return p === "hourly" ? "小时尺度" : p === "daily" ? "日尺度" : "未选择";
}

function profileBadge(p) {
  return `<span class="status-badge">${profileLabel(p)}</span>`;
}

function objectBadge(o) {
  return `<span class="status-badge">${escapeHtml(objectLabels[o] || "未定义对象")}</span>`;
}

function focusStatusLabel(status) {
  return ({ ok: "通过", warn: "注意", fail: "未通过" })[String(status || "").toLowerCase()] || "待检查";
}

function focusStatusClass(status) {
  return status === "ok" ? "status-ok" : status === "fail" ? "status-fail" : "status-warn";
}

function renderStationEventCoverageMatrix(check = {}) {
  const renderer = window.HBVStudioStationPrecip?.renderEventCoverageMatrix;
  if (!renderer) return "";
  return renderer(check, {
    escapeHtml,
    focusStatusClass,
    focusStatusLabel,
    formatNumber,
  });
}

function renderEngineeringFocusChecks(checks = [], { title = "专项检查", emptyText = "暂无专项检查。" } = {}) {
  if (!checks.length) {
    return `<div class="hint-box">${escapeHtml(emptyText)}</div>`;
  }
  return `
    <div class="focus-check-grid">
      ${checks.map(check => `
        <section class="focus-check-card">
          <div class="focus-check-head">
            <strong>${escapeHtml(check.title || title)}</strong>
            <span class="status-badge ${focusStatusClass(check.status)}">${escapeHtml(focusStatusLabel(check.status))}</span>
          </div>
          <div class="focus-check-summary">${escapeHtml(check.summary || "")}</div>
          <div class="focus-check-items">
            ${(check.items || []).map(item => `
              <div class="focus-check-item">
                <span class="focus-check-label">${escapeHtml(item.label || "")}</span>
                <span class="focus-check-value ${focusStatusClass(item.status)}">${escapeHtml(item.value || "—")}</span>
              </div>
            `).join("")}
          </div>
          ${renderStationEventCoverageMatrix(check)}
        </section>
      `).join("")}
    </div>
  `;
}

function stationPrecipModeLabel(mode) {
  return ({
    grid_only: "格点直接使用",
    grid_plus_station_bias: "格点 + 站点偏差订正",
    thiessen_station_only: "纯泰森多边形插值",
  })[String(mode || "").toLowerCase()] || "格点直接使用";
}

function stationPrecipModeDescription(mode) {
  if (mode === "grid_plus_station_bias") {
    return "按时段在站点位置抽取格点降水，采用比值订正与残差订正并进行空间插值，形成逐栅格订正降水。";
  }
  if (mode === "thiessen_station_only") {
    return "直接以站点降水控制目标格网，按最近控制站形成面雨量场，适合作为站点资料主导的基线方案。";
  }
  return "不启用站点订正或泰森分配，降水输入来自当前格点数据源。";
}

function renderPrecipStrategyStatus() {
  const host = $("#wz-precip-strategy-status");
  if (!host) return;
  const mode = getSelectedRadio("wz-precip-mode") || "grid_only";
  const stationPrec = $("#wz-station-prec")?.value.trim() || "";
  const stationMeta = $("#wz-station-meta")?.value.trim() || "";
  const needsStation = mode !== "grid_only";
  const stationReady = Boolean(stationPrec && stationMeta);
  const statusClass = !needsStation ? "status-ok" : stationReady ? "status-ok" : "status-warn";
  const statusText = !needsStation ? "未启用站点资料" : stationReady ? "站点资料已登记" : "待登记站点资料";
  host.innerHTML = `
    <div class="workflow-signal-card ${statusClass}">
      <strong>${escapeHtml(stationPrecipModeLabel(mode))}</strong>
      <span>${escapeHtml(statusText)}</span>
      <small>${escapeHtml(stationPrecipModeDescription(mode))}</small>
    </div>
    <div class="workflow-signal-card ${needsStation ? (stationPrec ? "status-ok" : "status-warn") : ""}">
      <strong>站点降水表</strong>
      <span>${escapeHtml(needsStation ? (stationPrec ? shortPath(stationPrec) : "未选择") : "不需要")}</span>
      <small>用于站点时间序列、站号匹配、缺测率和异常降水检查。</small>
    </div>
    <div class="workflow-signal-card ${needsStation ? (stationMeta ? "status-ok" : "status-warn") : ""}">
      <strong>站点空间信息</strong>
      <span>${escapeHtml(needsStation ? (stationMeta ? shortPath(stationMeta) : "未选择") : "不需要")}</span>
      <small>用于经纬度定位、格点抽样、空间权重和目标栅格分配。</small>
    </div>
  `;
}

function stationPrecipCheckFromValidation(validation) {
  const checks = validation?.focus_checks || [];
  return checks.find(check => String(check?.id || "").toLowerCase() === "station_precip")
    || checks.find(check => String(check?.title || "").includes("站点降水"))
    || null;
}

function renderStationPrecipCheckOverview(validation = null) {
  const host = $("#wz-station-check-overview");
  if (!host) return;
  const mode = getSelectedRadio("wz-precip-mode") || state.currentWorkspace?.气象策略?.降水方案 || "grid_only";
  const check = stationPrecipCheckFromValidation(validation);
  if (check) {
    host.innerHTML = renderEngineeringFocusChecks([check], { title: "站点降水专项检查" });
    return;
  }
  const stationPrec = $("#wz-station-prec")?.value.trim() || state.currentWorkspace?.气象策略?.站点降水_csv || "";
  const stationMeta = $("#wz-station-meta")?.value.trim() || state.currentWorkspace?.气象策略?.站点信息_csv || "";
  const needsStation = mode !== "grid_only";
  const status = !needsStation ? "ok" : (stationPrec && stationMeta ? "warn" : "fail");
  const summary = !needsStation
    ? "当前为格点基线模式，输入检查不会执行站点降水订正专项分析。"
    : (stationPrec && stationMeta
      ? "站点降水资料已登记，运行检查后会输出站号匹配、时间覆盖、缺测率和异常值。"
      : "当前降水方案需要站点降水表和站点空间信息，资料未完整登记。");
  host.innerHTML = renderEngineeringFocusChecks([{
    title: "站点降水专项检查",
    summary,
    status,
    items: [
      { label: "降水方案", value: stationPrecipModeLabel(mode), status: needsStation ? "ok" : "warn" },
      { label: "站点降水表", value: stationPrec ? shortPath(stationPrec) : (needsStation ? "缺失" : "不需要"), status: !needsStation || stationPrec ? "ok" : "fail" },
      { label: "站点空间信息", value: stationMeta ? shortPath(stationMeta) : (needsStation ? "缺失" : "不需要"), status: !needsStation || stationMeta ? "ok" : "fail" },
    ],
  }], { title: "站点降水专项检查" });
}

function updateProjectFocusHint() {
  const host = $("#wz-project-focus");
  if (!host) return;
  const hourly = isHourlyTimescaleSelected();
  const objectType = getSelectedRadio("wz-object") || "full_upstream_basin";
  let text = "";
  let className = "hint-box";
  if (!hourly && objectType === "full_upstream_basin") {
    text = "当前是“日尺度 + 完整上游流域”组合，最适合作为正式项目接入前的主运行流程。优先把时间分段、观测时间步和气象驱动覆盖先跑顺。";
    className = "hint-box status-ok";
  } else if (!hourly && objectType === "interbasin_with_boundary") {
    text = "当前是“日尺度 + 区间流域”组合。最关键的是上游边界入流 CSV：时间步要和项目一致、覆盖预热到验证全时段、不能有重复时间戳。";
    className = "hint-box status-warn";
  } else if (hourly && objectType === "full_upstream_basin") {
    text = "当前是“小时尺度 + 完整上游流域”组合。洪水过程更细，但对气象驱动完整性更敏感，建议先在日尺度完成主流程核对，再扩大到小时尺度。";
    className = "hint-box status-warn";
  } else {
    text = "当前是“小时尺度 + 区间流域”组合，负载和输入要求都最高。建议先确认边界入流、小时气象驱动和时间分段都完全正确，再启动正式率定。";
    className = "hint-box status-warn";
  }
  host.textContent = text;
  host.className = className;
}

function updateBoundaryGuidance() {
  const host = $("#wz-boundary-guidance");
  if (!host) return;
  if (isFullUpstream()) {
    host.textContent = "当前流域工程类型为「完整上游流域」，本步通常可以跳过，不需要提供上游边界入流。";
    host.className = "hint-box";
    return;
  }
  const hourly = isHourlyTimescaleSelected();
  host.textContent = hourly
    ? "区间流域小时项目对边界入流最敏感。建议先确认 CSV 时间步为 1 小时、覆盖预热至验证全时段、零值不是误填缺测。"
    : "区间流域日尺度项目建议先确认边界入流为 24 小时间隔，并覆盖预热、率定、验证全时段；重复时间戳和负值要先清掉。";
  host.className = "hint-box status-warn";
}

function parseComparableTime(text) {
  const value = String(text || "").trim();
  if (!value) return null;
  const normalized = value.replace("T", " ");
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}))?/);
  if (!match) return null;
  return new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
    Number(match[4] || "0"),
    Number(match[5] || "0"),
    0,
    0,
  );
}

function formatComparableTime(date, hourly = isHourlyTimescaleSelected()) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "—";
  const yyyy = String(date.getFullYear()).padStart(4, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  if (!hourly) return `${yyyy}-${mm}-${dd}`;
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

function updateObservationHint() {
  const host = $("#wz-obs-hint");
  if (!host) return;
  const info = state.obsInfo;
  if (!info) {
    host.textContent = "选择观测径流文件后将自动推断时间范围。";
    host.className = "hint-box";
    return;
  }
  const selectedProfile = isHourlyTimescaleSelected() ? "hourly" : "daily";
  const timeBasis = $("#wz-time-basis")?.value || "continuous";
  const obsStart = parseComparableTime(info.start);
  const obsEnd = parseComparableTime(info.end);
  const issues = [];
  const warnings = [];
  const effectiveProfile = info.effective_calibration_mode || info.suggested_calibration_mode || "";
  if (effectiveProfile && effectiveProfile !== selectedProfile) {
    issues.push(`观测序列更像${info.suggested_calibration_mode === "hourly" ? "小时尺度" : "日尺度"}，和当前项目模式不一致。`);
  } else if (selectedProfile === "daily" && info.resampled_to_daily) {
    const minHours = info.daily_aggregation?.min_hours_per_day || 18;
    warnings.push(`当前项目为日尺度，系统会把小时观测按自然日聚合为日平均流量（至少 ${minHours} 小时/天）。`);
  }
  if (timeBasis === "event_windows") {
    warnings.push("当前按洪水事件窗口检查资料；观测覆盖将在第 7 步按各事件评分窗口核验。");
  }
  const periods = [
    { label: "率定期", start: getWizardTimeValue("#wz-calib-start"), end: getWizardTimeValue("#wz-calib-end") },
    { label: "验证期", start: getWizardTimeValue("#wz-valid-start"), end: getWizardTimeValue("#wz-valid-end") },
  ];
  if (timeBasis !== "event_windows") {
    periods.forEach(period => {
      const startTs = parseComparableTime(period.start);
      const endTs = parseComparableTime(period.end);
      if (!startTs || !endTs || !obsStart || !obsEnd) return;
      if (startTs < obsStart) {
        issues.push(`${period.label}开始早于观测起点（${formatComparableTime(startTs)} < ${formatComparableTime(obsStart)}）。`);
      }
      if (endTs > obsEnd) {
        issues.push(`${period.label}结束晚于观测终点（${formatComparableTime(endTs)} > ${formatComparableTime(obsEnd)}）。`);
      }
      const stepHours = selectedProfile === "hourly" ? 1 : 24;
      const steps = Math.round((endTs - startTs) / (stepHours * 3600000)) + 1;
      if (selectedProfile === "daily" && steps > 0 && steps < 180) {
        warnings.push(`${period.label}长度只有 ${steps} 天，正式率定通常建议至少半年以上。`);
      }
      if (selectedProfile === "hourly" && steps > 0 && steps < 24 * 30) {
        warnings.push(`${period.label}长度只有 ${steps} 小时，小时尺度正式率定通常建议至少 30 天以上。`);
      }
    });
  }
  const summary = `识别到时间列：${info.date_field}；覆盖范围：${info.start} → ${info.end}；原始序列：${info.suggested_calibration_mode === "hourly" ? "小时尺度" : "日尺度"}。`;
  if (issues.length) {
    host.innerHTML = `<strong>观测时段检查未通过。</strong><br>${escapeHtml(summary)}<ul>${issues.slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    host.className = "hint-box status-fail";
  } else if (warnings.length) {
    host.innerHTML = `<strong>观测时段检查通过，但建议继续优化。</strong><br>${escapeHtml(summary)}<ul>${warnings.slice(0, 3).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    host.className = "hint-box status-warn";
  } else {
    host.textContent = `${summary} 当前率定期和验证期都落在观测覆盖范围内。`;
    host.className = "hint-box status-ok";
  }
}

function updateEventModeHint() {
  const host = $("#wz-event-mode-hint");
  if (!host) return;
  clearWizardEventSummary();
  const basis = $("#wz-time-basis")?.value || "continuous";
  const eventFile = $("#wz-event-file")?.value.trim() || "";
  if (basis === "event_windows") {
    host.className = `hint-box ${eventFile ? "status-ok" : "status-warn"}`;
    host.textContent = eventFile
      ? "当前按洪水事件窗口组织资料。系统将按事件运行窗口检查气象强迫，按评分窗口检查观测流量；事件之间允许资料间断。"
      : "已选择洪水事件窗口，请提供事件表。事件表应包含运行开始、评分开始、评分结束、运行结束和用途等字段。";
  } else {
    host.className = "hint-box";
    host.textContent = "连续时段要求完整覆盖预热、率定和验证期；洪水事件窗口只要求每场事件内部资料连续。";
  }
}

function clearWizardEventSummary() {
  const host = $("#wz-event-file-summary");
  if (host) host.innerHTML = "";
}

function renderWizardEventSummary(eventInfo = null) {
  const host = $("#wz-event-file-summary");
  if (!host) return;
  if (!eventInfo || !window.HBVStudioEventMode?.renderEventWindowSummary) {
    host.innerHTML = "";
    return;
  }
  host.innerHTML = window.HBVStudioEventMode.renderEventWindowSummary(eventInfo, {
    escapeHtml,
    statusClass: focusStatusClass,
  });
}

function renderInputTimeSummary(summary = {}) {
  if (!summary || !summary.headline) return "";
  const status = String(summary.status || "ok").toLowerCase();
  const cls = status === "fail" ? "status-fail" : status === "warn" ? "status-warn" : "status-ok";
  const items = Array.isArray(summary.items) ? summary.items : [];
  const itemHtml = items.length
    ? `<div class="input-time-summary-items">${items.map(item => `
      <span><strong>${escapeHtml(item.label || "")}</strong>${escapeHtml(item.value || "—")}</span>
    `).join("")}</div>`
    : "";
  return `
    <div class="hint-box input-time-summary ${cls}" style="margin-bottom:12px">
      <strong>${escapeHtml(summary.headline)}</strong>
      ${summary.detail ? `<div class="input-time-summary-detail">${escapeHtml(summary.detail)}</div>` : ""}
      ${itemHtml}
    </div>
  `;
}

function clearBoundaryPreview() {
  const host = $("#wz-boundary-preview");
  if (host) host.innerHTML = "";
}

function taskLabelParts(task) {
  return String(task?.label || "").split("|").map(part => part.trim()).filter(Boolean);
}

function taskPrimaryTitle(task) {
  const parts = taskLabelParts(task);
  if (task?.task_type === "data_prep") return task.step_title || parts[1] || parts[0] || task.label || "数据准备";
  return parts[0] || task.label || taskTypeLabel(task?.task_type);
}

function taskContextSummary(task) {
  const parts = taskLabelParts(task);
  const bits = [];
  const workspace = task?.config_path ? workspaceLabelByPath(task.config_path) : "";
  if (workspace && workspace !== "未命名工作区") {
    bits.push(`工作区：${workspace}`);
  }
  if (task?.task_type === "forward_sim") {
    const sourceRunPath = String(task?.run_path || "").trim();
    const newRunPath = String(task?.result?.run_path || "").trim();
    const sourceLabel = parts[1] || shortPath(sourceRunPath) || "";
    if (sourceLabel) {
      bits.push(`源结果：${sourceLabel}`);
    }
    if (newRunPath && (!sourceRunPath || !samePath(newRunPath, sourceRunPath))) {
      bits.push(`新结果：${shortPath(newRunPath)}`);
    }
  } else if (parts.length > 1) {
    bits.push(parts.slice(1).join(" · "));
  }
  if (task?.profile) {
    bits.push(`模式：${profileLabel(task.profile)}`);
  }
  return bits.join(" · ");
}

function parseTaskTagLine(line) {
  const match = String(line || "").trim().match(/^\[([^\]]+)\]\s*(.*)$/);
  return match ? { tag: match[1].trim(), message: match[2].trim() } : null;
}

function cleanTaskLogMessage(line) {
  const tagged = parseTaskTagLine(line);
  return tagged ? tagged.message : String(line || "").trim();
}

function summarizeTaskLogMessage(line) {
  const tagged = parseTaskTagLine(line);
  let message = tagged ? tagged.message : String(line || "").trim();
  if (tagged && ["缓存写入", "缓存命中", "扫描", "导入", "校验"].includes(tagged.tag)) {
    message = `${tagged.tag}：${message}`;
  }
  message = message.replace(/(->\s*)([A-Za-z]:[\\/][^\s]+)$/i, (_, prefix, rawPath) => `${prefix}${shortPath(rawPath)}`);
  return message;
}

function taskLastMeaningfulLog(task) {
  const lines = (task?.output || []).map(line => String(line || "").trim()).filter(Boolean);
  return lines.length ? summarizeTaskLogMessage(lines[lines.length - 1]) : "";
}

function normalizeWorkflowStepTitle(text) {
  return String(text || "")
    .replace(/\s+返回码.*$/, "")
    .replace(/\s+已完成$/, "")
    .replace(/\s+\(手动步骤\).*$/, "")
    .trim();
}

function workflowTaskSnapshot(task) {
  const titles = Array.isArray(task?.step_titles) && task.step_titles.length
    ? task.step_titles.filter(Boolean)
    : (task?.step_title ? [task.step_title] : []);
  const statusMap = new Map(titles.map(title => [title, "pending"]));
  const runningLabels = new Set();
  let blockedMessage = "";
  let failedMessage = "";
  let stageMessage = String(task?.ui_progress?.stage || "").trim();

  (task?.output || []).forEach(line => {
    const tagged = parseTaskTagLine(line);
    if (!tagged) return;
    const title = normalizeWorkflowStepTitle(tagged.message);
    if (tagged.tag === "运行") {
      runningLabels.add(title);
      if (statusMap.has(title)) statusMap.set(title, "running");
    } else if (tagged.tag === "完成") {
      runningLabels.delete(title);
      if (statusMap.has(title)) statusMap.set(title, "completed");
    } else if (tagged.tag === "跳过") {
      runningLabels.delete(title);
      if (statusMap.has(title)) statusMap.set(title, "skipped");
    } else if (tagged.tag === "失败") {
      failedMessage = tagged.message;
      if (statusMap.has(title)) statusMap.set(title, "failed");
    } else if (tagged.tag === "阻塞") {
      blockedMessage = tagged.message;
    } else if (tagged.tag === "并行" || tagged.tag === "阶段") {
      stageMessage = tagged.message;
    }
  });

  if (task?.status === "completed") {
    [...statusMap.keys()].forEach(title => {
      if (statusMap.get(title) === "pending" || statusMap.get(title) === "running") {
        statusMap.set(title, "completed");
      }
    });
  } else if (task?.status === "failed") {
    runningLabels.forEach(title => {
      if (statusMap.has(title) && statusMap.get(title) !== "completed") {
        statusMap.set(title, "failed");
      }
    });
  }

  const entries = [...statusMap.entries()].map(([label, status]) => ({ label, status }));
  const finished = entries.filter(item => item.status === "completed" || item.status === "skipped").length;
  return {
    entries,
    finished,
    total: entries.length || Number(task?.ui_progress?.total || 0),
    runningLabels: [...runningLabels],
    blockedMessage,
    failedMessage,
    stageMessage,
  };
}

function calibrationStageSequence(task) {
  const method = String(task?.method || "").trim().toLowerCase();
  if (method === "mc_only") return ["mc"];
  const stages = method === "mc_screen_de" ? ["mc", "global"] : ["global"];
  if (Number(task?.refine_maxiter || 0) > 0) stages.push("refine");
  return stages;
}

function calibrationTaskStageEntries(task) {
  const stages = calibrationStageSequence(task);
  if (!stages.length) return [];
  const progressStages = task?.progress?.stages || {};
  const optimization = task?.result?.optimization || {};
  const resultStages = optimization?.stage_stats || {};
  const selectedResultStage = String(optimization?.selected_result_stage || "").trim().toLowerCase();
  const currentStage = String(task?.progress?.stage || stages[0]).trim().toLowerCase() || stages[0];
  const currentIndex = Math.max(0, stages.indexOf(currentStage));
  return stages.map((stage, idx) => {
    const stageInfo = progressStages?.[stage];
    const resultStage = resultStages?.[stage];
    let status = "pending";
    if (task?.status === "completed") {
      if (resultStage && typeof resultStage === "object") {
        if (resultStage.executed || resultStage.selected || selectedResultStage === stage || stageInfo) status = "completed";
        else if (resultStage.requested === false || resultStage.skipped_reason) status = "skipped";
        else if (idx > currentIndex) status = "skipped";
        else status = "completed";
      } else if (stageInfo) status = "completed";
      else if (idx > currentIndex) status = "skipped";
      else status = "completed";
    } else if (task?.status === "failed") {
      status = idx < currentIndex ? "completed" : idx === currentIndex ? "failed" : "pending";
    } else {
      status = idx < currentIndex ? "completed" : idx === currentIndex ? "running" : "pending";
    }
    return { label: taskStageLabel(stage), status, stage };
  });
}

function meteoImportStageEntries(task) {
  const stageText = String(task?.ui_progress?.stage || "");
  let phase = 0;
  if (/完成|校验/.test(stageText)) phase = 2;
  else if (/导入|复用/.test(stageText)) phase = 1;
  return ["目录扫描", "文件导入", "导入后检查"].map((label, idx) => {
    let status = "pending";
    if (task?.status === "completed") status = "completed";
    else if (task?.status === "failed") status = idx < phase ? "completed" : idx === phase ? "failed" : "pending";
    else status = idx < phase ? "completed" : idx === phase ? "running" : "pending";
    return { label, status };
  });
}

function forwardSimStageEntries(task) {
  const stageText = String(task?.ui_progress?.stage || "");
  let phase = 0;
  if (/整理结果|完成/.test(stageText)) phase = 4;
  else if (/写出手调结果|保存/.test(stageText)) phase = 3;
  else if (/计算|执行前向模拟/.test(stageText)) phase = 2;
  else if (/加载|命中缓存/.test(stageText)) phase = 1;
  return ["读取工程配置", "装载模型与驱动", "执行前向模拟", "写出结果目录", "整理结果元数据"].map((label, idx) => {
    let status = "pending";
    if (task?.status === "completed") status = "completed";
    else if (task?.status === "failed") status = idx < phase ? "completed" : idx === phase ? "failed" : "pending";
    else status = idx < phase ? "completed" : idx === phase ? "running" : "pending";
    return { label, status };
  });
}

function manualStartStageEntries(task) {
  const stageText = String(task?.ui_progress?.stage || "");
  let phase = 0;
  if (/整理结果|写出|完成/.test(stageText)) phase = 3;
  else if (/整理起调参数/.test(stageText)) phase = 2;
  else if (/加载|命中缓存/.test(stageText)) phase = 1;
  return ["读取工作区配置", "装载模型与驱动", "整理起调参数", "写出手调起点结果"].map((label, idx) => {
    let status = "pending";
    if (task?.status === "completed") status = "completed";
    else if (task?.status === "failed") status = idx < phase ? "completed" : idx === phase ? "failed" : "pending";
    else status = idx < phase ? "completed" : idx === phase ? "running" : "pending";
    return { label, status };
  });
}

function forecastRestartStageEntries(task) {
  const stageText = String(task?.ui_progress?.stage || "");
  let phase = 0;
  if (/预报完成|完成/.test(stageText)) phase = 12;
  else if (/生成预报元数据|元数据/.test(stageText)) phase = 11;
  else if (/写出/.test(stageText)) phase = 10;
  else if (/执行连续状态预报/.test(stageText)) phase = 9;
  else if (/整理参数/.test(stageText)) phase = 8;
  else if (/加载未来气象|加载模型数据|地理数据/.test(stageText)) phase = 7;
  else if (/归档预报气象|归档/.test(stageText)) phase = 6;
  else if (/检查预报气象|时间覆盖/.test(stageText)) phase = 5;
  else if (/检查预报时段|连续性/.test(stageText)) phase = 4;
  else if (/加载 HBV|加载模型|核心/.test(stageText)) phase = 3;
  else if (/源结果参数/.test(stageText)) phase = 2;
  else if (/状态快照|源状态/.test(stageText)) phase = 1;
  return ["读取源结果", "读取状态", "读取参数", "加载模型", "检查起报", "检查气象", "归档气象", "加载数据", "整理起报", "执行预报", "写出结果", "生成元数据", "完成"].map((label, idx) => {
    let status = "pending";
    if (task?.status === "completed") status = "completed";
    else if (task?.status === "failed") status = idx < phase ? "completed" : idx === phase ? "failed" : "pending";
    else status = idx < phase ? "completed" : idx === phase ? "running" : "pending";
    return { label, status };
  });
}

function taskMilestoneEntries(task) {
  if (task?.task_type === "calibration") return calibrationTaskStageEntries(task);
  if (task?.task_type === "bootstrap" || task?.task_type === "data_prep") return workflowTaskSnapshot(task).entries;
  if (task?.task_type === "meteo_import") return meteoImportStageEntries(task);
  if (task?.task_type === "manual_start") return manualStartStageEntries(task);
  if (task?.task_type === "forward_sim") return forwardSimStageEntries(task);
  if (task?.task_type === "forecast_restart") return forecastRestartStageEntries(task);
  return [];
}

function renderTaskMilestones(task) {
  const entries = taskMilestoneEntries(task);
  if (!entries.length) return "";
  return `
    <div class="task-chip-row">
      ${entries.map(item => `<span class="task-chip is-${escapeHtml(item.status || "pending")}">${escapeHtml(item.label || "")}</span>`).join("")}
    </div>
  `;
}

function calibrationTaskSummary(task) {
  const progress = task?.progress;
  if (task?.status === "completed") {
    const result = task?.result || {};
    const optimization = result.optimization || {};
    const parts = [
      task?.detected_runs?.length
        ? `率定完成，已生成 ${task.detected_runs.length} 个结果目录`
        : "率定已完成",
    ];
    const selectedLabel = optimizationResultLabel(optimization);
    if (selectedLabel) parts.push(`最终采用${selectedLabel}`);
    if (optimization?.stage_stats?.refine?.requested || optimization?.polish) {
      parts.push(`局部精修：${optimizationRefineSummary(optimization)}`);
    }
    const metricParts = [];
    if (result?.metrics?.nse_cal !== undefined && result?.metrics?.nse_cal !== null) {
      metricParts.push(`率定纳什效率系数 ${formatNumber(result.metrics.nse_cal, 4)}`);
    }
    if (result?.metrics?.nse_val !== undefined && result?.metrics?.nse_val !== null) {
      metricParts.push(`验证纳什效率系数 ${formatNumber(result.metrics.nse_val, 4)}`);
    }
    if (metricParts.length) parts.push(metricParts.join("，"));
    return parts.join(" · ");
  }
  if (task?.status === "failed") {
    return taskLastMeaningfulLog(task) || "率定任务失败。";
  }
  if (progress) {
    const stepText = progress.maxiter ? `第 ${progress.gen}/${progress.maxiter} 步` : `第 ${progress.gen || "—"} 步`;
    const timeText = `已耗时 ${formatDurationSeconds(progress.elapsed_sec)}${progress.eta_sec !== null && progress.eta_sec !== undefined ? `，预计剩余 ${formatDurationSeconds(progress.eta_sec)}` : ""}`;
    return `${taskStageLabel(progress.stage || "global")} · ${stepText} · 率定纳什效率系数 ${formatNumber(progress.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(progress.nse_val, 4)}，综合评分值 ${formatNumber(progress.obj, 4)} · ${timeText}`;
  }
  return taskLastMeaningfulLog(task) || task?.ui_progress?.label || task?.ui_progress?.stage || "率定任务已启动，正在加载模型与驱动，首个进度点尚未写出。";
}

function workflowTaskSummary(task) {
  const snapshot = workflowTaskSnapshot(task);
  if (task?.status === "failed") {
    return taskLastMeaningfulLog(task) || snapshot.failedMessage || "任务执行失败。";
  }
  if (task?.status === "completed") {
    return snapshot.total ? `已完成 ${snapshot.finished || snapshot.total}/${snapshot.total} 个步骤。` : "任务已完成。";
  }
  if (snapshot.blockedMessage) return snapshot.blockedMessage;
  if (snapshot.runningLabels.length > 1) {
    return `正在并行执行 ${snapshot.runningLabels.length} 个步骤，已完成 ${snapshot.finished}/${snapshot.total || "—"}。`;
  }
  if (snapshot.runningLabels[0]) {
    return `正在执行 ${snapshot.runningLabels[0]}，已完成 ${snapshot.finished}/${snapshot.total || "—"}。`;
  }
  if (task?.ui_progress?.label) {
    return `${task.ui_progress.stage || "正在执行"}：${task.ui_progress.label}`;
  }
  return taskLastMeaningfulLog(task) || "任务已创建，正在等待脚本输出。";
}

function meteoImportTaskSummary(task) {
  const progress = task?.ui_progress || {};
  if (task?.status === "running") {
    const lastLog = taskLastMeaningfulLog(task);
    const total = Number(progress.total || 0);
    const current = Number(progress.current || 0);
    const label = progress.label || "导入";
    const itemCurrent = Number(progress.item_current || 0);
    const itemTotal = Number(progress.item_total || 0);
    const ts = progress.timestamp ? `，当前时间 ${progress.timestamp}` : "";
    if (lastLog) {
      return `${progress.stage || "正在导入"}：${lastLog}`;
    }
    return total > 0
      ? `${progress.stage || "正在导入"}：总进度 ${current}/${total}；${label} ${itemCurrent}/${itemTotal}${ts}`
      : (progress.stage || "正在准备导入，请稍候...");
  }
  if (task?.status === "completed") {
    const result = task?.result || {};
    const issues = [...(result.validation_errors || []), ...(result.validation_warnings || [])];
    const tail = result.validation_ok ? "导入后检查通过。" : `仍需继续检查：${issues.slice(0, 2).join("；") || "请到第 7 步继续检查。"} `;
    return `已导入降水 ${result.prec_count || 0}、气温 ${result.temp_count || 0}、蒸散 ${result.evap_count || 0} 个文件；${result.aligned ? "网格已一致。" : "已自动裁剪对齐到 DEM 网格。"}${tail}`;
  }
  return taskLastMeaningfulLog(task) || "气象导入失败。";
}

function forwardSimTaskSummary(task) {
  if (task?.status === "running") {
    const stage = task?.ui_progress?.stage || "正在保存并重算当前结果。";
    const lastLog = taskLastMeaningfulLog(task);
    return lastLog && lastLog !== stage ? `${stage} · ${lastLog}` : stage;
  }
  if (task?.status === "completed" && task?.result) {
    const metrics = task.result.metrics || {};
    return task.result.run_path
      ? `手调结果已保存：率定纳什效率系数 ${formatNumber(metrics.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(metrics.nse_val, 4)}。`
      : `结果重算完成：率定纳什效率系数 ${formatNumber(metrics.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(metrics.nse_val, 4)}。`;
  }
  return taskLastMeaningfulLog(task) || "保存并重算失败。";
}

function manualStartTaskSummary(task) {
  if (task?.status === "running") {
    const stage = task?.ui_progress?.stage || "正在生成手调起点。";
    const lastLog = taskLastMeaningfulLog(task);
    if (lastLog && lastLog !== stage) return `${stage} · ${lastLog}`;
    if (/加载气象与地理数据/.test(stage)) {
      return `${stage} · 首次运行通常会先写出 prec/temp/evap 缓存，请耐心等待。`;
    }
    return stage;
  }
  if (task?.status === "completed" && task?.result) {
    const metrics = task.result.metrics || {};
    return `手调起点已生成：率定纳什效率系数 ${formatNumber(metrics.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(metrics.nse_val, 4)}。`;
  }
  return taskLastMeaningfulLog(task) || "手调起点生成失败。";
}

function forecastRestartTaskSummary(task) {
  if (task?.status === "running") {
    const stage = task?.ui_progress?.stage || "正在执行连续状态预报。";
    const lastLog = taskLastMeaningfulLog(task);
    return lastLog && lastLog !== stage ? `${stage} · ${lastLog}` : stage;
  }
  if (task?.status === "completed" && task?.result) {
    const result = task.result || {};
    const meta = result.metadata?.forecast_result || {};
    const range = meta.forecast_start && meta.forecast_end ? `${meta.forecast_start} 至 ${meta.forecast_end}` : "未来时段";
    return result.run_path ? `连续状态预报已生成：${range}。` : "连续状态预报已完成。";
  }
  return taskLastMeaningfulLog(task) || "连续状态预报失败。";
}

function selfCheckTaskSummary(task) {
  if (task?.status === "running") {
    return task?.ui_progress?.stage || "正在检查本地环境、脚本与关键依赖。";
  }
  if (task?.status === "completed") return "系统自检完成。";
  return taskLastMeaningfulLog(task) || "系统自检失败。";
}

function taskSummaryLine(task) {
  if (task?.task_type === "calibration") return calibrationTaskSummary(task);
  if (task?.task_type === "bootstrap" || task?.task_type === "data_prep") return workflowTaskSummary(task);
  if (task?.task_type === "meteo_import") return meteoImportTaskSummary(task);
  if (task?.task_type === "manual_start") return manualStartTaskSummary(task);
  if (task?.task_type === "forward_sim") return forwardSimTaskSummary(task);
  if (task?.task_type === "forecast_restart") return forecastRestartTaskSummary(task);
  if (task?.task_type === "self_check") return selfCheckTaskSummary(task);
  if (task?.status === "completed") return "任务已完成。";
  if (task?.status === "failed") return taskLastMeaningfulLog(task) || "任务失败。";
  return taskLastMeaningfulLog(task) || "任务已创建，等待输出。";
}

function renderTaskActions(task) {
  const buttons = [];
  if (task?.config_path && !["calibration", "forward_sim"].includes(String(task?.task_type || ""))) {
    buttons.push(`<button class="ghost-button" data-task-open-workspace="${escapeHtml(task.config_path)}">查看向导</button>`);
  }
  if (task?.task_type === "forward_sim") {
    const sourceRunPath = String(task?.run_path || "").trim();
    const newRunPath = String(task?.result?.run_path || "").trim();
    const hasDistinctNewRun = Boolean(newRunPath && sourceRunPath && !samePath(newRunPath, sourceRunPath));
    const primaryRunPath = newRunPath || sourceRunPath;
    if (primaryRunPath) {
      buttons.push(`<button class="ghost-button" data-task-open-result="${escapeHtml(primaryRunPath)}">${hasDistinctNewRun ? "查看新结果" : "查看结果"}</button>`);
      buttons.push(`<button class="ghost-button" data-task-open-run-dir="${escapeHtml(primaryRunPath)}">${hasDistinctNewRun ? "打开新结果目录" : "打开结果目录"}</button>`);
    }
    if (hasDistinctNewRun) {
      buttons.push(`<button class="ghost-button" data-task-open-result="${escapeHtml(sourceRunPath)}">查看源结果</button>`);
      buttons.push(`<button class="ghost-button" data-task-open-run-dir="${escapeHtml(sourceRunPath)}">打开源结果目录</button>`);
    }
  } else {
    const runPath = task?.result?.run_path || task?.detected_runs?.[0] || task?.run_path || "";
    if (runPath) {
      buttons.push(`<button class="ghost-button" data-task-open-result="${escapeHtml(runPath)}">查看结果</button>`);
      buttons.push(`<button class="ghost-button" data-task-open-run-dir="${escapeHtml(runPath)}">打开结果目录</button>`);
    }
  }
  return buttons.length ? `<div class="workspace-card-actions task-actions">${buttons.join("")}</div>` : "";
}

function taskDebugDetails(task, { lines = 80 } = {}) {
  const output = (task?.output || []);
  if (!output.length) return "";
  const shownLines = output.slice(-lines);
  const rememberedOpen = Boolean(state.taskDebugOpen?.[task.id]);
  const openAttr = (task?.status === "failed" || rememberedOpen) ? " open" : "";
  return `
    <details class="task-debug-details" data-task-debug-id="${escapeHtml(task.id)}"${openAttr}>
      <summary class="task-debug-summary">运行日志（最近 ${shownLines.length} 行）</summary>
      <div class="task-debug-actions">
        <button class="ghost-button" data-copy-task-log="${escapeHtml(task.id)}">复制日志</button>
      </div>
      <pre class="task-log" data-log-key="task:${escapeHtml(task.id)}" data-log-default-stick-bottom="${task?.status === "running" ? "1" : "0"}" tabindex="0">${escapeHtml(shownLines.join("\n"))}</pre>
    </details>
  `;
}

function dataPathAlias(path, fallback = "—") {
  const alias = directoryAliasLabel(path || "");
  if (alias) return alias;
  return shortPath(path) || fallback;
}

function dataCacheSummary(meta) {
  const cache = meta?.data_cache || {};
  const items = ["prec", "temp", "evap"].filter(key => cache[key]);
  if (!items.length) return "未记录";
  const exactHits = items.filter(key => cache[key]?.cache_hit && (!cache[key]?.cache_hit_type || cache[key]?.cache_hit_type === "exact")).length;
  const coveringHits = items.filter(key => cache[key]?.cache_hit && cache[key]?.cache_hit_type === "covering_slice").length;
  const hits = exactHits + coveringHits;
  if (!hits) return `已建缓存 ${items.length} 项`;
  if (coveringHits > 0) return `已复用 ${hits}/${items.length}（精确 ${exactHits} · 切片 ${coveringHits}）`;
  return `已复用 ${hits}/${items.length}`;
}

function glacierModuleSummary(meta) {
  const glacier = meta?.optional_modules?.glacier || {};
  if (!glacier.enabled) {
    return glacier.mask_exists === false ? "关闭（未生成冰川掩膜）" : "关闭";
  }
  return glacier.reference_available ? "开启 · 已提供参考场" : "开启";
}

function boundaryModuleSummary(meta) {
  return meta?.optional_modules?.boundary_inflow?.enabled ? "开启" : "关闭";
}


function boundaryEnabledFromMeta(meta) {
  return Boolean(
    meta?.project_object_type === "interbasin_with_boundary"
    || meta?.optional_modules?.boundary_inflow?.enabled
    || meta?.boundary_condition?.enabled
    || meta?.boundary_condition?.boundary_inflow_file
  );
}


function replayCompatibilityInfo(meta) {
  const replay = meta?.replay_context || {};
  const obsReplay = Boolean(replay.obs_replayed_from_source_run);
  const boundaryReplay = Boolean(replay.boundary_replayed_from_source_run);
  if (!obsReplay && !boundaryReplay) {
    return {
      value: "未启用",
      detail: "当前结果直接使用现工作区输入",
      obsReplay: false,
      boundaryReplay: false,
    };
  }
  const labels = [];
  const details = [];
  if (obsReplay) {
    labels.push("观测回放");
    details.push("观测序列来自源结果");
  }
  if (boundaryReplay) {
    labels.push("边界回放");
    details.push("上游边界沿用源结果已汇流序列");
  }
  if (replay.source_run_path) {
    details.push(`源结果 ${shortPath(replay.source_run_path)}`);
  }
  return {
    value: labels.join(" + "),
    detail: details.join("；"),
    obsReplay,
    boundaryReplay,
  };
}


function optimizationResultLabel(optimization) {
  const stage = String(optimization?.selected_result_stage || "").trim().toLowerCase();
  if (stage === "global") return optimization?.polish ? "精细搜索结果（含末端精修）" : "精细搜索结果";
  if (stage === "refine") return "局部精修结果";
  if (stage === "mc") return "快速筛选结果";
  return String(optimization?.selected_result_label || "").trim();
}

function optimizationRefineSummary(optimization) {
  const refine = optimization?.stage_stats?.refine;
  if (!refine?.requested) {
    if (optimization?.polish) return "未启用独立局部精修，仅执行全局末端精修（polish）";
    return "未启用";
  }
  if (refine?.valid) {
    const nit = Number(refine.nit || 0);
    return nit > 0 ? `已执行（${nit} 代）` : "已执行";
  }
  if (String(refine?.skipped_reason || "").trim().toLowerCase() === "global_result_invalid") {
    return "已跳过（全局阶段结果无效）";
  }
  if (refine && refine.success === false) return "执行失败";
  return "未产出有效结果";
}

function optimizationPolishSummary(optimization) {
  if (!optimization) return "未记录";
  if (optimization.polish) {
    return optimization.requested_polish ? "已启用（显式请求）" : "已启用（单线程自动开启）";
  }
  if (optimization.requested_polish) return "请求启用但未生效";
  return "未启用";
}

function optimizationSummary(meta) {
  const optimization = meta?.optimization || {};
  const parts = [optimizationMethodLabel(optimization)];
  if (Number(optimization.debug_days || 0) > 0) parts.push(`辅助计算窗口 ${optimization.debug_days} 天`);
  if (String(optimization.method || "").trim().toLowerCase() !== "de" && Number(optimization.mc_samples || 0) > 0) {
    parts.push(`随机样本 ${optimization.mc_samples}`);
  }
  if (String(optimization.method || "").trim().toLowerCase() !== "mc_only" && Number(optimization.maxiter || 0) > 0) {
    parts.push(`最大迭代 ${optimization.maxiter}`);
  }
  if (Number(optimization.workers || 0) > 0) parts.push(`线程 ${optimization.workers}`);
  if (optimizationResultLabel(optimization)) parts.push(`最终采用 ${optimizationResultLabel(optimization)}`);
  if (optimization.objective_value !== undefined && optimization.objective_value !== null) {
    parts.push(`综合评分值 ${formatNumber(optimization.objective_value, 4)}`);
  }
  if (Number(optimization.selected_stage_evaluations || 0) > 0) {
    parts.push(`最终阶段评估 ${optimization.selected_stage_evaluations}`);
  }
  const refineSummary = optimizationRefineSummary(optimization);
  if (optimization?.stage_stats?.refine?.requested) {
    parts.push(`局部精修 ${refineSummary}`);
  } else if (optimization.polish) {
    parts.push("全局末端精修（polish）");
  }
  return parts.filter(Boolean).join(" · ");
}

function runPrecipSummary(meta) {
  const sources = meta?.data_sources || {};
  const runtimeSource = String(sources.runtime_prec_source || sources.prec_source || sources.configured_precip_source || "").trim().toLowerCase();
  const sourceLabel = getConfiguredPrecipSourceLabel(runtimeSource || "era5");
  const directoryLabel = sources.prec_dir ? dataPathAlias(sources.prec_dir) : getRuntimePrecipDirectoryLabel(runtimeSource || "era5");
  return `${sourceLabel} · ${directoryLabel}`;
}

function finiteSeriesStats(values) {
  const arr = Array.isArray(values) ? values : [];
  let sum = 0;
  let count = 0;
  let nonzero = 0;
  for (const raw of arr) {
    const value = Number(raw);
    if (!Number.isFinite(value)) continue;
    count += 1;
    sum += value;
    if (Math.abs(value) > 1e-12) nonzero += 1;
  }
  return { sum, count, nonzero };
}

function ratioValue(numerator, denominator) {
  const num = Number(numerator);
  const den = Number(denominator);
  if (!Number.isFinite(num) || !Number.isFinite(den) || Math.abs(den) <= 1e-12) return null;
  return num / den;
}

function formatPercentValue(value, digits = 1) {
  const num = Number(value);
  return Number.isFinite(num) ? `${(num * 100).toFixed(digits)}%` : "—";
}

function componentFractionReport(meta = {}) {
  return meta?.diagnostics?.component_fraction_report || {};
}

function componentFractionText(report = {}) {
  const values = [
    ["降雨", report.rain_fraction],
    ["融雪", report.snow_fraction],
    ["融冰", report.ice_fraction],
  ];
  if (!values.some(([, value]) => Number.isFinite(Number(value)))) return "未记录";
  return values.map(([label, value]) => `${label} ${formatPercentValue(value)}`).join(" / ");
}

function componentFractionBasisText(report = {}) {
  const basis = String(report.evaluation_period || "").trim();
  if (basis === "local_runoff_calibration_period") {
    return "率定期本地径流口径，不含上游边界入流";
  }
  if (basis === "total_runoff_calibration_period" || basis === "calibration_period") {
    return "率定期模拟总流量口径";
  }
  return "率定期模拟径流口径";
}

function glacierFractionReport(meta) {
  return meta?.diagnostics?.glacier_fraction_report
    || meta?.optional_modules?.glacier?.fraction_report
    || meta?.glacier_fraction_report
    || {};
}

function glacierFractionValue(report) {
  const raw = report?.f_ice ?? report?.result?.f_ice;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function wideIceGuardUpper(report) {
  const window = Array.isArray(report?.window) ? report.window : [];
  const upper = Number(window[1]);
  if (Number.isFinite(upper) && upper > 0) return Math.max(0.35, Math.min(0.60, upper * 1.30));
  return 0.35;
}

function analyzeIceContribution(data) {
  const meta = data?.metadata || {};
  const series = data?.series || {};
  const glacier = meta?.optional_modules?.glacier || {};
  const enabled = Boolean(glacier.enabled);
  const qIce = finiteSeriesStats(series.q_ice);
  const qTotal = finiteSeriesStats(series.q_total || series.q_sim);
  const qLocal = finiteSeriesStats(series.q_local);
  const qRain = finiteSeriesStats(series.q_rain);
  const qSnow = finiteSeriesStats(series.q_snow);
  const fracReport = glacierFractionReport(meta);
  const fIce = glacierFractionValue(fracReport);
  const guard = meta?.objective_terms?.cryo_consistency?.ice_dominance_guard || {};
  const qIceToTotal = ratioValue(qIce.sum, qTotal.sum);
  const qIceToLocal = ratioValue(qIce.sum, qLocal.sum);
  const qRainToTotal = ratioValue(qRain.sum, qTotal.sum);
  const qSnowToTotal = ratioValue(qSnow.sum, qTotal.sum);
  let stateLabel = "not_applicable_no_glacier";
  let message = "当前工作区未启用冰川模块。";
  if (enabled && qIce.count <= 0) {
    stateLabel = "missing_q_ice";
    message = "冰川模块已启用，但结果文件缺少裸冰融化流量，需要复核结果输出。";
  } else if (enabled && qIce.nonzero <= 0) {
    stateLabel = "zero_q_ice";
    message = "裸冰融化流量存在但全零，可能是该时段无有效融冰或冰川输入未产生贡献。";
  } else if (enabled) {
    stateLabel = "valid_q_ice";
    message = "裸冰融化流量已产生有效非零序列。";
  }
  return {
    enabled,
    state: stateLabel,
    message,
    qIce,
    qTotal,
    qLocal,
    qRain,
    qSnow,
    qIceToTotal,
    qIceToLocal,
    qRainToTotal,
    qSnowToTotal,
    fracReport,
    fIce,
    guard,
    guardPenalty: Number(guard?.penalty || 0),
    guardUpper: Number.isFinite(Number(guard?.upper)) ? Number(guard.upper) : wideIceGuardUpper(fracReport),
  };
}

function iceContributionDetailText(analysis) {
  if (!analysis.enabled || analysis.state !== "valid_q_ice") return analysis.message;
  return [
    `降雨产流占模拟总流量 ${formatPercentValue(analysis.qRainToTotal)}`,
    `融雪径流占模拟总流量 ${formatPercentValue(analysis.qSnowToTotal)}`,
    `裸冰融化占模拟总流量 ${formatPercentValue(analysis.qIceToTotal)}`,
  ].join(" · ");
}

function formatMetricValue(value, digits = 4, suffix = "") {
  const num = Number(value);
  return Number.isFinite(num) ? `${formatNumber(num, digits)}${suffix}` : "—";
}

function metadataItem(label, value, detail = "") {
  return `
    <div class="list-item metadata-list-item">
      <strong>${escapeHtml(label)}</strong>
      <small>${escapeHtml(value === undefined || value === null || value === "" ? "—" : String(value))}</small>
      ${detail ? `<em>${escapeHtml(detail)}</em>` : ""}
    </div>
  `;
}

function metadataSection(title, rows) {
  const content = rows.map(row => metadataItem(row[0], row[1], row[2])).join("");
  return `
    <section class="metadata-section">
      <h4>${escapeHtml(title)}</h4>
      <div class="metadata-section-grid">${content}</div>
    </section>
  `;
}

function floodEventEvaluation(meta = {}) {
  return meta?.flood_event_evaluation || meta?.diagnostics?.flood_event_evaluation || {};
}

function floodEventStatusText(evaluation = {}) {
  if (!evaluation?.enabled) return "未启用";
  const valid = Number(evaluation.valid_event_count || 0);
  const total = Number(evaluation.event_count || 0);
  const mode = evaluation.objective_enabled ? "事件目标函数" : "事件诊断";
  return `${mode}：${valid}/${total} 场有效`;
}

function floodEventObjectiveText(evaluation = {}) {
  const score = evaluation?.summary?.all?.mean_diagnostic_objective;
  return Number.isFinite(Number(score)) ? formatNumber(score, 4) : "—";
}

function floodEventRows(meta = {}) {
  const evaluation = floodEventEvaluation(meta);
  if (!evaluation?.enabled) return [];
  const rows = [
    ["事件评价", floodEventStatusText(evaluation), `评价口径：${evaluation.evaluation_basis || "模拟流量"}`],
    ["事件目标值", floodEventObjectiveText(evaluation), evaluation.objective_enabled ? "数值越小表示事件综合偏差越小" : "当前为诊断值，不参与本次优化"],
  ];
  const eventMode = meta?.event_mode || meta?.time_config?.event_runtime || {};
  if (eventMode?.enabled) {
    const modeText = eventMode.runtime_mode === "independent_event_windows" ? "事件窗口独立运行" : "事件窗口资料";
    const stateText = eventMode.state_continuity_between_events === false ? "事件之间不传递状态" : "按配置处理事件间状态";
    rows.push([
      "事件资料模式",
      `${modeText}，${Number(eventMode.event_count || 0)} 场`,
      `${stateText}；初始条件：${eventMode.initial_state_policy || "event_warmup"}`,
    ]);
  }
  const events = Array.isArray(evaluation.events) ? evaluation.events : [];
  events.slice(0, 12).forEach(event => {
    const name = event?.name || "未命名事件";
    const value = [
      `洪峰 ${formatMetricValue(event?.peak_error_percent, 2, "%")}`,
      `峰现 ${formatMetricValue(event?.peak_time_error_hours, 1, " h")}`,
      `洪量 ${formatMetricValue(event?.volume_error_percent, 2, "%")}`,
    ].join(" / ");
    const detail = [
      `NSE ${formatMetricValue(event?.nse, 4)}`,
      `KGE ${formatMetricValue(event?.kge, 4)}`,
      `高流量NSE ${formatMetricValue(event?.high_flow_weighted_nse, 4)}`,
      `高流量KGE ${formatMetricValue(event?.high_flow_kge, 4)}`,
      `退水 ${formatMetricValue(event?.recession_slope_error_percent, 2, "%")}`,
    ].join("，");
    rows.push([String(name), value, `${event?.used_in_objective ? "参与目标函数" : "诊断事件"}；${detail}`]);
  });
  if (events.length > 12) {
    rows.push(["更多事件", `还有 ${events.length - 12} 场`, "完整事件表见结果目录 flood_events.csv"]);
  }
  return rows;
}

function renderFloodEventChart(meta = {}, plotCfg = {}) {
  if (window.HBVStudioEventMode?.renderFloodEventChart) {
    window.HBVStudioEventMode.renderFloodEventChart(meta, plotCfg, { finiteNumber, formatMetricValue });
  }
}

function forecastArchiveManifest(archive = {}) {
  return archive?.manifest || {};
}

function forecastArchiveVariables(archive = {}) {
  return forecastArchiveManifest(archive).variables || archive?.variables || {};
}

function forecastArchiveVariableItems(archive = {}) {
  const manifest = forecastArchiveManifest(archive);
  const variables = forecastArchiveVariables(archive);
  const labels = { prec: "降水", temp: "气温", evap: "潜在蒸散发" };
  return ["prec", "temp", "evap"].map(key => {
    const item = variables?.[key] || {};
    if (!item || !Object.keys(item).length) return null;
    const label = item.label || labels[key] || key;
    const expected = Number(item.expected_steps ?? manifest.expected_steps ?? 0);
    const archived = Number(item.archived_files ?? item.file_count ?? 0);
    const outside = Number(item.out_of_window_files ?? 0);
    const value = expected > 0
      ? `${archived || 0}/${expected} 个时步`
      : archived > 0 ? `${archived} 个文件` : "已归档";
    const detailParts = [];
    if (item.first_time || item.last_time) detailParts.push(`时段：${timeRangeText(item.first_time, item.last_time)}`);
    if (outside > 0) detailParts.push(`窗口外 ${outside} 个文件未纳入`);
    if (item.archive_dir) detailParts.push(`归档：${shortPath(item.archive_dir)}`);
    return { key, label, value, detail: detailParts.join("；") || "已纳入本次预报计算" };
  }).filter(Boolean);
}

function forecastArchiveSummaryText(archive = {}, fallback = "未记录预报气象归档") {
  const manifest = forecastArchiveManifest(archive);
  const items = forecastArchiveVariableItems(archive);
  if (!archive?.manifest_path && !items.length) return fallback;
  const expected = Number(manifest.expected_steps || items[0]?.value?.match(/\d+\/(\d+)/)?.[1] || 0);
  if (expected > 0) return `已归档 ${expected} 个预报时步`;
  return "已归档预报气象";
}

function forecastArchiveDetailText(archive = {}, fallback = "预报完成后将归档实际使用的降水、气温和潜在蒸散发栅格") {
  const items = forecastArchiveVariableItems(archive);
  if (!archive?.manifest_path && !items.length) return fallback;
  const manifest = forecastArchiveManifest(archive);
  const parts = [];
  if (manifest.forecast_start || manifest.forecast_end) {
    parts.push(`窗口：${timeRangeText(manifest.forecast_start, manifest.forecast_end)}`);
  }
  if (items.length) {
    parts.push(items.map(item => `${item.label}${item.value}`).join("，"));
  }
  if (archive?.manifest_path) {
    parts.push(`清单：${shortPath(archive.manifest_path)}`);
  }
  return parts.join("；") || "已保存本次预报实际使用的气象输入";
}

function forecastParameterSourceSummary(source = {}, fallback = {}) {
  const params = fallback?.optimized_params || {};
  const count = Number(source.parameter_count ?? fallback.optimized_param_count ?? (params && typeof params === "object" ? Object.keys(params).length : 0));
  const label = source.parameter_source_label || "源结果参数";
  const objectiveRaw = source.objective_mode || fallback.effective_objective_mode || fallback.objective_family || fallback.recorded_objective_family || "";
  const objective = objectiveRaw ? objectiveLabel(objectiveRaw) : "";
  const profile = source.calibration_profile || fallback.calibration_profile || "";
  const sourceName = source.source_run_name || fallback.source_run_name || "";
  const detailParts = [];
  if (sourceName) detailParts.push(`来源结果：${sourceName}`);
  if (profile) detailParts.push(profileLabel(profile));
  if (objective) detailParts.push(`目标函数：${objective}`);
  if (source.state_snapshot_time) detailParts.push(`状态时刻：${source.state_snapshot_time}`);
  return {
    value: `${label}${count > 0 ? `（${count} 项）` : ""}`,
    detail: detailParts.join("；") || "读取源结果保存的最优参数，不重新率定",
  };
}

function restartStateRows(meta = {}) {
  const initial = meta?.initial_state || {};
  const forecast = meta?.forecast_result || {};
  const rows = [];
  if (initial?.state_snapshot_available || initial?.hot_start_supported || forecast?.enabled) {
    rows.push([
      "状态热启动",
      initial?.hot_start_enabled || forecast?.enabled ? "可用" : "未启用",
      initial?.state_snapshot_file ? `状态文件：${initial.state_snapshot_file}` : "当前结果未记录状态文件",
    ]);
    rows.push([
      "状态时刻",
      initial?.state_snapshot_time || forecast?.forecast_end || "—",
      initial?.state_snapshot_routing_state ? "包含汇流上一时刻记忆" : "未记录汇流记忆",
    ]);
  }
  if (forecast?.enabled) {
    rows.push([
      "预报来源",
      forecast?.source_run_name || "源结果",
      forecast?.source_run_path ? shortPath(forecast.source_run_path) : "读取源结果参数与状态快照",
    ]);
    const parameterSource = forecastParameterSourceSummary(
      forecast?.source_parameter_summary || meta?.source_parameter_summary || {},
      meta,
    );
    rows.push([
      "参数来源",
      parameterSource.value,
      parameterSource.detail,
    ]);
    rows.push([
      "预报时段",
      timeRangeText(forecast?.forecast_start, forecast?.forecast_end, meta?.time_config?.time_step_hours || 24),
      "不重新率定参数，直接接续未来气象输入",
    ]);
    const archive = forecast?.forecast_input_archive || meta?.data_sources?.forecast_input_archive || {};
    rows.push([
      "预报气象",
      forecastArchiveSummaryText(archive),
      forecastArchiveDetailText(archive),
    ]);
    forecastArchiveVariableItems(archive).forEach(item => {
      rows.push([
        item.label,
        item.value,
        item.detail,
      ]);
    });
  }
  return rows;
}

function hydrologySummaryFor(data = {}, meta = null) {
  const metadata = meta || data?.metadata || {};
  return data?.hydrology_summary || data?.run?.hydrology_summary || metadata?.hydrology_summary || {};
}

function hydrologySummaryValue(summary, key, fallback = "—") {
  const value = summary?.[key];
  return value === undefined || value === null || value === "" ? fallback : String(value);
}

function renderRunEngineeringSummary(data) {
  const host = $("#run-engineering-summary");
  const actions = $("#run-engineering-actions");
  const note = $("#run-engineering-note");
  if (!host || !actions || !note) return;
  const meta = data?.metadata || {};
  const summary = hydrologySummaryFor(data, meta);
  const editable = isStudioEditableRun(data);
  const manual = Boolean(meta?.manual_result?.enabled);
  const starter = Boolean(meta?.starter_result?.enabled);
  const workspaceConfig = meta.workspace_config || data?.run?.workspace_config || "";
  const replayInfo = replayCompatibilityInfo(meta);
  const reliabilityFlag = String(meta?.reliability_flag || "ok").trim();
  const isDegraded = reliabilityFlag !== "ok";
  const reportPath = summary.diagnostics_detail_path || summary.diagnostics_detail_display_path || "";
  const componentReport = componentFractionReport(meta);
  const floodEval = floodEventEvaluation(meta);
  const cards = [
    { label: "率定流程", value: hydrologySummaryValue(summary, "workflow_label_zh", runTypeLabel(data?.run?.run_type, manual ? "手调结果" : starter ? "手调起点" : editable ? "单流程参数率定" : "历史率定结果")), detail: "当前页面显示水文摘要，详细数据见本地结果目录" },
    { label: "评分标准", value: hydrologySummaryValue(summary, "objective_label_zh", "综合水文目标函数"), detail: "径流拟合与三水源构成综合评分" },
    { label: "径流拟合", value: hydrologySummaryValue(summary, "flow_status_zh"), detail: "综合 NSE、KGE、PBIAS 径流指标" },
    ...(floodEval?.enabled ? [{ label: "洪水事件", value: floodEventStatusText(floodEval), detail: floodEval.objective_enabled ? "本次按事件窗口参与率定评分" : "本次输出逐场洪水诊断" }] : []),
    { label: "三水源构成", value: componentFractionText(componentReport), detail: componentFractionBasisText(componentReport) },
    { label: "结果说明", value: reportPath ? shortPath(summary.diagnostics_detail_display_path || reportPath) : "结果目录内生成", detail: "水文模拟结果说明已保存至本地结果目录" },
  ];
  host.innerHTML = cards.map(card => `
    <article class="engineering-card">
      <span>${escapeHtml(card.label)}</span>
      <strong>${escapeHtml(card.value || "—")}</strong>
      <small>${escapeHtml(card.detail || "—")}</small>
    </article>
  `).join("");
  const actionButtons = [
    data?.run?.path ? `<button class="ghost-button" data-rename-run="${escapeHtml(data.run.path)}">${data?.run?.has_custom_title ? "修改标题" : "命名结果"}</button>` : "",
    data?.run?.path ? `<button class="ghost-button" data-run-summary-open-dir="${escapeHtml(data.run.path)}">打开结果目录</button>` : "",
    reportPath ? `<button class="ghost-button" data-run-summary-open-report="${escapeHtml(reportPath)}">打开过程复核报告</button>` : "",
    workspaceConfig && !samePath(workspaceConfig, state.runWorkspaceFilterPath) ? `<button class="ghost-button" data-run-summary-filter-workspace="${escapeHtml(workspaceConfig)}">只看本工作区</button>` : "",
    workspaceConfig ? `<button class="ghost-button" data-run-summary-open-workspace="${escapeHtml(workspaceConfig)}">回到工作区配置</button>` : "",
    data?.run?.path ? `<button class="ghost-button" data-delete-run="${escapeHtml(data.run.path)}">删除当前结果</button>` : "",
  ].filter(Boolean);
  actions.innerHTML = actionButtons.join("");
  const noteParts = [
    "结果页已压缩为水文摘要；完整过程复核和逐年分析保存在本地过程复核报告中。",
    editable
      ? (manual ? "该结果来自手动调参后的保存重算，可继续在此基础上调整。" : starter ? "该结果是系统生成的手调起点，可作为后续人工复核起点。" : "该结果保留工作区配置和参数边界，可继续手动调参与保存重算。")
      : "当前结果仅支持查看。",
  ];
  if (replayInfo.obsReplay) {
    noteParts.push("观测序列已从源结果回放恢复，即使当前工作区原始观测 CSV 缺失，也能继续打开和重算。");
  }
  if (replayInfo.boundaryReplay) {
    noteParts.push("上游边界入流已从源结果回放恢复；当前继续修改 Muskingum 路由参数时，不会重新路由原始边界 CSV。");
  }
  if (isDegraded) {
    const degradedReason = Array.isArray(meta?.reliability_notes) ? meta.reliability_notes.join("；") : "";
    noteParts.push(`当前结果可靠性降级${degradedReason ? `：${degradedReason}` : "。"} `);
  }
  if (meta?.project_object_type === "regression_validation" || String(data?.run?.path || "").includes("HBVStudio_Demo")) {
    noteParts.push("当前结果仅代表本次工程配置下的一次率定结果，请结合输入数据、参数设置和本地过程复核报告综合判断。");
  }
  note.textContent = noteParts.join("");
  note.className = `hint-box ${(!editable || replayInfo.boundaryReplay || isDegraded) ? "status-warn" : "status-ok"}`.trim();
}

// --------------- API helpers ---------------

async function apiGet(path) {
  let r;
  try { r = await fetch(path); }
  catch { throw new Error("未连接到 HBV-Studio 本地服务，请使用 python HBV-Studio/launch.py 启动。"); }
  const text = await r.text();
  let p;
  try {
    p = text ? JSON.parse(text) : {};
  } catch {
    const snippet = String(text || "").replace(/\s+/g, " ").trim().slice(0, 120);
    throw new Error(`本地服务返回了无法识别的内容：${r.status}${snippet ? `，响应片段：${snippet}` : ""}`);
  }
  if (!r.ok || !p.ok) throw new Error(p.error || `请求失败：${r.status}`);
  return p;
}

async function apiPost(path, body) {
  let r;
  try {
    r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch { throw new Error("未连接到 HBV-Studio 本地服务，请使用 python HBV-Studio/launch.py 启动。"); }
  const text = await r.text();
  let p;
  try {
    p = text ? JSON.parse(text) : {};
  } catch {
    const snippet = String(text || "").replace(/\s+/g, " ").trim().slice(0, 120);
    throw new Error(`本地服务返回了无法识别的内容：${r.status}${snippet ? `，响应片段：${snippet}` : ""}`);
  }
  if (!r.ok || !p.ok) throw new Error(p.error || `请求失败：${r.status}`);
  return p;
}

// --------------- service pill ---------------

function setServiceState(ok, msg) {
  const pill = $("#service-pill");
  pill.textContent = msg;
  pill.classList.remove("connected", "error");
  pill.classList.add(ok ? "connected" : "error");
}

// --------------- view switching ---------------

function setView(view) {
  if (!viewMeta[view]) view = "dashboard";
  state.currentView = view;
  $all(".view").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  $all(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.viewTarget === view));
  $("#page-title").textContent    = viewMeta[view].title;
  $("#page-subtitle").textContent = viewMeta[view].subtitle;
  if (view === "forecast") renderForecastView();
}

// --------------- sidebar ---------------

function updateSidebar() {
  $("#sidebar-current-workspace").textContent = state.currentWorkspace
    ? (state.currentWorkspace?.流域名称 || workspaceLabelByPath(state.wizardWorkspacePath) || shortPath(state.wizardWorkspacePath))
    : "未选择";
  $("#sidebar-current-profile").textContent = profileLabel(state.currentWorkspace?.率定模式);
  $("#sidebar-current-object").textContent = objectLabels[state.currentWorkspace?.项目对象] || "未选择";
  const workflow = state.currentWorkspaceWorkflow;
  $("#sidebar-current-workflow").textContent = workflow
    ? (workflow.ready_for_calibration
      ? `可率定 · ${workflow.completed_count || 0}/${workflow.total_steps || 0}`
      : workflow.pending_validation
        ? `待检查 · ${workflow.completed_count || 0}/${workflow.total_steps || 0}`
        : `未就绪 · ${workflow.completed_count || 0}/${workflow.total_steps || 0}`)
    : "未检查";
  $("#sidebar-next-step").textContent = workspaceNextStepText(workflow);
}

function updateCounts() {
  $("#count-templates").textContent  = String(state.templates.length);
  $("#count-workspaces").textContent = String(state.workspaces.length);
  $("#count-runs").textContent       = String(state.runs.length);
  $("#count-tasks").textContent      = String(state.tasks.length);
}

// ===============================================================
//  WIZARD
// ===============================================================

function getSelectedRadio(name) {
  const el = document.querySelector(`input[name="${name}"]:checked`);
  return el ? el.value : "";
}

function isFullUpstream() {
  return getSelectedRadio("wz-object") === "full_upstream_basin";
}

function normalizePrecipSourceKey(source, fallback = "era5") {
  const key = String(source || "").trim().toLowerCase();
  return key || fallback;
}

function workspaceConfiguredPrecipSource(cfg = state.currentWorkspace || {}) {
  const meteo = cfg?.气象策略 || {};
  const source = normalizePrecipSourceKey(meteo?.降水来源, "");
  const legacySource = normalizePrecipSourceKey(meteo?.降水源, "");
  const topLevelSource = normalizePrecipSourceKey(cfg?.默认降水源, "");
  if (source) return source;
  if ((topLevelSource === "era5" || topLevelSource === "cmfd" || topLevelSource === "custom_tif") && (!legacySource || legacySource === "mswep")) {
    return topLevelSource;
  }
  return legacySource || topLevelSource || "era5";
}

function getConfiguredPrecipSource() {
  return normalizePrecipSourceKey($("#wz-prec-source")?.value, "") || workspaceConfiguredPrecipSource(state.currentWorkspace);
}

function getTaskPrecipSource() {
  return normalizePrecipSourceKey($("#task-prec-source")?.value, "") || getConfiguredPrecipSource();
}

function getEffectiveRuntimePrecipSource(source = getConfiguredPrecipSource()) {
  const key = normalizePrecipSourceKey(source, "");
  if (key === "custom_tif") return "custom_tif";
  if (key === "era5" || key === "cmfd") return key;
  return "mswep";
}

function getTaskRuntimePrecipSource() {
  return getEffectiveRuntimePrecipSource(getTaskPrecipSource());
}

function syncTaskPrecipSourceControl() {
  const select = $("#task-prec-source");
  if (!select) return;
  const configured = getConfiguredPrecipSource();
  let customOption = Array.from(select.options).find(opt => opt.value === "custom_tif");
  if (configured === "custom_tif") {
    if (!customOption) {
      customOption = document.createElement("option");
      customOption.value = "custom_tif";
      customOption.textContent = "本地栅格目录";
      select.appendChild(customOption);
    }
    select.value = "custom_tif";
    select.disabled = true;
    select.title = "当前工作区已锁定为本地降水栅格目录";
    return;
  }
  if (customOption) customOption.remove();
  if (!select.value || select.value === "custom_tif") {
    select.value = getEffectiveRuntimePrecipSource(configured);
  }
  select.disabled = false;
  select.title = "";
}

function getConfiguredPrecipSourceLabel(source = getConfiguredPrecipSource()) {
  const key = normalizePrecipSourceKey(source, "");
  if (key === "custom_tif") return "本地降水栅格目录";
  if (key === "era5") return "ERA5 自动下载降水";
  if (key === "cmfd") return "CMFD 本地原始文件";
  return "MSWEP 本地原始文件";
}

function getRuntimePrecipDirectoryLabel(source = getConfiguredPrecipSource()) {
  const key = normalizePrecipSourceKey(source, "");
  if (key === "custom_tif") return "工程独立降水目录（本地导入）";
  if (getEffectiveRuntimePrecipSource(key) === "era5") return "工程降水目录（ERA5 自动下载）";
  return getEffectiveRuntimePrecipSource(key) === "cmfd"
    ? "工程降水目录（CMFD 本地原始文件）"
    : "工程降水目录（MSWEP 本地原始文件）";
}

function isStudioEditableRun(data) {
  return Boolean(data?.studio_compatible || data?.run?.studio_compatible);
}

function getRunManualPresetConfigPath(data = state._runData) {
  return String(data?.metadata?.workspace_config || data?.run?.workspace_config || "").trim();
}

function getTaskManualPresetConfigPath() {
  return String(state.wizardWorkspacePath || "").trim();
}

function resolveManualPresetProfile(configPath = "", explicitProfile = "") {
  const explicit = normalizeCalibrationProfile(explicitProfile, "");
  if (explicit) return explicit;
  const path = String(configPath || "").trim();
  const runConfigPath = String(state._runData?.metadata?.workspace_config || "").trim();
  if (path && runConfigPath && samePath(path, runConfigPath)) {
    const runProfile = normalizeCalibrationProfile(state._runData?.metadata?.calibration_profile, "");
    if (runProfile) return runProfile;
  }
  if (path && state.wizardWorkspacePath && samePath(path, state.wizardWorkspacePath)) {
    const workspaceProfile = normalizeCalibrationProfile(state.currentWorkspace?.率定模式, "");
    if (workspaceProfile) return workspaceProfile;
  }
  return normalizeCalibrationProfile(
    state._runData?.metadata?.calibration_profile || state.currentWorkspace?.率定模式,
    "daily"
  );
}

function renderPresetOptions(selector, presets, placeholder) {
  const el = $(selector);
  if (!el) return;
  window.HBVStudioParameterLibrary?.renderPresetOptions(el, presets, placeholder, { escapeHtml });
}

function renderManualPresetOptions() {
  renderPresetOptions("#manual-preset-select", state.runManualPresets, "选择已保存参数集");
  renderPresetOptions("#task-init-preset", state.taskManualPresets, "不使用手调初值");
  renderTaskPresetContextHint();
}

function updateManualPresetControls() {
  const editable = isStudioEditableRun(state._runData);
  const hasConfigPath = Boolean(getRunManualPresetConfigPath());
  const enabled = editable && hasConfigPath;
  const hasPreset = Boolean(selectedManualPreset());
  const hasCompare = Boolean(state.compareSeries || state.compareMetrics);
  ["#manual-preset-name", "#manual-preset-scope", "#manual-preset-select", "#btn-save-manual-preset"].forEach(sel => {
    const el = $(sel);
    if (el) el.disabled = !enabled;
  });
  ["#btn-load-manual-preset", "#btn-delete-manual-preset", "#btn-compare-manual-preset"].forEach(sel => {
    const el = $(sel);
    if (el) el.disabled = !(enabled && hasPreset);
  });
  const clearCompareBtn = $("#btn-clear-manual-compare");
  if (clearCompareBtn) clearCompareBtn.disabled = !hasCompare;
}

async function loadRunManualPresets(configPath = getRunManualPresetConfigPath(), { silent = false, calibrationProfile = "" } = {}) {
  const path = String(configPath || "").trim();
  const resolvedProfile = resolveManualPresetProfile(path, calibrationProfile);
  const requestId = nextRunManualPresetRequestId();
  const pathChanged = !samePath(path, state.runManualPresetConfigPath);
  state.runManualPresetConfigPath = path;
  if (!path) {
    if (requestId !== state.activeRunManualPresetRequestId) return [];
    state.runManualPresets = [];
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
    return [];
  }
  if (pathChanged) {
    state.runManualPresets = [];
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
  }
  try {
    const p = await apiGet(`/api/manual-presets?config_path=${encodeURIComponent(path)}&calibration_profile=${encodeURIComponent(resolvedProfile)}&scope=all`);
    if (requestId !== state.activeRunManualPresetRequestId || !samePath(path, state.runManualPresetConfigPath)) {
      return p.data?.presets || [];
    }
    state.runManualPresets = p.data?.presets || [];
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
    clearStaleManualPresetComparison({ silent: true });
    return state.runManualPresets;
  } catch (err) {
    if (requestId !== state.activeRunManualPresetRequestId || !samePath(path, state.runManualPresetConfigPath)) {
      return [];
    }
    state.runManualPresets = [];
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
    clearStaleManualPresetComparison({ silent: true });
    if (!silent) showToast(err.message, true);
    return [];
  }
}

async function loadTaskManualPresets(configPath = getTaskManualPresetConfigPath(), { silent = false, calibrationProfile = "" } = {}) {
  const path = String(configPath || "").trim();
  const resolvedProfile = resolveManualPresetProfile(path, calibrationProfile);
  const requestId = nextTaskManualPresetRequestId();
  const pathChanged = !samePath(path, state.taskManualPresetConfigPath);
  state.taskManualPresetConfigPath = path;
  if (!path) {
    if (requestId !== state.activeTaskManualPresetRequestId) return [];
    state.taskManualPresets = [];
    renderManualPresetOptions();
    refreshCalibrationControls();
    return [];
  }
  if (pathChanged) {
    state.taskManualPresets = [];
    renderManualPresetOptions();
    refreshCalibrationControls();
  }
  try {
    const p = await apiGet(`/api/manual-presets?config_path=${encodeURIComponent(path)}&calibration_profile=${encodeURIComponent(resolvedProfile)}&scope=all`);
    if (requestId !== state.activeTaskManualPresetRequestId || !samePath(path, state.taskManualPresetConfigPath)) {
      return p.data?.presets || [];
    }
    state.taskManualPresets = p.data?.presets || [];
    renderManualPresetOptions();
    refreshCalibrationControls();
    return state.taskManualPresets;
  } catch (err) {
    if (requestId !== state.activeTaskManualPresetRequestId || !samePath(path, state.taskManualPresetConfigPath)) {
      return [];
    }
    state.taskManualPresets = [];
    renderManualPresetOptions();
    refreshCalibrationControls();
    if (!silent) showToast(err.message, true);
    return [];
  }
}

const WIZARD_TIME_FIELDS = [
  "#wz-warmup-start",
  "#wz-warmup-end",
  "#wz-calib-start",
  "#wz-calib-end",
  "#wz-valid-start",
  "#wz-valid-end",
];

function isHourlyTimescaleSelected() {
  return getSelectedRadio("wz-timescale") === "hourly";
}

function toWizardInputTimeValue(value, hourly) {
  const text = String(value || "").trim();
  if (!text) return "";
  const normalized = text.replace("T", " ");
  const match = normalized.match(/^(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?/);
  if (match) {
    return hourly ? `${match[1]}T${match[2] || "00:00"}` : match[1];
  }
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  const yyyy = String(date.getFullYear()).padStart(4, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  if (!hourly) return `${yyyy}-${mm}-${dd}`;
  const hh = String(date.getHours()).padStart(2, "0");
  const mi = String(date.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}T${hh}:${mi}`;
}

function fromWizardInputTimeValue(value, hourly) {
  if (!value) return "";
  return hourly ? String(value).replace("T", " ") : String(value).slice(0, 10);
}

function setWizardTimeValue(selector, value) {
  const input = $(selector);
  if (!input) return;
  input.value = toWizardInputTimeValue(value, isHourlyTimescaleSelected());
}

function getWizardTimeValue(selector) {
  const input = $(selector);
  if (!input) return "";
  return fromWizardInputTimeValue(input.value, isHourlyTimescaleSelected());
}

function syncWizardTimeInputMode() {
  const hourly = isHourlyTimescaleSelected();
  WIZARD_TIME_FIELDS.forEach(selector => {
    const input = $(selector);
    if (!input) return;
    const preserved = toWizardInputTimeValue(input.value, hourly);
    input.type = hourly ? "datetime-local" : "date";
    input.step = hourly ? "60" : "";
    input.value = preserved;
  });
}

function syncCustomMeteoImportInputs(force = false) {
  let copied = 0;
  const mappings = [
    {
      sourceSel: "#wz-custom-prec-dir",
      targetSel: "#wz-import-prec-dir",
      enabled: () => ($("#wz-prec-source")?.value || "era5") === "custom_tif",
    },
    {
      sourceSel: "#wz-custom-temp-dir",
      targetSel: "#wz-import-temp-dir",
      enabled: () => ($("#wz-temp-source")?.value || "era5") === "custom_tif",
    },
    {
      sourceSel: "#wz-custom-pet-dir",
      targetSel: "#wz-import-evap-dir",
      enabled: () => ($("#wz-pet-source")?.value || "era5_fao56") === "custom_tif",
    },
  ];
  mappings.forEach(({ sourceSel, targetSel, enabled }) => {
    const source = $(sourceSel);
    const target = $(targetSel);
    if (!source || !target || !enabled()) return;
    if (source.value.trim() && (force || !target.value.trim())) {
      target.value = source.value.trim();
      copied += 1;
    }
  });
  return copied;
}

function getWizardMeteoSources() {
  return {
    prec: ($("#wz-prec-source")?.value || "era5").trim().toLowerCase(),
    temp: ($("#wz-temp-source")?.value || "era5").trim().toLowerCase(),
    pet: ($("#wz-pet-source")?.value || "era5_fao56").trim().toLowerCase(),
  };
}

function wizardNeedsEra5Download() {
  const sources = getWizardMeteoSources();
  return sources.prec === "era5" || sources.temp !== "custom_tif" || sources.pet !== "custom_tif";
}

function currentEra5NeedSignature() {
  const sources = getWizardMeteoSources();
  return `${sources.prec}|${sources.temp}|${sources.pet}`;
}

function getWizardLocalMeteoLabels() {
  const sources = getWizardMeteoSources();
  const labels = [];
  if (sources.prec === "custom_tif") labels.push("降水");
  if (sources.temp === "custom_tif") labels.push("气温");
  if (sources.pet === "custom_tif") labels.push("蒸散发");
  return labels;
}

function getWizardPipelineMeteoLabels() {
  const sources = getWizardMeteoSources();
  const labels = [];
  if (sources.prec !== "custom_tif") labels.push("降水");
  if (sources.temp !== "custom_tif") labels.push("气温");
  if (sources.pet !== "custom_tif") labels.push("蒸散发");
  return labels;
}

function hasLocalMeteoSourceConfigured() {
  return getWizardLocalMeteoLabels().length > 0;
}

function allMeteoSourcesUseLocalTif() {
  return getWizardLocalMeteoLabels().length === 3;
}

function updateMeteoModeHint() {
  const hint = $("#wz-import-meteo-hint");
  if (!hint) return;
  const localLabels = getWizardLocalMeteoLabels();
  if (!localLabels.length) {
    if (!hint.textContent || !hint.className.includes("status-fail")) {
      hint.textContent = "";
      hint.className = "hint-box";
    }
    return;
  }
  const copiedLabels = [];
  if ($("#wz-import-prec-dir")?.value.trim()) copiedLabels.push("降水");
  if ($("#wz-import-temp-dir")?.value.trim()) copiedLabels.push("气温");
  if ($("#wz-import-evap-dir")?.value.trim()) copiedLabels.push("蒸散发");
  const copiedText = copiedLabels.length
    ? `已自动带入第 4 步登记的本地栅格目录（${copiedLabels.join("、")}）。`
    : "";
  if (allMeteoSourcesUseLocalTif()) {
    hint.textContent = `${copiedText}当前三类气象都来自本地栅格，第 6 步默认使用“直接导入本地栅格”。`;
    hint.className = "hint-box status-ok";
    return;
  }
  const pipelineLabels = getWizardPipelineMeteoLabels();
  const pipelineText = pipelineLabels.length
    ? `仍需按步骤处理 ${pipelineLabels.join("、")}。`
    : "请按当前配置继续。";
  hint.textContent = `${copiedText}当前为混合来源方案，本地目录会在对齐步骤自动读取；${pipelineText}`;
  hint.className = "hint-box status-ok";
}

function applyStep6MeteoDefaults({ force = false, switchMode = false } = {}) {
  const copied = syncCustomMeteoImportInputs(force);
  if (switchMode) setRadioValue("wz-meteo-mode", allMeteoSourcesUseLocalTif() ? "import" : "pipeline");
  updateMeteoMode();
  return copied;
}

// --- conditional fields ---

function updateConditionalFields() {
  // step 3 skipped?
  const step3btn = $(`.wizard-step[data-step="3"]`);
  if (isFullUpstream()) {
    step3btn.classList.add("skipped");
  } else {
    step3btn.classList.remove("skipped");
  }

  // station fields
  const precMode = getSelectedRadio("wz-precip-mode");
  const stationFields = $("#wz-station-fields");
  if (precMode === "grid_only") {
    stationFields.classList.add("hidden");
  } else {
    stationFields.classList.remove("hidden");
  }

  // hourly prec group: only show for hourly timescale
  const timescale = getSelectedRadio("wz-timescale");
  const hourlyGroup = $("#wz-hourly-prec-group");
  if (timescale === "daily") {
    hourlyGroup.classList.add("hidden");
  } else {
    hourlyGroup.classList.remove("hidden");
  }

  // custom prec dir: only show when prec source is custom_tif
  const precSource = $("#wz-prec-source")?.value || "era5";
  const customPrecGroup = $("#wz-custom-prec-group");
  if (customPrecGroup) {
    if (precSource === "custom_tif") {
      customPrecGroup.classList.remove("hidden");
    } else {
      customPrecGroup.classList.add("hidden");
    }
  }

  // temperature: custom tif directory
  const tempSource = $("#wz-temp-source")?.value || "era5";
  const customTempGroup = $("#wz-custom-temp-group");
  if (customTempGroup) {
    if (tempSource === "custom_tif") {
      customTempGroup.classList.remove("hidden");
    } else {
      customTempGroup.classList.add("hidden");
    }
  }

  // PET: custom tif directory
  const petSource = $("#wz-pet-source")?.value || "era5_fao56";
  const customPetGroup = $("#wz-custom-pet-group");
  if (customPetGroup) {
    if (petSource === "custom_tif") {
      customPetGroup.classList.remove("hidden");
    } else {
      customPetGroup.classList.add("hidden");
    }
  }

  syncTaskPrecipSourceControl();
  syncWizardTimeInputMode();
  syncCustomMeteoImportInputs();
  updateMeteoMode();
  renderPrecipStrategyStatus();
  renderStationPrecipCheckOverview();
  updateProjectFocusHint();
  updateBoundaryGuidance();
  updateObservationHint();
  clearBoundaryPreview();
}

// --- radio cards ---

function setupRadioCards() {
  document.addEventListener("click", (e) => {
    const card = e.target.closest(".radio-card");
    if (!card) return;
    const group = card.closest(".radio-card-group");
    if (!group) return;
    group.querySelectorAll(".radio-card").forEach(c => c.classList.remove("selected"));
    card.classList.add("selected");
    const radio = card.querySelector("input[type=radio]");
    if (radio) {
      radio.checked = true;
      radio.dispatchEvent(new Event("change", { bubbles: true }));
    }
    updateConditionalFields();
    updateGisMode();
    updateMeteoMode();
  });
}

// --- wizard navigation ---

function navigateWizardStep(target) {
  let t = Number(target);

  // skip step 3 when full_upstream
  if (t === 3 && isFullUpstream()) {
    t = state.wizardStep < 3 ? 4 : 2;
  }

  state.wizardStep = t;
  $all(".wizard-panel").forEach(p => p.classList.toggle("active", Number(p.dataset.wizardStep) === t));
  $all(".wizard-step").forEach(s => {
    const sn = Number(s.dataset.step);
    s.classList.toggle("active", sn === t);
    if (sn < t && !(sn === 3 && isFullUpstream())) {
      s.classList.add("completed");
    }
  });

  // auto-load data for specific steps
  if (t === 5 && state.wizardWorkspacePath) loadBootstrapStatus();
  if (t === 6 && state.wizardWorkspacePath) {
    applyStep6MeteoDefaults({ force: true, switchMode: true });
    loadPrepSteps();
  }
  if (t === 7 && state.wizardWorkspacePath) runInputCheck();
}

// --- collect step data ---

function collectStepData(step) {
  switch (step) {
    case 1: return {
      name: $("#wz-name").value.trim(),
      timescale: getSelectedRadio("wz-timescale"),
      object: getSelectedRadio("wz-object"),
    };
    case 2: return {
      basin_shp: $("#wz-basin-shp").value.trim(),
      obs_csv: $("#wz-obs-csv").value.trim(),
      dem_tif: $("#wz-dem-tif").value.trim(),
      glacier_shp: $("#wz-glacier-shp").value.trim(),
      time_basis: $("#wz-time-basis")?.value || "continuous",
      event_file: $("#wz-event-file")?.value.trim() || "",
      warmup_start: getWizardTimeValue("#wz-warmup-start"),
      warmup_end: getWizardTimeValue("#wz-warmup-end"),
      calib_start: getWizardTimeValue("#wz-calib-start"),
      calib_end: getWizardTimeValue("#wz-calib-end"),
      valid_start: getWizardTimeValue("#wz-valid-start"),
      valid_end: getWizardTimeValue("#wz-valid-end"),
      cfmax: Number($("#wz-cfmax").value) || 5000,
      fao_elev: Number($("#wz-fao-elev").value) || 4500,
    };
    case 3: return {
      boundary_csv: $("#wz-boundary-csv").value.trim(),
      gap_fill: $("#wz-gap-fill").value,
      date_field: $("#wz-boundary-date").value.trim(),
      flow_field: $("#wz-boundary-flow").value.trim(),
    };
    case 4: return {
      气象策略: {
        降水方案: getSelectedRadio("wz-precip-mode"),
        降水来源: $("#wz-prec-source").value,
        降水源: $("#wz-prec-source").value,
        站点降水_csv: $("#wz-station-prec").value.trim(),
        站点信息_csv: $("#wz-station-meta").value.trim(),
        原始小时降水目录: $("#wz-hourly-prec-dir").value.trim(),
        自带降水tif目录: $("#wz-custom-prec-dir")?.value.trim() || "",
        温度来源: $("#wz-temp-source")?.value || "era5",
        自带温度tif目录: $("#wz-custom-temp-dir")?.value.trim() || "",
        潜在蒸散发来源: $("#wz-pet-source")?.value || "era5_fao56",
        自带蒸散发tif目录: $("#wz-custom-pet-dir")?.value.trim() || "",
      },
      默认降水源: $("#wz-prec-source").value || "era5",
    };
    default: return {};
  }
}

// --- save current step ---

async function saveCurrentWizardStep() {
  const step = state.wizardStep;
  const data = collectStepData(step);
  clearInputCheckCache();

  if (step === 1 && (!state.wizardWorkspacePath || !state.currentWorkspace)) {
    state.wizardWorkspacePath = workspacePathForName(data.name || "");
  }

  // for a NEW workspace (no path yet), derive path from name
  if (false && !state.wizardWorkspacePath && step === 1) {
    const name = data.name || "新流域";
    state.wizardWorkspacePath = `workspaces/${name}.json`;
  }

  if (!state.wizardWorkspacePath) return;

  try {
    const payload = await apiPost("/api/wizard/save-step", {
      workspace_path: state.wizardWorkspacePath,
      step: step,
      data: data,
    });
    const result = payload.data || {};
    if (result.path) {
      state.wizardWorkspacePath = result.path;
    }
    if (result.config) {
      state.currentWorkspace = result.config;
      if (step === 2) {
        if ($("#wz-basin-shp")) $("#wz-basin-shp").value = result.config.流域边界_shp || $("#wz-basin-shp").value;
        if ($("#wz-obs-csv")) $("#wz-obs-csv").value = result.config.观测径流_csv || $("#wz-obs-csv").value;
        if ($("#wz-glacier-shp")) $("#wz-glacier-shp").value = result.config.冰川边界_shp || $("#wz-glacier-shp").value;
        if ($("#wz-time-basis")) $("#wz-time-basis").value = result.config.任务时段模式 || $("#wz-time-basis").value;
        if ($("#wz-event-file")) {
          const eventMode = result.config.事件资料模式 || {};
          const floodMode = result.config.洪水事件率定 || {};
          $("#wz-event-file").value = eventMode.事件表路径 || floodMode.事件表路径 || $("#wz-event-file").value;
        }
        updateEventModeHint();
        renderWizardEventSummary(result.validation?.event_windows || null);
      }
    }
    if (step === 1) {
      await loadWorkspaces();
      previewWorkspaceLayout(state.wizardWorkspacePath, { silent: true }).catch(() => {});
      refreshCurrentWorkspaceLayout().catch(() => {});
    }
    await refreshCurrentWorkspaceWorkflow();
    if (step >= 6 || state.currentView === "calibration") {
      refreshCurrentWorkspaceAdvice().catch(() => {});
    }
    updateSidebar();
    refreshCalibrationControls();
    return result.validation || null;
  } catch (err) {
    showToast(err.message, true);
    throw err;
  }
}

function enforceWizardValidation(validation, step = state.wizardStep) {
  if (!validation || validation.valid) return true;
  if (step === 2) {
    renderWizardEventSummary(validation.event_windows || null);
    const issues = (validation.missing || []).slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    const warns = (validation.warnings || []).slice(0, 2).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    $("#wz-obs-hint").innerHTML = `<strong>第 2 步未通过。</strong>${issues ? `<ul>${issues}</ul>` : ""}${warns ? `<div style="margin-top:6px">提示：</div><ul>${warns}</ul>` : ""}`;
    $("#wz-obs-hint").className = "hint-box status-fail";
  } else if (step === 3) {
    const issues = (validation.missing || []).slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    const warns = (validation.warnings || []).slice(0, 2).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    $("#wz-boundary-preview").innerHTML = `<div class="hint-box status-fail"><strong>第 3 步未通过。</strong>${issues ? `<ul>${issues}</ul>` : ""}${warns ? `<div style="margin-top:6px">提示：</div><ul>${warns}</ul>` : ""}</div>`;
  }
  const preview = (validation.missing || []).slice(0, 3).join("；");
  showToast(`第 ${step} 步未完成：${preview || "请补全必填项"}`, true);
  return false;
}

// --- populate wizard fields from config ---

function populateWizardFromConfig(cfg, path) {
  state.currentWorkspace = cfg;
  state.wizardWorkspacePath = path;
  state.currentWorkspaceLayout = null;
  state.currentWorkspaceLayoutPath = "";
  clearInputCheckCache();
  state.obsInfo = null;

  // step 1
  $("#wz-name").value = cfg.流域名称 || cfg.name || "";
  setRadioAndCard("wz-timescale", cfg.率定模式 === "hourly" ? "hourly" : "daily");
  setRadioAndCard("wz-object", cfg.项目对象 || "full_upstream_basin");
  syncWizardTimeInputMode();

  // step 2
  $("#wz-basin-shp").value     = cfg.流域边界_shp || "";
  $("#wz-obs-csv").value       = cfg.观测径流_csv || "";
  $("#wz-dem-tif").value       = cfg.DEM_tif || "";
  $("#wz-glacier-shp").value   = cfg.冰川边界_shp || "";
  const eventModeCfg = cfg.事件资料模式 || {};
  const floodEventCfg = cfg.洪水事件率定 || {};
  const timeBasis = cfg.任务时段模式 || cfg.time_basis || cfg.资料时段模式 || (eventModeCfg.启用 ? "event_windows" : "continuous");
  if ($("#wz-time-basis")) $("#wz-time-basis").value = timeBasis === "event_windows" ? "event_windows" : "continuous";
  if ($("#wz-event-file")) $("#wz-event-file").value = eventModeCfg.事件表路径 || floodEventCfg.事件表路径 || eventModeCfg.events_file || floodEventCfg.events_file || "";
  setWizardTimeValue("#wz-warmup-start", cfg.时间?.预热开始 || "");
  setWizardTimeValue("#wz-warmup-end", cfg.时间?.预热结束 || "");
  setWizardTimeValue("#wz-calib-start", cfg.时间?.率定开始 || "");
  setWizardTimeValue("#wz-calib-end", cfg.时间?.率定结束 || "");
  setWizardTimeValue("#wz-valid-start", cfg.时间?.验证开始 || "");
  setWizardTimeValue("#wz-valid-end", cfg.时间?.验证结束 || "");
  $("#wz-cfmax").value         = cfg.CFMAX分区阈值_m ?? 5000;
  $("#wz-fao-elev").value      = cfg.FAO56平均海拔_m ?? 4500;
  updateEventModeHint();

  // step 3
  $("#wz-boundary-csv").value  = cfg.边界条件?.上游边界入流_csv || "";
  $("#wz-gap-fill").value      = cfg.边界条件?.缺失填补 || "zero";
  $("#wz-boundary-date").value = cfg.边界条件?.时间字段 || "date";
  $("#wz-boundary-flow").value = cfg.边界条件?.流量字段 || "inflow_m3s";

  // step 4
  setRadioAndCard("wz-precip-mode", cfg.气象策略?.降水方案 || "grid_only");
  $("#wz-station-prec").value    = cfg.气象策略?.站点降水_csv || "";
  $("#wz-station-meta").value    = cfg.气象策略?.站点信息_csv || "";
  $("#wz-prec-source").value     = workspaceConfiguredPrecipSource(cfg);
  $("#wz-hourly-prec-dir").value = cfg.气象策略?.原始小时降水目录 || "";
  if ($("#wz-custom-prec-dir")) $("#wz-custom-prec-dir").value = cfg.气象策略?.自带降水tif目录 || "";
  const tempSrc = cfg.气象策略?.温度来源 || "era5";
  if ($("#wz-temp-source")) $("#wz-temp-source").value = tempSrc;
  if ($("#wz-custom-temp-dir")) $("#wz-custom-temp-dir").value = cfg.气象策略?.自带温度tif目录 || "";
  const petSrc = cfg.气象策略?.潜在蒸散发来源 || "era5_fao56";
  if ($("#wz-pet-source")) $("#wz-pet-source").value = petSrc;
  if ($("#wz-custom-pet-dir")) $("#wz-custom-pet-dir").value = cfg.气象策略?.自带蒸散发tif目录 || "";
  if ($("#wz-import-prec-dir")) $("#wz-import-prec-dir").value = "";
  if ($("#wz-import-temp-dir")) $("#wz-import-temp-dir").value = "";
  if ($("#wz-import-evap-dir")) $("#wz-import-evap-dir").value = "";
  if ($("#wz-import-dem")) $("#wz-import-dem").value = "";
  if ($("#wz-import-flowacc")) $("#wz-import-flowacc").value = "";
  if ($("#wz-import-flowdir")) $("#wz-import-flowdir").value = "";
  if ($("#wz-import-glacier")) $("#wz-import-glacier").value = "";
  if ($("#wz-import-meteo-log")) {
    $("#wz-import-meteo-log").textContent = "";
    $("#wz-import-meteo-log").style.display = "none";
  }
  if ($("#wz-import-meteo-hint")) {
    $("#wz-import-meteo-hint").textContent = "";
    $("#wz-import-meteo-hint").className = "hint-box";
  }
  if ($("#wz-pipeline-task-log")) {
    $("#wz-pipeline-task-log").textContent = "";
    $("#wz-pipeline-task-log").style.display = "none";
  }
  if ($("#wz-pipeline-task-hint")) {
    $("#wz-pipeline-task-hint").textContent = "";
    $("#wz-pipeline-task-hint").className = "hint-box";
    $("#wz-pipeline-task-hint").style.display = "none";
  }

  // calibration defaults
  $("#task-prec-source").value = workspaceConfiguredPrecipSource(cfg);
  if ($("#task-objective-mode")) $("#task-objective-mode").value = "daily_unified_professional_v1";
  syncObjectiveModeCards("daily_unified_professional_v1");
  if ($("#task-param-bounds-profile")) $("#task-param-bounds-profile").value = "qtp_alpine_default";

  applyStep6MeteoDefaults({ force: true, switchMode: true });
  updateConditionalFields();
  updateGisMode();
  updateSidebar();
  refreshCalibrationControls();
  refreshWizardWorkspacePreview();
  if ($("#wz-obs-csv").value.trim()) {
    detectObs().catch(() => {});
  }
}

function setRadioAndCard(name, value) {
  const radio = document.querySelector(`input[name="${name}"][value="${value}"]`);
  if (!radio) return;
  radio.checked = true;
  const group = radio.closest(".radio-card-group");
  if (group) {
    group.querySelectorAll(".radio-card").forEach(c => c.classList.remove("selected"));
    const card = radio.closest(".radio-card");
    if (card) card.classList.add("selected");
  }
}

function resetWizard() {
  state.wizardWorkspacePath = "";
  state.currentWorkspace = null;
  state.currentWorkspaceWorkflow = null;
  state.currentWorkspaceAdvice = null;
  state.currentWorkspaceLayout = null;
  state.currentWorkspaceLayoutPath = "";
  clearInputCheckCache();
  state.obsInfo = null;
  state.manualParamGroup = "all";
  state.wizardStep = 1;

  $("#wz-name").value = "";
  setRadioAndCard("wz-timescale", "daily");
  setRadioAndCard("wz-object", "full_upstream_basin");
  syncWizardTimeInputMode();

  [
    "#wz-basin-shp", "#wz-obs-csv", "#wz-dem-tif", "#wz-glacier-shp",
    "#wz-event-file", "#wz-boundary-csv", "#wz-station-prec", "#wz-station-meta",
    "#wz-hourly-prec-dir", "#wz-custom-prec-dir", "#wz-custom-temp-dir",
    "#wz-custom-pet-dir", "#wz-import-prec-dir", "#wz-import-temp-dir",
    "#wz-import-evap-dir", "#wz-import-dem", "#wz-import-flowacc",
    "#wz-import-flowdir", "#wz-import-glacier",
  ].forEach(s => { if ($(s)) $(s).value = ""; });
  WIZARD_TIME_FIELDS.forEach(selector => {
    if ($(selector)) $(selector).value = "";
  });
  $("#wz-cfmax").value = "5000";
  $("#wz-fao-elev").value = "4500";
  if ($("#wz-time-basis")) $("#wz-time-basis").value = "continuous";
  $("#wz-gap-fill").value = "zero";
  $("#wz-boundary-date").value = "date";
  $("#wz-boundary-flow").value = "inflow_m3s";
  setRadioAndCard("wz-precip-mode", "grid_only");
  setRadioValue("wz-meteo-mode", "pipeline");
  $("#wz-prec-source").value = "era5";
  $("#wz-temp-source").value = "era5";
  $("#wz-pet-source").value = "era5_fao56";
  $("#wz-obs-hint").textContent = "选择观测径流文件后将自动推断时间范围。";
  updateEventModeHint();
  $("#wz-elev-hint").textContent = "选择流域边界 shp 后，将根据内置 DEM 自动计算 CFMAX 分区阈值和 FAO56 海拔。";
  $("#wz-boundary-preview").textContent = "";
  $("#bootstrap-status").innerHTML = "";
  $("#wz-bootstrap-log").textContent = "";
  $("#prep-step-list").innerHTML = "";
  $("#wz-check-results").innerHTML = "";
  if ($("#wz-import-meteo-log")) {
    $("#wz-import-meteo-log").textContent = "";
    $("#wz-import-meteo-log").style.display = "none";
  }
  if ($("#wz-import-meteo-hint")) {
    $("#wz-import-meteo-hint").textContent = "";
    $("#wz-import-meteo-hint").className = "hint-box";
  }
  if ($("#wz-pipeline-task-log")) {
    $("#wz-pipeline-task-log").textContent = "";
    $("#wz-pipeline-task-log").style.display = "none";
  }
  if ($("#wz-pipeline-task-hint")) {
    $("#wz-pipeline-task-hint").textContent = "";
    $("#wz-pipeline-task-hint").className = "hint-box";
    $("#wz-pipeline-task-hint").style.display = "none";
  }
  state.activeMeteoImportTaskId = "";
  if (state.meteoImportPollTimer) {
    clearInterval(state.meteoImportPollTimer);
    state.meteoImportPollTimer = null;
  }
  state.activePrepTaskId = "";
  stopPrepTaskPolling();
  state.activeForwardSimTaskId = "";
  state.activeForwardSimSourceRunPath = "";
  stopForwardSimPolling();

  state.taskManualPresets = [];
  state.taskManualPresetConfigPath = "";
  nextTaskManualPresetRequestId();
  if ($("#task-kind")) $("#task-kind").value = "calibration";
  if ($("#task-prec-source")) $("#task-prec-source").value = "era5";
  if ($("#task-glacier-mode")) $("#task-glacier-mode").value = "inline";
  if ($("#task-quick-days")) $("#task-quick-days").value = "30";
  if ($("#task-method")) $("#task-method").value = "mc_screen_de";
  if ($("#task-objective-mode")) $("#task-objective-mode").value = "daily_unified_professional_v1";
  syncObjectiveModeCards("daily_unified_professional_v1");
  if ($("#task-param-bounds-profile")) $("#task-param-bounds-profile").value = "qtp_alpine_default";
  if ($("#task-mc-samples")) $("#task-mc-samples").value = "300";
  if ($("#task-init-preset")) $("#task-init-preset").value = "";
  if ($("#task-init-bound-shrink")) $("#task-init-bound-shrink").value = "0.25";
  if ($("#task-workers")) $("#task-workers").value = "4";
  if ($("#task-maxiter")) $("#task-maxiter").value = "24";
  if ($("#task-popsize")) $("#task-popsize").value = "6";
  if ($("#task-seed")) $("#task-seed").value = "42";
  renderManualPresetOptions();

  // reset progress bar
  $all(".wizard-step").forEach(s => {
    s.classList.remove("active", "completed", "skipped");
  });
  $(`.wizard-step[data-step="1"]`).classList.add("active");
  $all(".wizard-panel").forEach(p => p.classList.remove("active"));
  $(`.wizard-panel[data-wizard-step="1"]`).classList.add("active");

  updateConditionalFields();
  updateGisMode();
  updateManualGroupToolbar();
  updateSidebar();
  refreshCalibrationControls();
  refreshWizardWorkspacePreview();
}

// --- obs auto-detect ---

async function detectObs() {
  const path = $("#wz-obs-csv").value.trim();
  if (!path) return;
  try {
    const targetStepHours = isHourlyTimescaleSelected() ? 1 : 24;
    const payload = await apiGet(
      `/api/obs-info?path=${encodeURIComponent(path)}&target_step_hours=${encodeURIComponent(targetStepHours)}`
    );
    const info = payload.data;
    state.obsInfo = info;
    // Auto-fill time range if empty
    if (info.start && !$("#wz-warmup-start").value) setWizardTimeValue("#wz-warmup-start", info.start);
    if (info.end && !$("#wz-valid-end").value) setWizardTimeValue("#wz-valid-end", info.end);
    // Auto-split if all fields are empty
    if (!$("#wz-warmup-end").value && !$("#wz-calib-start").value && !$("#wz-calib-end").value && !$("#wz-valid-start").value) {
      autoSplitTime();
    }
    updateObservationHint();
  } catch (err) {
    state.obsInfo = null;
    showToast(err.message, true);
  }
}

function autoSplitTime() {
  const start = getWizardTimeValue("#wz-warmup-start");
  const end = getWizardTimeValue("#wz-valid-end");
  if (!start || !end) { showToast("请先填写预热开始和验证结束日期。", true); return; }
  const hourly = isHourlyTimescaleSelected();
  const d0 = parseComparableTime(start);
  const d1 = parseComparableTime(end);
  if (!(d0 instanceof Date) || !(d1 instanceof Date) || Number.isNaN(d0.getTime()) || Number.isNaN(d1.getTime()) || d1 <= d0) {
    showToast("时间范围无效，无法自动划分。", true);
    return;
  }
  const formatSplitValue = d => formatComparableTime(d, hourly);

  if (!hourly) {
    const firstFullYear = (d0.getMonth() === 0 && d0.getDate() === 1) ? d0.getFullYear() : (d0.getFullYear() + 1);
    const lastFullYear = (d1.getMonth() === 11 && d1.getDate() === 31) ? d1.getFullYear() : (d1.getFullYear() - 1);
    const fullYearCount = lastFullYear - firstFullYear + 1;
    if (fullYearCount >= 3) {
      let warmupYears = fullYearCount >= 12 ? 2 : 1;
      let validYears = fullYearCount >= 8 ? 3 : (fullYearCount >= 5 ? 2 : 1);
      while ((fullYearCount - warmupYears - validYears) < 1) {
        if (validYears > 1) validYears -= 1;
        else if (warmupYears > 1) warmupYears -= 1;
        else break;
      }
      if ((fullYearCount - warmupYears - validYears) >= 1) {
        const warmupEnd = new Date(firstFullYear + warmupYears - 1, 11, 31, 0, 0, 0, 0);
        const calibStart = new Date(warmupEnd.getFullYear() + 1, 0, 1, 0, 0, 0, 0);
        const validStart = new Date(lastFullYear - validYears + 1, 0, 1, 0, 0, 0, 0);
        const calibEnd = new Date(validStart.getFullYear() - 1, 11, 31, 0, 0, 0, 0);
        if (calibStart <= calibEnd) {
          setWizardTimeValue("#wz-warmup-end", formatSplitValue(warmupEnd));
          setWizardTimeValue("#wz-calib-start", formatSplitValue(calibStart));
          setWizardTimeValue("#wz-calib-end", formatSplitValue(calibEnd));
          setWizardTimeValue("#wz-valid-start", formatSplitValue(validStart));
          updateObservationHint();
          showToast(
            `已按整年划分：预热 ${formatSplitValue(d0)} ~ ${formatSplitValue(warmupEnd)} / `
            + `率定 ${formatSplitValue(calibStart)} ~ ${formatSplitValue(calibEnd)} / `
            + `验证 ${formatSplitValue(validStart)} ~ ${formatSplitValue(d1)}`
          );
          return;
        }
      }
    }
  }

  const stepMs = hourly ? 3600000 : 86400000;
  const totalSteps = Math.round((d1 - d0) / stepMs);
  const minSteps = hourly ? 30 * 24 : 30;
  if (totalSteps < minSteps) { showToast("时间范围太短，无法自动划分。", true); return; }
  const totalDays = totalSteps / (hourly ? 24 : 1);
  let warmupSteps;
  if (totalDays < 365) warmupSteps = Math.max(1, Math.round(totalSteps * 0.1));
  else if (totalDays < 1095) warmupSteps = 365 * (hourly ? 24 : 1);
  else warmupSteps = 730 * (hourly ? 24 : 1);
  const remaining = Math.max(totalSteps - warmupSteps, 1);
  const calibSteps = Math.max(1, Math.round(remaining * 0.7));
  const warmupEnd = new Date(d0.getTime() + (warmupSteps - 1) * stepMs);
  const calibStart = new Date(warmupEnd.getTime() + stepMs);
  const calibEnd = new Date(calibStart.getTime() + (calibSteps - 1) * stepMs);
  const validStart = new Date(calibEnd.getTime() + stepMs);
  setWizardTimeValue("#wz-warmup-end", formatSplitValue(warmupEnd));
  setWizardTimeValue("#wz-calib-start", formatSplitValue(calibStart));
  setWizardTimeValue("#wz-calib-end", formatSplitValue(calibEnd));
  setWizardTimeValue("#wz-valid-start", formatSplitValue(validStart));
  const unit = hourly ? "小时" : "天";
  updateObservationHint();
  showToast(`已按连续时段划分：预热${warmupSteps}${unit} / 率定${calibSteps}${unit} / 验证${Math.max(totalSteps - warmupSteps - calibSteps, 0)}${unit}`);
}

// --- auto-compute CFMAX/FAO56 from DEM + SHP ---

async function autoComputeElevation() {
  const shpPath = $("#wz-basin-shp").value.trim();
  const demPath = $("#wz-dem-tif").value.trim() || "";
  if (!shpPath) return;
  try {
    const demParam = demPath ? `&dem_path=${encodeURIComponent(demPath)}` : "";
    const payload = await apiGet(
      `/api/suggest/cfmax-threshold?shp_path=${encodeURIComponent(shpPath)}${demParam}`
    );
    const d = payload.data;
    if (d.suggested_threshold_m) {
      $("#wz-cfmax").value = d.suggested_threshold_m;
      $("#wz-fao-elev").value = d.median_m;
      $("#wz-elev-hint").textContent =
        `DEM 高程范围：${d.min_m} ~ ${d.max_m} m，中位高程：${d.median_m} m。已自动填充 CFMAX 阈值与 FAO56 海拔。`;
    }
  } catch (err) {
    // silent — user can still set manually
    $("#wz-elev-hint").textContent = "自动计算高程失败，请手动输入。";
  }
}

// --- boundary preview ---

function currentBoundaryPreviewQuery() {
  const params = new URLSearchParams();
  const stepHours = isHourlyTimescaleSelected() ? "1" : "24";
  const expectedStart = getWizardTimeValue("#wz-warmup-start");
  const expectedEnd = getWizardTimeValue("#wz-valid-end");
  if (expectedStart || expectedEnd) {
    if (expectedStart) params.set("expected_start", expectedStart);
    if (expectedEnd) params.set("expected_end", expectedEnd);
    params.set("expected_step_hours", stepHours);
    return params;
  }
  if (state.wizardWorkspacePath) {
    params.set("config_path", state.wizardWorkspacePath);
    return params;
  }
  params.set("expected_step_hours", stepHours);
  return params;
}

async function previewBoundary() {
  const csvPath   = $("#wz-boundary-csv").value.trim();
  const dateField = $("#wz-boundary-date").value.trim() || "date";
  const flowField = $("#wz-boundary-flow").value.trim() || "inflow_m3s";
  if (!csvPath) { showToast("请先选择边界入流 csv。", true); return; }
  try {
    const params = currentBoundaryPreviewQuery();
    params.set("path", csvPath);
    params.set("date_field", dateField);
    params.set("flow_field", flowField);
    const payload = await apiGet(`/api/boundary-preview?${params.toString()}`);
    const d = payload.data;
    const suggestedProfile = d.suggested_calibration_mode === "hourly" ? "小时尺度" : "日尺度";
    const detectedStep = d.time_step_hours !== null && d.time_step_hours !== undefined ? `${formatNumber(d.time_step_hours, 0)} 小时` : "未识别";
    const expectedStep = d.expected_time_step_hours !== null && d.expected_time_step_hours !== undefined ? `${formatNumber(d.expected_time_step_hours, 0)} 小时` : "未提供";
    const coverage = d.coverage_ratio !== null && d.coverage_ratio !== undefined
      ? `${formatNumber(d.coverage_ratio * 100, 1)}%`
      : "未与当前项目时段对比";
    const zeroRatio = d.valid_rows ? `${formatNumber((d.zero_count / Math.max(1, d.valid_rows)) * 100, 1)}%` : "—";
    const checks = [
      { label: "识别时间步长", value: detectedStep, status: d.time_step_hours && d.expected_time_step_hours && Number(d.time_step_hours) !== Number(d.expected_time_step_hours) ? "fail" : "ok" },
      { label: "当前项目时间步长", value: expectedStep, status: "ok" },
      { label: "覆盖率", value: coverage, status: d.coverage_ratio !== null && d.coverage_ratio !== undefined && d.coverage_ratio < 0.99 ? "fail" : "ok" },
      { label: "重复时间戳", value: String(d.duplicate_count || 0), status: Number(d.duplicate_count || 0) > 0 ? "fail" : "ok" },
      { label: "负流量记录", value: String(d.negative_count || 0), status: Number(d.negative_count || 0) > 0 ? "fail" : "ok" },
      { label: "零值比例", value: zeroRatio, status: Number(d.valid_rows || 0) > 0 && (Number(d.zero_count || 0) / Math.max(1, Number(d.valid_rows || 0))) >= 0.8 ? "warn" : "ok" },
    ];
    const summary = d.coverage_ratio !== null && d.coverage_ratio !== undefined && d.coverage_ratio < 0.99
      ? "当前边界入流和项目时段相比仍有缺口，建议先补齐覆盖范围后再做率定。"
      : (Number(d.duplicate_count || 0) > 0 || Number(d.negative_count || 0) > 0)
        ? "边界入流存在重复时间戳或负值，建议先清洗数据。"
        : "边界入流预览通过，可继续结合第 7 步输入检查核对覆盖范围。";
    $("#wz-boundary-preview").innerHTML = `
      <div class="hint-box ${Number(d.duplicate_count || 0) > 0 || Number(d.negative_count || 0) > 0 ? "status-fail" : (d.coverage_ratio !== null && d.coverage_ratio !== undefined && d.coverage_ratio < 0.99 ? "status-warn" : "status-ok")}">
        <strong>边界入流概览</strong><br>
        有效记录 ${escapeHtml(String(d.valid_rows || 0))}/${escapeHtml(String(d.total_rows || 0))} 行；
        时间范围 ${escapeHtml(d.date_range?.start || "—")} → ${escapeHtml(d.date_range?.end || "—")}；
        流量范围 ${escapeHtml(formatNumber(d.flow_stats?.min, 2))} ~ ${escapeHtml(formatNumber(d.flow_stats?.max, 2))} m³/s；
        建议模式 ${escapeHtml(suggestedProfile)}。
      </div>
      ${renderEngineeringFocusChecks([{ title: "边界入流预览检查", summary, status: Number(d.duplicate_count || 0) > 0 || Number(d.negative_count || 0) > 0 ? "fail" : (d.coverage_ratio !== null && d.coverage_ratio !== undefined && d.coverage_ratio < 0.99 ? "warn" : "ok"), items: checks }], { title: "边界入流预览检查" })}
    `;
  } catch (err) {
    $("#wz-boundary-preview").innerHTML = `<div class="hint-box status-fail">边界入流预览失败：${escapeHtml(err.message)}</div>`;
    showToast(err.message, true);
  }
}

// --- bootstrap (step 5) ---

async function loadBootstrapStatus() {
  if (!state.wizardWorkspacePath) return;
  try {
    const payload = await apiGet(`/api/data-prep/status?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&prec_source=${encodeURIComponent(getTaskRuntimePrecipSource())}`);
    const items = (payload.data || []).filter(s => GIS_STEP_IDS.has(s.id));
    const host = $("#bootstrap-status");
    if (!items.length) {
      host.innerHTML = '<div class="hint-box">暂无 GIS 步骤状态信息。</div>';
      return;
    }
    host.innerHTML = items.map(s => {
      const isDisabledOptional = s.optional && String(s.message || "").includes("未启用");
      const badge = isDisabledOptional ? "未启用" : (s.done ? "已完成" : "待执行");
      const badgeClass = isDisabledOptional ? "" : (s.done ? "status-ok" : "status-warn");
      return `
      <div class="bootstrap-item ${s.done ? "done" : ""}">
        <span class="status-badge ${badgeClass}">${badge}</span>
        <span>${escapeHtml(s.title || s.id)}</span>
        <small style="margin-left:auto;color:var(--muted)">${escapeHtml(s.message || "")}</small>
      </div>`;
    }).join("");
  } catch (err) {
    showToast(err.message, true);
  }
}

// --- GIS/meteo mode toggle ---

function updateGisMode() {
  const mode = getSelectedRadio("wz-gis-mode");
  $("#wz-gis-auto-panel").classList.toggle("hidden", mode !== "auto");
  $("#wz-gis-import-panel").classList.toggle("hidden", mode !== "import");
}

function syncMeteoModeConstraints() {
  const forceImport = allMeteoSourcesUseLocalTif();
  const pipelineRadio = document.querySelector('input[name="wz-meteo-mode"][value="pipeline"]');
  const importRadio = document.querySelector('input[name="wz-meteo-mode"][value="import"]');
  const pipelineCard = pipelineRadio?.closest(".radio-card");
  if (pipelineRadio) pipelineRadio.disabled = forceImport;
  if (pipelineCard) {
    pipelineCard.classList.toggle("disabled", forceImport);
    pipelineCard.title = forceImport ? "当降水、气温、蒸散发三项都来自本地栅格时，请在本步直接导入本地目录。" : "";
    pipelineCard.style.opacity = forceImport ? "0.55" : "";
    pipelineCard.style.pointerEvents = forceImport ? "none" : "";
  }
  if (forceImport && importRadio) {
    importRadio.closest(".radio-card-group")?.querySelectorAll(".radio-card").forEach(card => card.classList.remove("selected"));
    importRadio.checked = true;
    importRadio.closest(".radio-card")?.classList.add("selected");
  }
}

function updateMeteoMode() {
  syncMeteoModeConstraints();
  const mode = getSelectedRadio("wz-meteo-mode");
  $("#wz-meteo-pipeline-panel").classList.toggle("hidden", mode !== "pipeline");
  $("#wz-meteo-import-panel").classList.toggle("hidden", mode !== "import");
  updateMeteoModeHint();
  renderEra5ApiPanel();
}

function stopMeteoImportPolling() {
  if (state.meteoImportPollTimer) {
    clearInterval(state.meteoImportPollTimer);
    state.meteoImportPollTimer = null;
  }
}

function updateMeteoImportUi(task) {
  const hint = $("#wz-import-meteo-hint");
  const logBox = $("#wz-import-meteo-log");
  const button = $("#wz-import-meteo-btn");
  if (!hint || !logBox || !button || !task) return;

  const progress = task.ui_progress || {};
  const logs = task.output || [];
  logBox.style.display = logs.length ? "" : "none";
  setLogBoxContent(logBox, logs.slice(-80), "wizard:import-log");

  if (task.status === "running") {
    const total = Number(progress.total || 0);
    const current = Number(progress.current || 0);
    const label = progress.label || "导入";
    const itemCurrent = Number(progress.item_current || 0);
    const itemTotal = Number(progress.item_total || 0);
    const ts = progress.timestamp ? ` · 当前时间 ${progress.timestamp}` : "";
    hint.textContent = total > 0
      ? `${progress.stage || "正在导入"}：总进度 ${current}/${total}；${label} ${itemCurrent}/${itemTotal}${ts}`
      : (progress.stage || "正在准备导入，请稍候...");
    hint.className = "hint-box status-warn";
    button.disabled = true;
    button.textContent = "正在导入...";
    return;
  }

  button.disabled = false;
  button.textContent = "验证并导入";
  const result = task.result || {};
  if (task.status === "completed") {
    const issues = [...(result.validation_errors || []), ...(result.validation_warnings || [])];
    const modeLabel = result.preparation_mode_label || "本地栅格导入";
    const sourceDirs = result.source_dirs || {};
    const targetDirs = result.target_dirs || {};
    const pathLines = ["prec", "temp", "evap"].map(key => {
      const label = key === "prec" ? "降水" : key === "temp" ? "气温" : "蒸散发";
      const sourceDir = String(sourceDirs[key] || "").trim();
      const targetDir = String(targetDirs[key] || "").trim();
      if (!sourceDir && !targetDir) return "";
      const parts = [];
      if (sourceDir) parts.push(`来源 <code>${escapeHtml(shortPath(sourceDir))}</code>`);
      if (targetDir) parts.push(`写入 <code>${escapeHtml(shortPath(targetDir))}</code>`);
      return `${label}：${parts.join(" → ")}`;
    }).filter(Boolean);
    hint.innerHTML = `${escapeHtml(modeLabel)}完成：降水 ${escapeHtml(String(result.prec_count || 0))} 文件、气温 ${escapeHtml(String(result.temp_count || 0))} 文件、蒸散 ${escapeHtml(String(result.evap_count || 0))} 文件；按时间顺序导入。${escapeHtml(result.aligned ? "网格已一致。" : "已自动裁剪对齐到 DEM 网格。")}${result.validation_ok ? "" : ` 当前仍有问题：${escapeHtml(issues.slice(0, 2).join("；") || "请到第 7 步继续检查。")}`}${pathLines.length ? `<div style="margin-top:8px">${pathLines.join("<br>")}</div>` : ""}`;
    hint.className = `hint-box ${result.validation_ok ? "status-ok" : "status-warn"}`;
  } else {
    const lastLine = logs.length ? logs[logs.length - 1] : "导入失败，请检查目录与文件名格式。";
    hint.textContent = lastLine;
    hint.className = "hint-box status-fail";
  }
}

function findCurrentMeteoImportTask({ runningOnly = false } = {}) {
  if (!state.wizardWorkspacePath) return null;
  const target = String(state.wizardWorkspacePath).trim();
  return state.tasks.find(task =>
    task.task_type === "meteo_import" &&
    String(task.config_path || "").trim() === target &&
    (!runningOnly || task.status === "running")
  ) || null;
}

function findCurrentPrepTask({ runningOnly = false } = {}) {
  if (!state.wizardWorkspacePath) return null;
  const target = String(state.wizardWorkspacePath).trim();
  return state.tasks.find(task =>
    task.task_type === "data_prep" &&
    String(task.config_path || "").trim() === target &&
    (!runningOnly || task.status === "running")
  ) || null;
}

function stopForwardSimPolling() {
  if (state.forwardSimPollTimer) {
    clearInterval(state.forwardSimPollTimer);
    state.forwardSimPollTimer = null;
  }
}

function isForwardSimTaskForCurrentRun(task, sourceRunPath = "") {
  const currentRunPath = String(state._runData?.run?.path || "").trim();
  const taskSourceRunPath = String(sourceRunPath || task?.run_path || "").trim();
  return Boolean(currentRunPath && taskSourceRunPath && samePath(currentRunPath, taskSourceRunPath));
}

function findCurrentForwardSimTask({ runningOnly = false } = {}) {
  const runPath = String(state._runData?.run?.path || "").trim();
  if (!runPath) return null;
  return state.tasks.find(task =>
    task.task_type === "forward_sim" &&
    String(task.run_path || "").trim() === runPath &&
    (!runningOnly || task.status === "running")
  ) || null;
}

function updateForwardSimUi(task) {
  const hint = $("#resim-hint");
  const logBox = $("#resim-log");
  const btn = $("#btn-resimulate");
  if (!hint || !logBox || !btn || !task) return;
  const logs = task.output || [];
  const elapsed = task.created_at ? Math.max(0, Math.round(Date.now() / 1000 - Number(task.created_at))) : null;
  logBox.style.display = logs.length ? "" : "none";
  setLogBoxContent(logBox, logs.slice(-40), "results:resim-log");
  if (task.status === "running") {
    const stage = task.ui_progress?.stage || "正在保存并重算当前结果";
    hint.style.display = "";
    hint.textContent = `${stage}${elapsed !== null ? ` · 已耗时 ${formatDurationSeconds(elapsed)}` : ""}`;
    hint.className = "hint-box status-warn";
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  if (task.status === "completed" && task.result) {
    const m = task.result.metrics || {};
    hint.style.display = "";
    hint.textContent = task.result.run_path
      ? `保存完成：已生成新结果，率定纳什效率系数=${formatNumber(m.nse_cal, 4)}，验证纳什效率系数=${formatNumber(m.nse_val, 4)}`
      : `模拟完成：率定纳什效率系数=${formatNumber(m.nse_cal, 4)}，验证纳什效率系数=${formatNumber(m.nse_val, 4)}`;
    hint.className = "hint-box status-ok";
  } else if (task.status === "failed") {
    const lastLine = logs.length ? logs[logs.length - 1] : "保存并重算失败。";
    hint.style.display = "";
    hint.textContent = lastLine;
    hint.className = "hint-box status-fail";
  }
}

function applyForwardSimulationResult(result) {
  if (!result) return;
  const newSeries = {
    dates: result.dates, q_sim: result.q_sim, q_obs: result.q_obs,
    q_rain: result.q_rain, q_snow: result.q_snow, q_ice: result.q_ice,
    q_boundary_inflow: result.q_boundary_inflow,
    residuals: result.q_sim.map((s, i) => (s != null && result.q_obs[i] != null) ? s - result.q_obs[i] : null),
  };
  renderCharts({ series: newSeries });
  const m = result.metrics || {};
  updateMetricsStrip(
    { nse: m.nse_cal, kge: m.kge_cal, pbias: m.pbias_cal },
    { nse: m.nse_val },
    state._runData.metadata,
  );
  updateCompareSummary();
}

async function pollForwardSimulationTask(taskId, sourceRunPath = "") {
  if (!taskId) return;
  state.activeForwardSimTaskId = taskId;
  state.activeForwardSimSourceRunPath = String(sourceRunPath || "").trim();
  stopForwardSimPolling();

  const tick = async () => {
    try {
      const payload = await apiGet("/api/tasks");
      state.tasks = payload.data || [];
      renderTasks();
      updateCounts();
      const task = state.tasks.find(item => item.id === taskId);
      if (!task) return;
      const taskSourceRunPath = String(task.run_path || state.activeForwardSimSourceRunPath || "").trim();
      if (isForwardSimTaskForCurrentRun(task, taskSourceRunPath)) {
        updateForwardSimUi(task);
      }
      if (task.status !== "running") {
        stopForwardSimPolling();
        state.activeForwardSimTaskId = "";
        state.activeForwardSimSourceRunPath = "";
        if (task.status === "completed" && task.result) {
          if (task.result.run_path && isForwardSimTaskForCurrentRun(task, taskSourceRunPath)) {
            await loadRuns().catch(() => {});
            await openLatestRunAndSwitch(task.result.run_path, { workspacePath: task.result.workspace_config || state.wizardWorkspacePath || "" });
          } else if (!task.result.run_path && isForwardSimTaskForCurrentRun(task, taskSourceRunPath)) {
            applyForwardSimulationResult(task.result);
          } else {
            showToast("保存并重算已完成，可在任务列表中查看结果。");
          }
        }
      }
    } catch (err) {
      stopForwardSimPolling();
      const hint = $("#resim-hint");
      const btn = $("#btn-resimulate");
      if (hint) {
        hint.style.display = "";
        hint.textContent = err.message;
        hint.className = "hint-box status-fail";
      }
      if (btn) btn.disabled = false;
      state.activeForwardSimSourceRunPath = "";
    }
  };

  await tick();
  state.forwardSimPollTimer = setInterval(() => { tick().catch(() => {}); }, 1500);
}

async function openLatestRunAndSwitch(pathHint = "", { workspacePath = "", createStarterIfMissing = false } = {}) {
  if (workspacePath) {
    setRunWorkspaceFilter(workspacePath);
  }
  setView("results");
  const fallbackWorkspacePath = workspacePath || state.runWorkspaceFilterPath || state.wizardWorkspacePath || "";
  const preferredWorkspaceRuns = (!pathHint && !workspacePath && !state.runWorkspaceFilterPath && state.wizardWorkspacePath)
    ? runsForWorkspace(state.wizardWorkspacePath)
    : [];
  const runPath = pathHint || latestEditableRunPath(preferredWorkspaceRuns.length ? preferredWorkspaceRuns : visibleRuns());
  if (!runPath) {
    if (createStarterIfMissing && fallbackWorkspacePath) {
      await startManualStarterResult({ workspacePath: fallbackWorkspacePath, openWhenDone: true });
      return false;
    }
    clearRunDetail(
      fallbackWorkspacePath
        ? `工作区“${workspaceLabelByPath(fallbackWorkspacePath)}”当前还没有结果。`
        : "当前还没有可打开的结果。"
    );
    showToast(
      fallbackWorkspacePath
        ? `工作区“${workspaceLabelByPath(fallbackWorkspacePath)}”当前还没有结果。`
        : "当前还没有可打开的结果。",
      true
    );
    return false;
  }
  await loadRun(runPath);
  setView("results");
  return true;
}

async function ensureReadyForCalibration({ forceCheck = false } = {}) {
  if (!forceCheck && hasRecentInputCheck({ requireReady: true })) {
    return true;
  }
  const result = await runInputCheck({ force: forceCheck });
  return Boolean(result?.ready_for_calibration);
}

async function pollMeteoImportTask(taskId) {
  if (!taskId) return;
  state.activeMeteoImportTaskId = taskId;
  stopMeteoImportPolling();
  const button = $("#wz-import-meteo-btn");
  if (button) {
    button.disabled = true;
    button.textContent = "正在导入...";
  }

  const tick = async () => {
    try {
      const payload = await apiGet("/api/tasks");
      state.tasks = payload.data || [];
      renderTasks();
      updateCounts();
      const task = state.tasks.find(item => item.id === taskId);
      if (!task) return;
      updateMeteoImportUi(task);
      if (task.status !== "running") {
        stopMeteoImportPolling();
        state.activeMeteoImportTaskId = "";
        await loadPrepSteps();
        await Promise.allSettled([refreshCurrentWorkspaceWorkflow(), refreshCurrentWorkspaceAdvice()]);
        if (state.wizardStep === 7) {
          runInputCheck().catch(() => {});
        }
        if (task.status === "completed") {
          showToast(task.result?.validation_ok ? "气象驱动导入完成" : "气象驱动已导入，请继续检查输入");
        } else {
          showToast("气象驱动导入失败", true);
        }
      }
    } catch (err) {
      stopMeteoImportPolling();
      const hint = $("#wz-import-meteo-hint");
      const btn = $("#wz-import-meteo-btn");
      if (hint) {
        hint.textContent = err.message;
        hint.className = "hint-box status-fail";
      }
      if (btn) {
        btn.disabled = false;
        btn.textContent = "验证并导入";
      }
    }
  };

  await tick();
  state.meteoImportPollTimer = setInterval(() => { tick().catch(() => {}); }, 1500);
}

// --- GIS import ---

async function importGisFiles() {
  if (!state.wizardWorkspacePath) { showToast("请先保存工作区。", true); return; }
  clearInputCheckCache();
  const demPath = $("#wz-import-dem").value.trim();
  const flowaccPath = $("#wz-import-flowacc").value.trim();
  if (!demPath || !flowaccPath) { showToast("请至少选择裁剪后 DEM 和流量累积掩膜文件。", true); return; }
  const hint = $("#wz-import-gis-hint");
  hint.textContent = "正在导入...";
  try {
    const payload = await apiPost("/api/gis/import", {
      config_path: state.wizardWorkspacePath,
      dem_path: demPath,
      flowacc_masked_path: flowaccPath,
      flowdir_path: $("#wz-import-flowdir").value.trim() || "",
      glacier_mask_path: $("#wz-import-glacier").value.trim() || "",
    });
    hint.textContent = payload.data?.message || "导入完成！";
    hint.className = "hint-box status-ok";
    await loadBootstrapStatus();
    await loadPrepSteps();
    await Promise.allSettled([refreshCurrentWorkspaceWorkflow(), refreshCurrentWorkspaceAdvice()]);
    showToast("GIS 文件导入成功");
  } catch (err) {
    hint.textContent = err.message;
    hint.className = "hint-box status-fail";
  }
}

// --- Meteorological import ---

async function importMeteoFiles() {
  if (!state.wizardWorkspacePath) { showToast("请先保存工作区。", true); return; }
  clearInputCheckCache();
  const precDir = $("#wz-import-prec-dir").value.trim() || ((($("#wz-prec-source")?.value || "era5") === "custom_tif") ? ($("#wz-custom-prec-dir")?.value.trim() || "") : "");
  const tempDir = $("#wz-import-temp-dir").value.trim() || ((($("#wz-temp-source")?.value || "era5") === "custom_tif") ? ($("#wz-custom-temp-dir")?.value.trim() || "") : "");
  const evapDir = $("#wz-import-evap-dir").value.trim() || ((($("#wz-pet-source")?.value || "era5_fao56") === "custom_tif") ? ($("#wz-custom-pet-dir")?.value.trim() || "") : "");
  if (!precDir || !tempDir || !evapDir) { showToast("请选择降水、气温和蒸散发三个目录。", true); return; }
  if ($("#wz-import-prec-dir") && !$("#wz-import-prec-dir").value.trim()) $("#wz-import-prec-dir").value = precDir;
  if ($("#wz-import-temp-dir") && !$("#wz-import-temp-dir").value.trim()) $("#wz-import-temp-dir").value = tempDir;
  if ($("#wz-import-evap-dir") && !$("#wz-import-evap-dir").value.trim()) $("#wz-import-evap-dir").value = evapDir;
  const hint = $("#wz-import-meteo-hint");
  const logBox = $("#wz-import-meteo-log");
  hint.textContent = "正在创建导入任务...";
  hint.className = "hint-box status-warn";
  if (logBox) {
    logBox.textContent = "";
    logBox.style.display = "";
  }
  try {
    const payload = await apiPost("/api/meteo/import/start", {
      config_path: state.wizardWorkspacePath,
      prec_source: getEffectiveRuntimePrecipSource(),
      prec_dir: precDir,
      temp_dir: tempDir,
      evap_dir: evapDir,
    });
    const task = payload.task;
    state.activeMeteoImportTaskId = task?.id || "";
    if (task) {
      updateMeteoImportUi(task);
      await loadTasks();
      await pollMeteoImportTask(task.id);
    }
  } catch (err) {
    hint.textContent = err.message;
    hint.className = "hint-box status-fail";
    if (logBox) {
      logBox.style.display = "none";
    }
  }
}

async function runBootstrap() {
  if (!state.wizardWorkspacePath) { showToast("请先保存工作区。", true); return; }
  try {
    const payload = await apiPost("/api/bootstrap/start", {
      config_path: state.wizardWorkspacePath,
      prec_source: getEffectiveRuntimePrecipSource(),
    });
    showToast(`已启动：${payload.task.label}`);
    await loadTasks();
    pollBootstrapLog(payload.task);
  } catch (err) {
    showToast(err.message, true);
  }
}

function pollBootstrapLog(task) {
  const logBox = $("#wz-bootstrap-log");
  const timer = setInterval(async () => {
    try {
      const payload = await apiGet("/api/tasks");
      const t = payload.data.find(x => x.id === task.id);
      if (t) {
        setLogBoxContent(logBox, (t.output || []).slice(-30), "wizard:bootstrap-log");
        if (t.status !== "running") {
          clearInterval(timer);
          await loadBootstrapStatus();
        }
      }
    } catch { clearInterval(timer); }
  }, 2000);
}

// --- prep steps (step 6) ---

function describeEra5Need() {
  const sources = getWizardMeteoSources();
  if (sources.prec === "era5" && sources.pet === "custom_tif" && sources.temp === "custom_tif") {
    return "下面先下载 ERA5 降水，再生成当前项目的降水输入。";
  }
  if (sources.pet !== "custom_tif" && sources.temp === "custom_tif") {
    return "下面先下载计算潜在蒸散发要用的 ERA5 变量，再生成潜在蒸散发。";
  }
  if (sources.pet !== "custom_tif" || sources.temp !== "custom_tif") {
    return "下面按顺序完成 ERA5 下载和结果生成。";
  }
  return "下面按顺序整理本项目需要的气象数据。";
}

function formatPrepDisplayTitle(index, title) {
  const clean = String(title || "").replace(/^\d+\.\s*/, "").trim();
  return `${index}. ${clean}`;
}

function buildVisiblePrepSteps() {
  const rawSteps = state.prepSteps.filter(step => !GIS_STEP_IDS.has(step.id) && !CHECK_STEP_IDS.has(step.id));
  const byId = Object.fromEntries(rawSteps.map(step => [step.id, step]));
  const sources = getWizardMeteoSources();
  const precipMode = getSelectedRadio("wz-precip-mode") || "grid_only";
  const visible = [];
  const add = (id, title, description) => {
    const step = byId[id];
    if (!step) return;
    visible.push({ ...step, displayTitle: title, displayDescription: description });
  };
  const needsEra5Temp = sources.temp !== "custom_tif";
  const needsEra5Pet = sources.pet !== "custom_tif";
  const needsEra5Precip = sources.prec === "era5";
  const needsGridPrec = sources.prec !== "custom_tif";

  if (isHourlyTimescaleSelected()) {
    if (needsEra5Precip || needsEra5Temp || needsEra5Pet) {
      const hourlyDownloadTitle = needsEra5Pet
        ? (needsEra5Temp ? "下载小时 ERA5 变量" : "下载 PET 所需 ERA5 变量")
        : needsEra5Precip
          ? "下载小时 ERA5 降水"
          : "下载小时 ERA5 气温";
      const hourlyDownloadDesc = needsEra5Pet
        ? "下载这一步要用到的 ERA5 原始变量。"
        : needsEra5Precip
          ? "下载小时 ERA5 total_precipitation 原始变量。"
          : "下载小时气温要用的 ERA5 原始变量。";
      const hourlyProcessTitle = needsEra5Pet
        ? (needsEra5Temp ? "生成小时气温和潜在蒸散发" : "生成小时潜在蒸散发")
        : needsEra5Precip
          ? "生成小时 ERA5 降水"
          : "生成小时气温";
      const hourlyProcessDesc = needsEra5Pet
        ? "把下载结果处理成当前项目要用的小时结果。"
        : needsEra5Precip
          ? "把 ERA5 降水下载结果处理成小时降水栅格。"
          : "把下载结果处理成小时气温。";
      add(
        "download_hourly_era5",
        hourlyDownloadTitle,
        hourlyDownloadDesc
      );
      add(
        "process_hourly_era5",
        hourlyProcessTitle,
        hourlyProcessDesc
      );
    }
    if (needsGridPrec) {
      add("process_hourly_prec", "整理小时降水", "把降水整理到当前工程可直接使用的格式。");
    }
    if (precipMode !== "grid_only") {
      add("station_precip_strategy", "分析站点降水资料", "核对站点匹配、时间覆盖、缺测和异常值。");
    }
    add("align_hourly_inputs", "写入工程目录", "把最终要用的气象数据裁剪对齐到 DEM，并写入工程目录。");
    if (precipMode !== "grid_only") {
      add("apply_precip_strategy", "执行降水方案", "按你选的站点订正或泰森方案，生成最终降水输入。");
    }
  } else {
    if (needsEra5Precip || needsEra5Temp || needsEra5Pet) {
      const dailyDownloadTitle = needsEra5Pet
        ? (needsEra5Temp ? "下载 ERA5 变量" : "下载 PET 所需 ERA5 变量")
        : needsEra5Precip
          ? "下载 ERA5 降水"
          : "下载 ERA5 气温";
      const dailyDownloadDesc = needsEra5Pet
        ? "下载这一步要用到的 ERA5 原始变量。"
        : needsEra5Precip
          ? "下载 ERA5 total_precipitation 原始变量。"
          : "下载气温要用的 ERA5 原始变量。";
      const dailyProcessTitle = needsEra5Pet
        ? (needsEra5Temp ? "生成日尺度气温和潜在蒸散发" : "生成日尺度潜在蒸散发")
        : "生成日尺度气温";
      const dailyProcessDesc = needsEra5Pet
        ? "把下载结果处理成当前项目要用的日尺度结果。"
        : "把下载结果处理成日尺度气温。";
      add(
        "download_era5",
        dailyDownloadTitle,
        dailyDownloadDesc
      );
      if (needsEra5Temp || needsEra5Pet) {
        add(
          "process_era5",
          dailyProcessTitle,
          dailyProcessDesc
        );
      }
    }
    if (needsGridPrec) {
      add("process_prec", "整理降水", "把降水整理到当前工程可直接使用的格式。");
    }
    if (precipMode !== "grid_only") {
      add("station_precip_strategy", "分析站点降水资料", "核对站点匹配、时间覆盖、缺测和异常值。");
    }
    add("align_inputs", "写入工程目录", "把最终要用的气象数据裁剪对齐到 DEM，并写入工程目录。");
    if (precipMode !== "grid_only") {
      add("apply_precip_strategy", "执行降水方案", "按你选的站点订正或泰森方案，生成最终降水输入。");
    }
  }

  return visible.map((step, index) => ({
    ...step,
    displayTitle: formatPrepDisplayTitle(index + 1, step.displayTitle || step.title),
    displayDescription: step.displayDescription || step.description || "",
  }));
}

function updatePrepPanelSummary(steps) {
  const hint = $("#wz-pipeline-meteo-hint");
  if (!hint) return;
  const sources = getWizardMeteoSources();
  const precText = sources.prec === "custom_tif"
    ? "本地栅格"
    : sources.prec === "era5"
      ? "ERA5 自动下载"
      : sources.prec === "cmfd"
        ? "CMFD 本地原始文件"
        : "MSWEP 本地原始文件";
  hint.textContent =
    `当前流程：降水用${precText}，`
    + `气温用${sources.temp === "custom_tif" ? "本地栅格" : "ERA5"}，`
    + `潜在蒸散发用${sources.pet === "custom_tif" ? "本地栅格" : "ERA5+FAO56"}。`
    + describeEra5Need();
  hint.className = "hint-box status-ok";
}

function renderEra5ApiPanel() {
  const hint = $("#wz-era5-api-hint");
  const actions = $("#wz-era5-api-actions");
  const mode = getSelectedRadio("wz-meteo-mode");
  if (!hint || !actions) return;
  if (mode !== "pipeline" || !wizardNeedsEra5Download()) {
    hint.style.display = "none";
    actions.style.display = "none";
    return;
  }
  const sources = getWizardMeteoSources();
  const petOnly = sources.pet !== "custom_tif" && sources.temp === "custom_tif";
  const precipOnly = sources.prec === "era5" && sources.temp === "custom_tif" && sources.pet === "custom_tif";
  const status = state.cdsApiStatus;
  hint.style.display = "";
  actions.style.display = "";
  if (!status || status.loading) {
    hint.textContent = "正在检查当前电脑的 ERA5 / CDS API 配置...";
    hint.className = "hint-box status-warn";
    return;
  }
  if (status.error) {
    hint.textContent = `ERA5 API 配置检查失败：${status.error}`;
    hint.className = "hint-box status-fail";
    return;
  }
  const basis = precipOnly
    ? "这一步会下载 ERA5 降水。"
    : petOnly
    ? "这一步会下载计算潜在蒸散发要用的 ERA5 变量。"
    : "这一步会下载当前方案要用的 ERA5 变量。";
  if (status.exists && status.looks_valid !== false) {
    hint.textContent = `${basis} 已检测到 CDS API 配置，可以直接下载。`;
    hint.className = "hint-box status-ok";
    return;
  }
  if (status.exists) {
    hint.textContent = `${basis} 已找到 .cdsapirc，但内容看起来不完整，建议检查里面是否包含 url 和 key。`;
    hint.className = "hint-box status-warn";
    return;
  }
  hint.textContent = `${basis} 这台电脑还没检测到 .cdsapirc，请先配置 CDS API。`;
  hint.className = "hint-box status-warn";
}

async function refreshEra5ApiStatus({ force = false } = {}) {
  const needSignature = currentEra5NeedSignature();
  if (!wizardNeedsEra5Download()) {
    state.cdsApiStatus = null;
    state.cdsApiNeedSignature = "";
    renderEra5ApiPanel();
    return;
  }
  if (!force && state.cdsApiStatus && state.cdsApiNeedSignature === needSignature) {
    renderEra5ApiPanel();
    return;
  }
  const requestId = ++state.activeCdsApiRequestId;
  state.cdsApiNeedSignature = needSignature;
  state.cdsApiStatus = { loading: true };
  renderEra5ApiPanel();
  try {
    const payload = await apiGet("/api/cdsapi/status");
    if (requestId !== state.activeCdsApiRequestId) return;
    state.cdsApiStatus = payload.data || {};
  } catch (err) {
    if (requestId !== state.activeCdsApiRequestId) return;
    state.cdsApiStatus = { error: err.message };
  }
  renderEra5ApiPanel();
}

function formatPrepBlockedMessage(status, visibleSteps) {
  const blockedBy = Array.isArray(status.blocked_by) ? status.blocked_by : [];
  if (!blockedBy.length) return String(status.message || "尚未检测。");
  const labels = blockedBy.map(depId => {
    if (GIS_STEP_IDS.has(depId)) return "第 5 步地理数据";
    const step = visibleSteps.find(item => item.id === depId) || state.prepSteps.find(item => item.id === depId);
    return String(step?.displayTitle || step?.title || depId).replace(/^\d+\.\s*/, "").trim();
  });
  return `依赖未满足：请先完成 ${labels.join("、")}。`;
}

async function loadPrepSteps() {
  if (!state.wizardWorkspacePath) return;
  try {
    const [stepsP, statusP] = await Promise.all([
      apiGet(`/api/data-prep/steps?config_path=${encodeURIComponent(state.wizardWorkspacePath)}`),
      apiGet(`/api/data-prep/status?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&prec_source=${encodeURIComponent(getTaskRuntimePrecipSource())}`),
    ]);
    state.prepSteps  = stepsP.data || [];
    state.prepStatus = Object.fromEntries((statusP.data || []).map(i => [i.id, i]));
    renderPrepSteps();
  } catch (err) {
    showToast(err.message, true);
  }
}

function handleTaskPrecipSourceChange() {
  clearInputCheckCache();
  refreshCalibrationControls();
  if (!state.wizardWorkspacePath) return;
  Promise.allSettled([
    loadBootstrapStatus(),
    loadPrepSteps(),
    refreshCurrentWorkspaceWorkflow(),
    refreshCurrentWorkspaceAdvice(),
  ]).catch(() => {});
}

function renderPrepSteps() {
  const host = $("#prep-step-list");
  renderEra5ApiPanel();
  refreshEra5ApiStatus().catch(() => {});
  if (!state.wizardWorkspacePath) {
    host.innerHTML = '<div class="hint-box">先选择或创建工作区。</div>';
    return;
  }
  const steps = buildVisiblePrepSteps();
  updatePrepPanelSummary(steps);
  if (!steps.length) {
    host.innerHTML = '<div class="hint-box">当前工作区无需额外气象准备步骤。</div>';
    return;
  }
  host.innerHTML = steps.map(step => {
    const status = state.prepStatus[step.id] || {};
    const running = Boolean(status.running);
    const blocked = (status.blocked_by || []).length > 0;
    const txt = running ? "执行中" : status.done ? "已完成" : blocked ? "依赖未满足" : status.manual ? "需补充资料" : "待执行";
    const canOverwrite = Boolean(step.supports_overwrite && status.done && !blocked && !step.manual && !running);
    const message = running
      ? String(status.message || "正在执行，请看下方日志。")
      : blocked ? formatPrepBlockedMessage(status, steps) : String(status.message || "尚未检测。");
    return `
      <div class="prep-step">
        <div class="prep-step-head">
          <div>
            <strong>${escapeHtml(step.displayTitle || step.title)}</strong>
            <div class="panel-note">${escapeHtml(step.displayDescription || step.description || "")}</div>
          </div>
          <span class="status-badge ${status.done ? "status-ok" : blocked ? "status-fail" : "status-warn"}">${escapeHtml(txt)}</span>
        </div>
        <div class="hint-box">${escapeHtml(message)}</div>
        <div class="prep-step-actions">
          ${!step.manual ? `<button class="ghost-button" data-run-step="${escapeHtml(step.id)}" ${(blocked || running) ? "disabled" : ""}>${running ? "执行中..." : status.done ? "重新运行" : "运行此步"}</button>` : ""}
          ${canOverwrite ? `<button class="ghost-button" data-run-step-overwrite="${escapeHtml(step.id)}">覆盖重跑</button>` : ""}
        </div>
      </div>`;
  }).join("");
}

function stopPrepTaskPolling() {
  if (state.prepTaskPollTimer) {
    clearInterval(state.prepTaskPollTimer);
    state.prepTaskPollTimer = null;
  }
}

function updatePrepTaskUi(task) {
  const hint = $("#wz-pipeline-task-hint");
  const logBox = $("#wz-pipeline-task-log");
  if (!hint || !logBox || !task) return;
  const progress = task.ui_progress || {};
  const logs = task.output || [];
  const label = progress.label || task.step_title || task.label || "数据处理";
  const stage = progress.stage || (task.status === "running" ? "正在执行" : task.status === "completed" ? "已完成" : "执行失败");
  const current = Number(progress.current || 0);
  const total = Number(progress.total || 0);
  hint.style.display = "";
  hint.textContent = total > 0 ? `${stage}：${label}（${current}/${total}）` : `${stage}：${label}`;
  hint.className = `hint-box ${task.status === "completed" ? "status-ok" : task.status === "failed" ? "status-fail" : "status-warn"}`;
  if (logs.length) {
    logBox.style.display = "";
    setLogBoxContent(logBox, logs.slice(-120), "wizard:pipeline-log");
  } else {
    logBox.style.display = "none";
  }
}

async function pollPrepTask(taskId) {
  if (!taskId) return;
  state.activePrepTaskId = taskId;
  stopPrepTaskPolling();
  const tick = async () => {
    try {
      const payload = await apiGet("/api/tasks");
      state.tasks = payload.data || [];
      renderTasks();
      updateCounts();
      const task = state.tasks.find(item => item.id === taskId);
      if (!task) return;
      updatePrepTaskUi(task);
      if (task.status !== "running") {
        stopPrepTaskPolling();
        state.activePrepTaskId = "";
        await loadPrepSteps();
        await Promise.allSettled([refreshCurrentWorkspaceWorkflow(), refreshCurrentWorkspaceAdvice()]);
        if (state.wizardStep === 7) runInputCheck().catch(() => {});
        showToast(task.status === "completed" ? "按步骤处理已完成" : "按步骤处理执行失败", task.status !== "completed");
      }
    } catch (err) {
      stopPrepTaskPolling();
      state.activePrepTaskId = "";
      const hint = $("#wz-pipeline-task-hint");
      if (hint) {
        hint.style.display = "";
        hint.textContent = err.message;
        hint.className = "hint-box status-fail";
      }
    }
  };
  await tick();
  state.prepTaskPollTimer = setInterval(() => { tick().catch(() => {}); }, 1500);
}

async function runPrepStep(stepId, { overwrite = false } = {}) {
  if (!state.wizardWorkspacePath) return;
  try {
    if (overwrite && !confirm(`将覆盖步骤「${stepId}」已生成的结果文件，是否继续？`)) {
      return;
    }
    const payload = await apiPost("/api/data-prep/start", {
      config_path: state.wizardWorkspacePath,
      step_id: stepId,
      prec_source: getEffectiveRuntimePrecipSource(),
      overwrite,
    });
    showToast(`已启动：${payload.task.label}`);
    await loadTasks();
    if (payload.task) {
      state.prepStatus[stepId] = {
        ...(state.prepStatus[stepId] || {}),
        running: true,
        message: "正在执行，请看下方日志。",
      };
      renderPrepSteps();
      updatePrepTaskUi(payload.task);
      await pollPrepTask(payload.task.id);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

// --- input check (step 7) ---

async function runInputCheck({ force = false, detail = false, stage = "calibration" } = {}) {
  if (!state.wizardWorkspacePath) { showToast("请先保存工作区。", true); return; }
  const host = $("#wz-check-results");
  const runningImport = findCurrentMeteoImportTask({ runningOnly: true });
  if (runningImport) {
    const progress = runningImport.ui_progress || {};
    const stage = progress.stage || "气象驱动导入";
    const current = Number(progress.current || 0);
    const total = Number(progress.total || 0);
    const label = progress.label || "";
    const itemCurrent = Number(progress.item_current || 0);
    const itemTotal = Number(progress.item_total || 0);
    const ts = progress.timestamp ? ` 当前时间：${escapeHtml(progress.timestamp)}。` : "";
    const logs = (runningImport.output || []).slice(-20).join("\n");
    host.innerHTML = `
      <div class="hint-box status-warn" style="margin-bottom:12px">
        <strong>当前正在导入气象驱动，暂不执行输入检查。</strong><br>
        ${escapeHtml(stage)}${total > 0 ? `：总进度 ${current}/${total}` : ""}${label ? `；${escapeHtml(label)} ${itemCurrent}/${itemTotal}` : ""}。${ts}
        导入完成后会自动重新检查。
      </div>
      ${logs ? `<div class="task-output-box">${escapeHtml(logs)}</div>` : ""}
    `;
    return null;
  }
  if (!force && hasRecentInputCheck({ stage })) {
    host.innerHTML = state.lastInputCheck.html || host.innerHTML;
    return state.lastInputCheck.result;
  }
  const checkStartedAt = Date.now();
  let checkStage = "基础配置检查";
  let checkTimer = null;
  const renderChecking = () => {
    const elapsed = Math.max(0, Math.floor((Date.now() - checkStartedAt) / 1000));
    const longDetail = checkStage === "详细输入检查" && elapsed >= 30;
    host.innerHTML = `
      <div class="hint-box input-check-progress ${longDetail ? "status-warn" : ""}">
        <div class="input-check-stage"><strong>${escapeHtml(checkStage)}</strong><span>已用时 ${elapsed} 秒</span></div>
        <div>${longDetail ? "正在执行详细输入检查，系统正在读取气象栅格、流域边界和可选冰川数据。数据量较大时可能需要数分钟，请勿关闭页面。" : "正在检查当前工作区输入，请稍候。"}</div>
      </div>
    `;
  };
  renderChecking();
  try {
    checkTimer = setInterval(renderChecking, 1000);
    const validationResp = await apiGet(`/api/config/validate?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&stage=${encodeURIComponent(stage)}&prec_source=${encodeURIComponent(getTaskRuntimePrecipSource())}`);
    const runtimePrecSource = getTaskRuntimePrecipSource();
    checkStage = "详细输入检查";
    renderChecking();
    const detailResp = (detail && stage === "calibration")
      ? await apiGet(`/api/workspace/detailed-check?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&prec_source=${encodeURIComponent(runtimePrecSource)}`)
      : { data: null };
    checkStage = "建议生成";
    renderChecking();
    const adviceResp = (detail && stage === "calibration")
      ? await apiGet(`/api/workspace/advice?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&prec_source=${encodeURIComponent(runtimePrecSource)}`)
      : { data: state.currentWorkspaceAdvice || null };
    if (checkTimer) clearInterval(checkTimer);
    checkTimer = null;
    const validation = validationResp.data || {};
    const detailData = detailResp.data;
    const advice = adviceResp.data;
    renderStationPrecipCheckOverview(validation);
    const comp = {
      ready: Boolean(validation.valid),
      ready_for_calibration: Boolean(validation.valid),
      missing: validation.missing || [],
      warnings: validation.warnings || [],
    };
    if (stage === "calibration") {
      const previousWorkflow = state.currentWorkspaceWorkflow || {};
      const totalSteps = Number(previousWorkflow.total_steps || 0);
      const fallbackCompleted = totalSteps
        ? Math.max(0, Math.min(Number(previousWorkflow.completed_count || 0), totalSteps - 1))
        : Number(previousWorkflow.completed_count || 0);
      const pendingSteps = comp.ready_for_calibration
        ? []
        : Array.from(new Set([...(Array.isArray(previousWorkflow.steps_remaining) ? previousWorkflow.steps_remaining : []), 7]))
            .sort((left, right) => Number(left) - Number(right));
      state.currentWorkspaceWorkflow = {
        ...previousWorkflow,
        ready_for_calibration: comp.ready_for_calibration,
        pending_validation: !comp.ready_for_calibration,
        next_step: comp.ready_for_calibration ? null : 7,
        completed_count: comp.ready_for_calibration ? (totalSteps || Number(previousWorkflow.completed_count || 0)) : fallbackCompleted,
        completion_ratio: totalSteps
          ? ((comp.ready_for_calibration ? totalSteps : fallbackCompleted) / totalSteps)
          : Number(previousWorkflow.completion_ratio || 0),
        steps_remaining: pendingSteps,
        missing: [...comp.missing],
        warnings: [...comp.warnings],
        missing_count: comp.missing.length,
        warning_count: comp.warnings.length,
      };
      if (detail && advice) state.currentWorkspaceAdvice = advice;
      updateSidebar();
      refreshCalibrationControls();
    }

    let html = "";
    html += renderInputTimeSummary(validation.input_time_summary);
    const readyHeadline = stage === "calibration"
      ? "所有率定所需数据已就位，可以进入率定！"
      : stage === "quick_test"
    ? "输入预核算所需数据已就位，可以进行限定时段前向计算。"
        : "所有手调/重算所需运行时数据已就位，可以继续前向重算。";

    // overall status
    if (comp.ready) {
      html += `<div class="hint-box status-ok" style="margin-bottom:12px"><strong>${readyHeadline}</strong></div>`;
    } else {
      const missingItems = (comp.missing || []).map(m => `<li>${escapeHtml(m)}${renderIssueJumpButton(m, 7)}</li>`).join("");
      html += `<div class="hint-box status-fail" style="margin-bottom:12px"><strong>以下数据缺失或配置不完整：</strong><ul>${missingItems || "<li>请完成前序步骤</li>"}</ul></div>`;
    }

    if (comp.warnings && comp.warnings.length > 0) {
      const warnItems = comp.warnings.map(w => `<li>${escapeHtml(w)}${renderIssueJumpButton(w, 7)}</li>`).join("");
      html += `<div class="hint-box status-warn" style="margin-bottom:12px"><strong>注意事项：</strong><ul>${warnItems}</ul></div>`;
    }

    if (validation.event_windows && window.HBVStudioEventMode?.renderEventWindowSummary) {
      html += window.HBVStudioEventMode.renderEventWindowSummary(validation.event_windows, {
        escapeHtml,
        statusClass: focusStatusClass,
      });
    }

    if (validation.focus_checks?.length) {
      html += `<div style="margin-bottom:12px"><strong style="display:block;margin-bottom:8px">专项工程检查</strong>${renderEngineeringFocusChecks(validation.focus_checks, { title: "专项工程检查" })}</div>`;
    }

    if (detail && stage === "calibration" && detailData?.reasonableness_checks?.length) {
      html += `<div style="margin-bottom:12px"><strong style="display:block;margin-bottom:8px">数值合理性检查</strong>${renderEngineeringFocusChecks(detailData.reasonableness_checks, { title: "数值合理性检查", emptyText: "暂无数值合理性检查。" })}</div>`;
    }

    if (detail && stage === "calibration" && advice?.recommendations?.length) {
      const items = advice.recommendations.slice(0, 4).map(item => {
        const target = inferIssueTarget(item.detail, item.target_step || 7);
        const stepBtn = target ? ` <button class="ghost-button" data-go-step="${escapeHtml(target.step)}" data-go-selector="${escapeHtml(target.selector || "")}" style="padding:4px 10px;font-size:12px">定位</button>` : "";
        return `<li><strong>${escapeHtml(item.title)}</strong>：${escapeHtml(item.detail)}${stepBtn}</li>`;
      }).join("");
      html += `<div class="hint-box ${comp.ready ? "status-ok" : "status-warn"}" style="margin-bottom:12px"><strong>智能建议：</strong><ul>${items}</ul></div>`;
    }

    if (detail && detailData) {
      const groups = {};
      for (const item of (detailData.summary || [])) {
        const g = item.group || "其他";
        if (!groups[g]) groups[g] = [];
        groups[g].push(item);
      }
      html += '<div class="check-detail-table">';
      for (const [groupName, items] of Object.entries(groups)) {
        html += `<div class="check-group-title">${escapeHtml(groupName)}</div>`;
        for (const item of items) {
          const okClass = item.ok === true ? "status-ok" : item.ok === false ? "status-fail" : "";
          html += `<div class="check-row ${okClass}">
            <span class="check-label">${escapeHtml(item.label)}</span>
            <span class="check-value">${escapeHtml(String(item.value))}</span>
          </div>`;
        }
      }
      html += '</div>';
    } else {
      html += '<div class="hint-box">当前显示的是输入检查概览。需要逐项明细时，再点击“运行检查”。</div>';
    }

    host.innerHTML = html;
    state.lastInputCheck = {
      configPath: String(state.wizardWorkspacePath),
      precipSource: String(getTaskRuntimePrecipSource()),
      stage: String(stage || "calibration"),
      checkedAt: Date.now(),
      result: comp,
      html,
    };
    await refreshCurrentWorkspaceWorkflow().catch(() => {});
    return comp;
  } catch (err) {
    if (checkTimer) clearInterval(checkTimer);
    const elapsed = Math.max(0, Math.floor((Date.now() - checkStartedAt) / 1000));
    host.innerHTML = `<div class="hint-box status-fail">检查失败：${escapeHtml(err.message)}<br>失败阶段：${escapeHtml(checkStage)}；已用时 ${elapsed} 秒。</div>`;
    return null;
  }
}

// ===============================================================
//  DASHBOARD
// ===============================================================

function renderWorkspaceCards() {
  const host = $("#workspace-card-list");
  if (!state.workspaces.length) {
    state.dashboardWorkspaceLayout = null;
    state.dashboardLayoutPath = "";
    host.innerHTML = '<div class="hint-box">还没有工作区。点击上方按钮新建流域项目，或从模板复制。</div>';
    return;
  }
  host.innerHTML = state.workspaces.map(w => `
    <div class="workspace-card ${state.dashboardLayoutPath === w.path ? "selected" : ""}" data-workspace-path="${escapeHtml(w.path)}">
      <div class="workspace-card-info" style="flex:1;min-width:0">
        <div class="list-item-head">
          <strong>${escapeHtml(w.flow_name || w.name)}</strong>
          <div style="display:flex;gap:6px;align-items:center">
            ${profileBadge(w.calibration_mode)}
            ${w.workflow?.ready_for_calibration
              ? '<span class="status-badge status-ok">可率定</span>'
              : w.workflow?.pending_validation
                ? '<span class="status-badge status-warn">待检查</span>'
                : '<span class="status-badge status-warn">待完善</span>'}
            <button class="delete-ws-btn" data-delete-path="${escapeHtml(w.path)}" title="删除工作区">&times;</button>
          </div>
        </div>
        <small>${escapeHtml(objectLabels[w.object_type] || "未定义对象")}</small>
        <small>${escapeHtml(`步骤 ${w.workflow?.completed_count || 0}/${w.workflow?.total_steps || 0} · 下一步 ${workspaceNextStepText(w.workflow)}${w.workflow?.missing_count ? ` · 缺项 ${w.workflow.missing_count}` : ""}`)}</small>
        <div class="workspace-card-meta">
          <span>配置位置</span><code>${escapeHtml(shortPath(w.display_path || w.path) || "待保存")}</code>
          <span>运行目录</span><code>${escapeHtml(shortPath(w.runtime_display_path || w.workspace_root || "") || "待第 1 步保存后生成")}</code>
        </div>
        <div class="workspace-card-actions">
          <button class="ghost-button" data-preview-workspace="${escapeHtml(w.path)}">目录结构</button>
          <button class="ghost-button" data-view-workspace-runs="${escapeHtml(w.path)}">查看结果</button>
          <button class="ghost-button" data-open-workspace="${escapeHtml(w.path)}">进入向导</button>
        </div>
      </div>
    </div>
  `).join("");
}

function renderTemplates() {
  const host = $("#template-list");
  if (!state.templates.length) {
    host.innerHTML = '<div class="hint-box">未发现模板。</div>';
    return;
  }
  host.innerHTML = state.templates.map(t => `
    <div class="list-item">
      <div class="list-item-head">
        <strong>${escapeHtml(t.title)}</strong>
        ${profileBadge(t.calibration_mode)}
      </div>
      <small>${escapeHtml(t.description || t.display_path)}</small>
      <small>${escapeHtml(objectLabels[t.object_type] || "未定义对象")}</small>
      <div class="action-row">
        <button class="ghost-button" data-template-instantiate="${escapeHtml(t.id)}">复制为工作区</button>
        ${t.id === "tuotuohe-daily-builtin" ? '<button class="ghost-button" data-template-sync="tuotuohe">同步历史数据</button>' : ""}
      </div>
    </div>
  `).join("");
}

// ===============================================================
//  CALIBRATION
// ===============================================================

function syncObjectiveModeCards(value = "") {
  const mode = String(value || $("#task-objective-mode")?.value || CURRENT_OBJECTIVE_FAMILY).trim() || CURRENT_OBJECTIVE_FAMILY;
  const select = $("#task-objective-mode");
  if (select && select.value !== mode) select.value = mode;
  document.querySelectorAll('input[name="task-objective-mode-radio"]').forEach(input => {
    const checked = input.value === mode;
    input.checked = checked;
    input.closest(".radio-card")?.classList.toggle("selected", checked);
  });
}

function setObjectiveMode(value) {
  const mode = String(value || CURRENT_OBJECTIVE_FAMILY).trim() || CURRENT_OBJECTIVE_FAMILY;
  syncObjectiveModeCards(mode);
  refreshCalibrationControls();
}

function toggleCalibrationMethodFields() {
  const kind = $("#task-kind")?.value || "calibration";
  const method = $("#task-method")?.value || "de";
  const hasPreset = Boolean($("#task-init-preset")?.value);
  const isCalibration = kind === "calibration" || kind === "debug_calibration";
  const show = (selector, visible) => {
    const el = $(selector);
    if (el) el.classList.toggle("hidden", !visible);
  };
  show("#task-method-group", isCalibration);
  const profile = state.currentWorkspace?.率定模式 || "daily";
  show("#task-objective-mode-group", isCalibration);
  show("#task-param-bounds-profile-group", isCalibration && profile === "daily");
  show("#task-mc-samples-group", isCalibration && method !== "de");
  show("#task-init-preset-group", isCalibration);
  show("#task-init-bound-shrink-group", isCalibration && hasPreset);
  syncObjectiveModeCards();
}

function refreshCalibrationControls() {
  toggleCalibrationMethodFields();
  renderTaskPresetContextHint();
  updateCalibrationGuidance();
}

async function startCalibration() {
  const kind = $("#task-kind").value;
  const method = $("#task-method").value;
  const objectiveMode = $("#task-objective-mode")?.value || "daily_unified_professional_v1";
  const initPresetId = $("#task-init-preset").value;
  const quickTest = kind === "quick_test";
  const quickDays = Number($("#task-quick-days").value) || 30;
  const debugDays = (!quickTest && kind === "debug_calibration") ? quickDays : 0;
  try {
    if (kind === "self_check") {
      const payload = await apiPost("/api/self-check/start", {});
      showToast(`已启动：${payload.task.label}`);
    } else {
      if (!state.wizardWorkspacePath) { showToast("请先选择工作区。", true); return; }
      const validationStage = quickTest ? "quick_test" : "calibration";
      const ready = await ensureWorkspaceReadyForExecution(state.wizardWorkspacePath, { restoreView: "calibration", stage: validationStage });
      if (!ready) {
        showToast("输入检查未通过，已跳转到第 7 步。", true);
        return;
      }
      const payload = await apiPost("/api/calibration/start", {
        config_path: state.wizardWorkspacePath,
        calibration_mode: state.currentWorkspace?.率定模式 || "daily",
        objective_mode: objectiveMode,
        prec_source: getTaskRuntimePrecipSource(),
        glacier_mode: $("#task-glacier-mode").value,
        workers: Number($("#task-workers").value) || 4,
        maxiter: Number($("#task-maxiter").value) || 24,
        popsize: Number($("#task-popsize").value) || 6,
        seed: Number($("#task-seed").value) || 42,
        method,
        mc_samples: Number($("#task-mc-samples").value) || 300,
        param_bounds_profile: $("#task-param-bounds-profile")?.value || "qtp_alpine_default",
        init_preset_id: initPresetId,
        init_bound_shrink: Number($("#task-init-bound-shrink").value) || 0,
        debug_days: debugDays,
        quick_test: quickTest,
        quick_days: quickDays,
        refine_enabled: Boolean($("#task-refine-enabled")?.checked),
        refine_maxiter: Math.max(0, Number($("#task-refine-maxiter")?.value) || 0),
      });
      showToast(`已启动：${payload.task.label}`);
    }
    await loadTasks();
  } catch (err) {
    showToast(err.message, true);
  }
}

function applyRecommendedCalibrationSettings() {
  const rec = state.currentWorkspaceAdvice?.calibration;
  if (!rec) {
    showToast("当前没有可用的推荐设置。", true);
    return;
  }
  if ($("#task-kind")) {
    $("#task-kind").value = "calibration";
  }
  if ($("#task-method")) $("#task-method").value = rec.method || "mc_screen_de";
  if ($("#task-workers")) $("#task-workers").value = rec.workers || 4;
  if ($("#task-maxiter")) $("#task-maxiter").value = rec.maxiter || 24;
  if ($("#task-popsize")) $("#task-popsize").value = rec.popsize || 6;
  if ($("#task-mc-samples")) $("#task-mc-samples").value = rec.mc_samples || 300;
  if ($("#task-param-bounds-profile")) $("#task-param-bounds-profile").value = rec.param_bounds_profile || "qtp_alpine_default";
  if ($("#task-init-bound-shrink")) $("#task-init-bound-shrink").value = rec.init_bound_shrink > 0 ? rec.init_bound_shrink : 0.25;
  refreshCalibrationControls();
  showToast(`已应用推荐设置：${rec.method_label}`);
}

// ===============================================================
//  RESULTS
// ===============================================================

function selectedManualPreset() {
  const presetId = $("#manual-preset-select")?.value || "";
  return state.runManualPresets.find(p => p.id === presetId) || null;
}

function applyManualPresetToCurrentRun(preset) {
  if (!preset || !state._runParams || !state._runOrigParams) return;
  const params = preset.params || {};
  state._runParams = { ...state._runParams, ...params };
  Object.entries(params).forEach(([name, value]) => {
    const slider = $(`[data-param-slider="${name}"]`);
    const input = $(`[data-param-input="${name}"]`);
    if (slider) slider.value = value;
    if (input) input.value = value;
    const item = slider?.closest(".param-slider-item");
    if (item) item.classList.toggle("changed", Math.abs(Number(value) - Number(state._runOrigParams[name])) > 1e-8);
  });
  const hint = $("#resim-hint");
  hint.style.display = "";
  const mismatchText = manualPresetContextWarning(preset);
  hint.textContent = `已载入参数集：${preset.name}${preset.params_adjusted ? "（已按约束自动修正）" : ""}${mismatchText ? `。${mismatchText}` : ""}`;
  hint.className = `hint-box ${mismatchText ? "status-warn" : "status-ok"}`;
  updateManualChangeSummary();
}

async function saveCurrentManualPreset() {
  if (!state._runData || !state._runParams || !isStudioEditableRun(state._runData)) {
    showToast("当前结果不支持保存手调参数集。", true);
    return;
  }
  const configPath = getRunManualPresetConfigPath();
  const name = $("#manual-preset-name").value.trim();
  if (!configPath) {
    showToast("缺少工作区配置路径，无法保存参数集。", true);
    return;
  }
  if (!name) {
    showToast("请输入参数集名称。", true);
    return;
  }
  const payload = await apiPost("/api/manual-preset/save", {
    config_path: configPath,
    scope: $("#manual-preset-scope")?.value || "workspace",
    run_path: state._runData.run?.path || "",
    calibration_profile: state._runData?.metadata?.calibration_profile || state.currentWorkspace?.率定模式 || "daily",
    objective_mode: effectiveObjectiveMode(state._runData?.metadata || {}) || "daily_unified_professional_v1",
    param_bounds_profile: state._runData?.metadata?.param_bounds_profile || state._runData?.metadata?.parameter_profile?.bounds_profile || $("#task-param-bounds-profile")?.value || "qtp_alpine_default",
    prec_source: String(
      state._runData?.metadata?.data_sources?.runtime_prec_source
      || state._runData?.metadata?.data_sources?.prec_source
      || state._runData?.metadata?.data_sources?.configured_precip_source
      || getTaskRuntimePrecipSource()
      || "era5"
    ).trim().toLowerCase(),
    glacier_mode: state._runData?.metadata?.data_sources?.glacier_mode || $("#task-glacier-mode")?.value || "inline",
    name,
    params: state._runParams,
  });
  await loadRunManualPresets(configPath, { silent: true });
  if (samePath(configPath, getTaskManualPresetConfigPath())) {
    await loadTaskManualPresets(configPath, {
      silent: true,
      calibrationProfile: state.currentWorkspace?.率定模式 || state._runData?.metadata?.calibration_profile || "daily",
    });
  }
  const savedId = payload.data?.preset?.id || "";
  if ($("#manual-preset-select")) $("#manual-preset-select").value = savedId;
  if (samePath(configPath, getTaskManualPresetConfigPath()) && $("#task-init-preset")) $("#task-init-preset").value = savedId;
  updateManualPresetControls();
  refreshCalibrationControls();
  renderManualPresetDiff();
  const scopeLabel = String(payload.data?.preset?.scope || "workspace") === "global" ? "公共参数库" : "当前工作区";
  showToast(`已保存到${scopeLabel}：${name}${payload.data?.preset?.params_adjusted ? "（已按约束自动修正）" : ""}`);
}

async function loadSelectedManualPreset() {
  const preset = selectedManualPreset();
  if (!preset) {
    showToast("请先选择一个参数集。", true);
    return;
  }
  $("#manual-preset-name").value = preset.name || "";
  applyManualPresetToCurrentRun(preset);
  renderManualPresetDiff();
  showToast(`已载入参数集：${preset.name}${preset.params_adjusted ? "（已按约束自动修正）" : ""}`);
}

async function deleteSelectedManualPreset() {
  const preset = selectedManualPreset();
  const configPath = getRunManualPresetConfigPath();
  if (!preset || !configPath) {
    showToast("请先选择一个参数集。", true);
    return;
  }
  if (!window.confirm(`确定删除参数集“${preset.name}”吗？`)) return;
  await apiPost("/api/manual-preset/delete", { config_path: configPath, preset_id: preset.id, scope: preset.scope || "workspace" });
  const deletedPresetId = String(preset.id || "").trim();
  await loadRunManualPresets(configPath, { silent: true });
  if (samePath(configPath, getTaskManualPresetConfigPath())) {
    await loadTaskManualPresets(configPath, {
      silent: true,
      calibrationProfile: state.currentWorkspace?.率定模式 || state._runData?.metadata?.calibration_profile || "daily",
    });
  }
  if (deletedPresetId && deletedPresetId === String(state.comparePresetId || "").trim()) {
    clearManualPresetComparison({ silent: true });
  }
  if ($("#manual-preset-name")) $("#manual-preset-name").value = "";
  refreshCalibrationControls();
  renderManualPresetDiff();
  showToast(`已删除参数集：${preset.name}`);
}

function renderRunList() {
  const host = $("#run-list");
  const selectedRunPath = currentSelectedRunPath();
  const workspaceFilterPath = String(state.runWorkspaceFilterPath || "").trim();
  const workspaceRunCount = workspaceFilterPath ? runsForWorkspace(workspaceFilterPath).length : state.runs.length;
  renderResultsFilterToolbar();
  if (!state.runs.length) {
    host.innerHTML = '<div class="hint-box">暂无结果。</div>';
    const hint = $("#results-entry-hint");
    if (hint) {
      hint.textContent = manualStarterWorkspacePath()
        ? `工作区“${workspaceLabelByPath(manualStarterWorkspacePath())}”当前还没有结果。可直接生成“手调起点”，不必先做正式率定。`
        : "还没有结果。选择工作区后，可直接生成“手调起点”进入手动调参。";
      hint.className = "hint-box status-warn";
    }
    updateManualStarterButtons();
    return;
  }
  const runs = visibleRuns();
  if (!runs.length) {
    const workspaceEmpty = Boolean(workspaceFilterPath) && workspaceRunCount === 0;
    host.innerHTML = workspaceEmpty
      ? `<div class="hint-box status-warn">工作区“${escapeHtml(workspaceLabelByPath(workspaceFilterPath))}”当前还没有结果。可直接生成“手调起点”，或启动正式率定。</div>`
      : '<div class="hint-box status-warn">当前筛选下没有结果。可切换筛选条件，或先回到“全部结果”查看。</div>';
    const hint = $("#results-entry-hint");
    if (hint) {
      hint.textContent = workspaceEmpty
        ? `工作区“${workspaceLabelByPath(workspaceFilterPath)}”当前还没有结果。可直接生成“手调起点”继续。`
        : workspaceFilterPath
          ? `工作区“${workspaceLabelByPath(workspaceFilterPath)}”有结果，但当前筛选条件下没有匹配项。可放宽筛选后再查看。`
          : "当前筛选下没有结果。可切换筛选条件后再查看。";
      hint.className = "hint-box status-warn";
    }
    updateManualStarterButtons();
    return;
  }
  const hint = $("#results-entry-hint");
  if (hint && !state.currentRun) {
    hint.textContent = state.runWorkspaceFilterPath
      ? `先从左侧选择“${workspaceLabelByPath(state.runWorkspaceFilterPath)}”的一个结果。选中后即可在下方继续手动调参并重算结果。`
      : "先从左侧选择一个结果，或点击“打开最新结果”。选中后即可在下方手动调参并重算结果。";
    hint.className = "hint-box";
  }
  updateManualStarterButtons();
  host.innerHTML = runs.map(r => {
    const hydro = r.hydrology_summary || {};
    return `
    <article class="list-item run-card ${selectedRunPath && samePath(selectedRunPath, r.path) ? "selected" : ""}" data-run-path="${escapeHtml(r.path)}">
      <div class="run-card-topline">
        <span class="run-card-kicker">${escapeHtml(runWorkspaceName(r))}</span>
        <div class="run-card-badges">
          ${runTypeBadge(r)}
          ${objectiveVersionBadge(r)}
          ${r.studio_compatible ? '<span class="status-badge status-ok">可继续手调</span>' : '<span class="status-badge status-warn">仅查看</span>'}
        </div>
      </div>
      <div class="list-item-head run-card-head">
        <div class="run-card-titlebox">
          <strong>${escapeHtml(runDisplayName(r))}</strong>
          ${runDisplaySubtitle(r) ? `<small class="run-card-subtitle">${escapeHtml(runDisplaySubtitle(r))}</small>` : ""}
        </div>
        <div class="run-card-score">
          <span>NSE 率定 / 验证</span>
          <strong>${escapeHtml(`${formatNumber(r?.nse_cal, 4)} / ${formatNumber(r?.nse_val, 4)}`)}</strong>
          <small>${escapeHtml(`PBIAS ${formatMetricValue(r?.pbias_cal, 2, "%")} / ${formatMetricValue(r?.pbias_val, 2, "%")}`)}</small>
        </div>
      </div>
      <div class="run-card-meta">
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "workflow_label_zh", "单流程参数率定"))}</span>
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "objective_label_zh", "综合水文目标函数"))}</span>
        <span class="run-meta-pill">${escapeHtml(hydrologySummaryValue(hydro, "flow_status_zh", "径流拟合未达标"))}</span>
      </div>
      <div class="workspace-card-actions run-card-actions">
        ${r.workspace_config && !samePath(r.workspace_config, state.runWorkspaceFilterPath) ? `<button class="ghost-button" data-filter-run-workspace="${escapeHtml(r.workspace_config)}">只看本工作区</button>` : ""}
        <button class="ghost-button" data-rename-run="${escapeHtml(r.path)}">${r.has_custom_title ? "修改标题" : "命名结果"}</button>
        <button class="ghost-button" data-open-run-dir="${escapeHtml(r.path)}">打开目录</button>
        <button class="ghost-button" data-delete-run="${escapeHtml(r.path)}">删除</button>
      </div>
    </article>
  `;
  }).join("");
}

function renderRunDetail(data) {
  const meta = data.metadata || {};
  const metrics = meta.metrics || {};
  const cal = metrics.calibration || {};
  const val = metrics.validation || {};
  const editable = isStudioEditableRun(data);
  const manual = Boolean(meta?.manual_result?.enabled);
  const starter = Boolean(meta?.starter_result?.enabled);
  const optimization = meta.optimization || {};
  const debugWindow = optimization.debug_window || {};
  const initPresetLabel = optimization.init_params_file ? shortPath(optimization.init_params_file) : "\u2014";
  const replayInfo = replayCompatibilityInfo(meta);
  const requestedObjective = requestedObjectiveMode(meta);
  const effectiveObjective = effectiveObjectiveMode(meta);

  // Store for re-simulation
  state._runData = data;
  state._runParams = editable ? { ...(meta.optimized_params || {}) } : null;
  state._runOrigParams = editable ? { ...(meta.optimized_params || {}) } : null;
  nextCompareRequestId();
  state.compareSeries = null;
  state.compareMetrics = null;
  state.compareLabel = "";
  state.comparePresetId = "";
  state.compareAdjusted = false;
  state.selectedRunPath = String(data?.run?.path || data?.path || state.selectedRunPath || "").trim();
  state.currentRun = data;
  state.lastRunExportPath = "";

  renderRunEngineeringSummary(data);
  updateMetricsStrip(cal, val, meta);
  configureRunExportPanel(data);
  renderCharts(data);
  updateManualGroupToolbar();
  renderParamSliders(data);
  $("#btn-resimulate").disabled = !editable;
  $("#btn-reset-params").disabled = !editable;
  $("#resim-hint").style.display = editable ? "none" : "";
  $("#resim-hint").textContent = editable ? "" : "该结果不是可调结果，只支持查看，不支持滑块重算。";
  $("#resim-hint").className = editable ? "hint-box" : "hint-box status-warn";
  if ($("#resim-log")) {
    $("#resim-log").textContent = "";
    $("#resim-log").style.display = "none";
  }
  updateManualPresetControls();
  if ($("#manual-preset-name")) $("#manual-preset-name").value = "";
  renderManualPresetDiff();
  updateCompareSummary();
  updateManualStarterButtons();

  const summary = hydrologySummaryFor(data, meta);
  const timeCfg = meta.time_config || {};
  const seriesRange = data.series_range || {};
  const stepHours = currentRunStepHours(data);
  const reportPath = summary.diagnostics_detail_path || summary.diagnostics_detail_display_path || "";
  const reportDisplayPath = summary.diagnostics_detail_display_path || summary.diagnostics_detail_path || "";
  const componentReport = componentFractionReport(meta);
  const floodRows = floodEventRows(meta);
  const restartRows = restartStateRows(meta);
  const metadataHtml = [
    metadataSection("水文结果摘要", [
      ["率定流程", hydrologySummaryValue(summary, "workflow_label_zh", "单流程参数率定")],
      ["评分标准", hydrologySummaryValue(summary, "objective_label_zh", "综合水文目标函数")],
      ["参数范围", meta.param_bounds_profile_label || meta.parameter_profile?.bounds_profile_label || PARAM_BOUNDS_PROFILE_LABELS[meta.param_bounds_profile] || PARAM_BOUNDS_PROFILE_LABELS[meta.parameter_profile?.bounds_profile] || "当前运行范围"],
      ["径流拟合", hydrologySummaryValue(summary, "flow_status_zh")],
      ["三水源构成", componentFractionText(componentReport)],
      ["口径", componentFractionBasisText(componentReport)],
      ["结果说明", hydrologySummaryValue(summary, "diagnostics_detail_note", "水文模拟结果说明已保存至本地结果目录。")],
      ["说明文件", reportDisplayPath ? shortPath(reportDisplayPath) : "结果目录内生成"],
      ["运行时间", meta.run_time],
      ["结果类型", data.run?.run_type_label || RUN_TYPE_LABELS[data.run?.run_type] || (manual ? "手调结果" : starter ? "手调起点" : data.run?.run_origin === "studio" ? "可调结果" : "查看结果")],
      ["所属工作区", workspaceLabelByPath(meta.workspace_config || data.run?.workspace_config)],
      ["率定时段", timeRangeText(timeCfg.calib_start, timeCfg.calib_end, stepHours)],
      ["验证时段", timeRangeText(timeCfg.valid_start, timeCfg.valid_end, stepHours)],
    ]),
    restartRows.length ? metadataSection("状态重启与预报", restartRows) : "",
    floodRows.length ? metadataSection("洪水事件评价", floodRows) : "",
    `
      <section class="metadata-section">
        <h4>本地过程复核报告</h4>
        <div class="hint-box">页面显示摘要信息。详细水文过程复核已写入本地结果目录，供专业复核使用。</div>
        <div class="workspace-card-actions" style="margin-top:10px">
          ${data?.run?.path ? `<button class="ghost-button" data-run-detail-open-dir="${escapeHtml(data.run.path)}">打开结果目录</button>` : ""}
          ${reportPath ? `<button class="ghost-button" data-run-detail-open-report="${escapeHtml(reportPath)}">打开过程复核报告</button>` : ""}
        </div>
      </section>
    `,
  ].join("");
  $("#metadata-grid").innerHTML = metadataHtml;
  const hint = $("#results-entry-hint");
  const periodHint = runMetricsText(data.run);
  if (hint) {
    const baseText = editable
      ? manual
        ? "当前结果来自一次手调后的保存结果。继续改参数后，再点“保存并重算”，左侧会新增一条结果记录，图表和指标也会切换到最新结果。"
        : starter
          ? "当前结果是系统生成的手调起点。直接在下方改参数值，再点“保存并重算”，左侧会新增一条结果记录。"
          : "当前结果支持继续手调。直接在下方改参数值，再点“保存并重算”，左侧会新增一条结果记录，图表和指标也会切换到最新结果。"
      : "当前结果只支持查看。若要手动调参，请选择一个可调结果。";
    const legacyWarmupWarning = seriesRange.warmup_start && seriesRange.actual_start && !seriesRange.warmup_covered
      ? `当前这个历史结果实际从 ${compactTimeText(seriesRange.actual_start, stepHours)} 开始保存，未包含预热段；如果需要导出或查看预热期，请用新版程序重新生成一次结果。`
      : "";
    hint.textContent = [
      baseText,
      periodHint ? `当前图表与导出都覆盖${periodHint}。` : "",
      legacyWarmupWarning,
      "结果页只显示简要水文解释；完整过程复核请打开本地过程复核报告。",
    ].filter(Boolean).join(" ");
    hint.className = `hint-box ${(editable && !legacyWarmupWarning) ? "status-ok" : "status-warn"}`.trim();
  }
}

function updateMetricsStrip(cal, val, meta) {
  const floodEval = floodEventEvaluation(meta);
  const items = [
    { l: "模式", v: profileLabel(meta.calibration_profile) },
    { l: "步长", v: `${formatNumber(meta.time_config?.time_step_hours, 0)} 小时` },
    { l: "率定纳什效率系数", v: formatNumber(cal.nse, 4) },
    { l: "验证纳什效率系数", v: formatNumber(val.nse, 4) },
    { l: "率定 KGE 综合效率", v: formatNumber(cal.kge, 4) },
    { l: "率定水量偏差", v: `${formatNumber(cal.pbias, 2)}%` },
  ];
  if (floodEval?.enabled) {
    items.push({ l: "洪水事件", v: floodEventStatusText(floodEval) });
    items.push({ l: "事件目标值", v: floodEventObjectiveText(floodEval) });
  }
  $("#results-metric-strip").innerHTML = items.map(i => `<div class="metric-tile"><span>${i.l}</span><strong>${i.v}</strong></div>`).join("");
}

function renderRunExportFields() {
  const host = $("#run-export-fields");
  if (!host) return;
  const fields = RUN_EXPORT_FIELDS.filter(field => field.key !== "q_boundary_inflow" || boundaryEnabledFromMeta(state.currentRun?.metadata || {}));
  host.innerHTML = fields.map(field => `
    <label class="phase-chip" style="cursor:pointer">
      <input type="checkbox" data-run-export-field="${escapeHtml(field.key)}" ${field.checked ? "checked" : ""} style="margin-right:6px">
      ${escapeHtml(field.label)}
    </label>
  `).join("");
}

function currentRunStepHours(data = state.currentRun) {
  const hours = Number(data?.metadata?.time_config?.time_step_hours || data?.run?.time_step_hours || 24);
  return hours <= 1.5 ? 1 : 24;
}

function configureRunExportPanel(data) {
  renderRunExportFields();
  const exportBtn = $("#btn-run-export");
  const openBtn = $("#btn-open-export-file");
  const hint = $("#run-export-hint");
  const startInput = $("#run-export-start");
  const endInput = $("#run-export-end");
  const hourly = currentRunStepHours(data) <= 1.5;
  const startValue = data?.metadata?.time_config?.warmup_start || data?.metadata?.time_config?.calib_start || data?.series?.dates?.[0] || "";
  const endValue = data?.metadata?.time_config?.valid_end || (data?.series?.dates || []).slice(-1)[0] || "";
  if (startInput) {
    startInput.type = hourly ? "datetime-local" : "date";
    startInput.step = hourly ? "60" : "";
    startInput.value = toWizardInputTimeValue(startValue, hourly);
  }
  if (endInput) {
    endInput.type = hourly ? "datetime-local" : "date";
    endInput.step = hourly ? "60" : "";
    endInput.value = toWizardInputTimeValue(endValue, hourly);
  }
  if (exportBtn) exportBtn.disabled = !data?.run?.path;
  if (openBtn) openBtn.disabled = !state.lastRunExportPath;
  if (hint) {
    hint.textContent = hourly
      ? "当前结果已保存预热至验证全时段。默认已带入全时段，小时结果会导出到当前结果目录下的“导出”子目录，时间范围按分钟精度填写。"
      : "当前结果已保存预热至验证全时段。默认已带入全时段，日尺度结果会导出到当前结果目录下的“导出”子目录。";
    hint.className = "hint-box";
  }
}

function selectedRunExportFields() {
  return $all("[data-run-export-field]")
    .filter(input => input.checked)
    .map(input => input.dataset.runExportField)
    .filter(Boolean);
}

async function exportCurrentRunExcel() {
  const runPath = String(state.currentRun?.run?.path || "").trim();
  if (!runPath) {
    showToast("请先选择一个结果。", true);
    return;
  }
  const hourly = currentRunStepHours() <= 1.5;
  const fields = selectedRunExportFields();
  if (!fields.length) {
    showToast("请至少勾选一个导出字段。", true);
    return;
  }
  const startValue = fromWizardInputTimeValue($("#run-export-start")?.value || "", hourly);
  const endValue = fromWizardInputTimeValue($("#run-export-end")?.value || "", hourly);
  const payload = await apiPost("/api/run/export-excel", {
    path: runPath,
    start_date: startValue,
    end_date: endValue,
    fields,
  });
  state.lastRunExportPath = payload.data?.path || "";
  if ($("#btn-open-export-file")) $("#btn-open-export-file").disabled = !state.lastRunExportPath;
  if ($("#run-export-hint")) {
    $("#run-export-hint").textContent =
      `已导出 ${payload.data?.row_count || 0} 行到 ${payload.data?.display_path || shortPath(state.lastRunExportPath)}。`;
    $("#run-export-hint").className = "hint-box status-ok";
  }
  showToast(`Excel 已导出：${payload.data?.row_count || 0} 行`);
}

function renderCharts(data) {
  const drawPlot = (id, traces, layout, config) => {
    const host = document.getElementById(id);
    if (!host || !window.Plotly) return;
    try { window.Plotly.purge(host); } catch {}
    host.innerHTML = "";
    Plotly.newPlot(host, traces, layout, config);
  };
  const dates = data.series?.dates || [];
  const plotLayout = {
    margin: { t: 10, r: 10, b: 40, l: 55 },
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    xaxis: { title: "日期" }, yaxis: { title: "流量 m\u00B3/s" },
    legend: { orientation: "h", y: 1.12 },
  };
  const plotCfg = { responsive: true };
  const qIceLabel = "裸冰融化流量";
  const compare = state.compareSeries;
  const boundaryEnabled = boundaryEnabledFromMeta(data?.metadata || {});
  const hydrographTraces = [
    { x: dates, y: data.series?.q_obs || [], name: "实测流量", mode: "lines", line: { color: colors.qObs, width: 1.6 } },
    { x: dates, y: data.series?.q_sim || [], name: "模拟流量", mode: "lines", line: { color: colors.qSim, width: 1.8 } },
  ];
  if (compare?.q_sim?.length) {
    hydrographTraces.push({
      x: compare.dates || dates,
      y: compare.q_sim,
      name: state.compareLabel ? `对比：${state.compareLabel}` : "对比模拟",
      mode: "lines",
      line: { color: "#5b4a3a", width: 1.6, dash: "dash" },
    });
  }
  if (boundaryEnabled) {
    hydrographTraces.push({ x: dates, y: data.series?.q_boundary_inflow || [], name: "边界入流", mode: "lines", line: { color: "#7c5c99", width: 1.2 } });
  }

  drawPlot("hydrograph-chart", hydrographTraces, plotLayout, plotCfg);
  renderFloodEventChart(data?.metadata || {}, plotCfg);

  drawPlot("component-chart", [
    { x: dates, y: data.series?.q_rain || [], name: "降雨产流", mode: "lines", line: { color: colors.qRain } },
    { x: dates, y: data.series?.q_snow || [], name: "融雪流量", mode: "lines", line: { color: colors.qSnow } },
    { x: dates, y: data.series?.q_ice || [],  name: qIceLabel, mode: "lines", line: { color: colors.qIce } },
  ], { ...plotLayout, yaxis: { title: "流量 m\u00B3/s" } }, plotCfg);

  const residualTraces = [
    { x: dates, y: data.series?.residuals || [], name: "当前残差", mode: "lines", line: { color: colors.residual } },
  ];
  if (compare?.residuals?.length) {
    residualTraces.push({
      x: compare.dates || dates,
      y: compare.residuals,
      name: "对比残差",
      mode: "lines",
      line: { color: "#6f6255", width: 1.4, dash: "dash" },
    });
  }
  drawPlot("residual-chart", residualTraces, { ...plotLayout, yaxis: { title: "残差 m\u00B3/s" } }, plotCfg);
}

function renderParamSliders(data) {
  const meta = data.metadata || {};
  if (!isStudioEditableRun(data)) {
    $("#param-sliders").innerHTML = '<div class="hint-box status-warn">该结果缺少继续手调所需的参数边界信息，暂时只能查看，不能手动调参。</div>';
    updateManualPhaseGuide([]);
    updateManualChangeSummary();
    return;
  }
  const params = meta.optimized_params || {};
  const bounds = meta.parameter_profile?.bounds || {};
  const paramNames = Object.keys(params);
  if (!paramNames.length) {
    $("#param-sliders").innerHTML = '<div class="hint-box">无参数信息。</div>';
    updateManualPhaseGuide([]);
    updateManualChangeSummary();
    return;
  }
  updateManualPhaseGuide(paramNames);
  const shownParamNames = manualGroupParamNames(state.manualParamGroup, paramNames);
  if (!shownParamNames.length) {
    $("#param-sliders").innerHTML = '<div class="hint-box status-warn">当前分组没有可调参数，请切换到其他参数组。</div>';
    updateManualChangeSummary();
    return;
  }
  const html = shownParamNames.map(name => {
    const val = params[name];
    const [lo, hi] = bounds[name] || [0, 1];
    const step = Math.max((hi - lo) / 1000, 1e-6);
    const label = PARAM_LABELS[name] || name;
    return `
      <div class="param-slider-item" data-param="${escapeHtml(name)}">
        <div class="param-slider-head">
          <strong>${escapeHtml(name)}</strong>
          <span style="flex:1;margin-left:6px;font-size:11px;color:var(--muted)">${escapeHtml(label)}</span>
          <input class="param-value" type="number" step="${step}" min="${lo}" max="${hi}" value="${val}" data-param-input="${escapeHtml(name)}">
        </div>
        <input type="range" min="${lo}" max="${hi}" step="${step}" value="${val}" data-param-slider="${escapeHtml(name)}">
        <div class="param-slider-bounds"><span>${lo}</span><span>${hi}</span></div>
      </div>`;
  }).join("");
  $("#param-sliders").innerHTML = html;

  // Bind slider ↔ input sync
  $all("[data-param-slider]").forEach(slider => {
    const name = slider.dataset.paramSlider;
    const input = $(`[data-param-input="${name}"]`);
    const item = slider.closest(".param-slider-item");
    const applyValue = numeric => {
      if (!Number.isFinite(numeric)) return;
      state._runParams[name] = numeric;
      item.classList.toggle("changed", Math.abs(numeric - state._runOrigParams[name]) > 1e-8);
      updateManualChangeSummary();
    };
    slider.addEventListener("input", () => {
      const numeric = Number(slider.value);
      if (!Number.isFinite(numeric)) return;
      input.value = numeric.toFixed(6);
      applyValue(numeric);
    });
    input.addEventListener("input", () => {
      const numeric = Number(input.value);
      if (!Number.isFinite(numeric)) return;
      slider.value = numeric;
      applyValue(numeric);
    });
    input.addEventListener("change", () => {
      const numeric = Number(input.value);
      if (!Number.isFinite(numeric)) return;
      slider.value = numeric;
      input.value = numeric.toFixed(6);
      applyValue(numeric);
    });
  });
  updateManualChangeSummary();
}

function resetParamsToOriginal() {
  if (!state._runOrigParams) return;
  state._runParams = { ...state._runOrigParams };
  for (const [name, val] of Object.entries(state._runOrigParams)) {
    const slider = $(`[data-param-slider="${name}"]`);
    const input = $(`[data-param-input="${name}"]`);
    if (slider) slider.value = val;
    if (input) input.value = val;
    const item = slider?.closest(".param-slider-item");
    if (item) item.classList.remove("changed");
  }
  // Restore original charts
  if (state._runData) renderCharts(state._runData);
  const meta = state._runData?.metadata || {};
  const cal = meta.metrics?.calibration || {};
  const val = meta.metrics?.validation || {};
  updateMetricsStrip(cal, val, meta);
  $("#resim-hint").style.display = "none";
  updateManualChangeSummary();
  updateCompareSummary();
}

async function runForwardSimulation() {
  if (!state._runData || !state._runParams || !isStudioEditableRun(state._runData)) {
    showToast("该结果不支持保存并重算。", true);
    return;
  }
  const hint = $("#resim-hint");
  const logBox = $("#resim-log");
  hint.style.display = "";
  hint.textContent = "正在创建保存并重算任务...";
  hint.className = "hint-box status-warn";
  if (logBox) {
    logBox.textContent = "";
    logBox.style.display = "";
  }
  try {
    const payload = await apiPost("/api/simulate/forward/start", {
      run_path: state._runData.run?.path,
      params: state._runParams,
      save_run: true,
    });
    const task = payload.task;
    if (task) {
      updateForwardSimUi(task);
      await loadTasks();
      await pollForwardSimulationTask(task.id, state._runData?.run?.path || "");
    }
  } catch (err) {
    hint.textContent = `模拟失败：${err.message}`;
    hint.className = "hint-box status-fail";
    if (logBox) logBox.style.display = "none";
  }
}

async function compareSelectedManualPresetSimulation() {
  const preset = selectedManualPreset();
  if (!preset) {
    showToast("请先选择一个参数集。", true);
    return;
  }
  if (!state._runData || !isStudioEditableRun(state._runData)) {
    showToast("当前结果不支持参数集对比。", true);
    return;
  }
  const host = $("#manual-compare-summary");
  if (host) {
    host.style.display = "";
    host.className = "hint-box";
    host.textContent = `正在计算参数集“${preset.name}”的对比结果...`;
  }
  const requestId = nextCompareRequestId();
  const runPath = String(state._runData?.run?.path || "").trim();
  const presetId = String(preset.id || "").trim();
  try {
    const payload = await apiPost("/api/simulate/forward", {
      run_path: state._runData.run?.path,
      params: preset.params || {},
    });
    if (requestId !== state.activeCompareRequestId) return;
    if (!samePath(runPath, state._runData?.run?.path || "")) return;
    const currentPresetId = String(selectedManualPreset()?.id || "").trim();
    if (presetId && currentPresetId && presetId !== currentPresetId) return;
    const d = payload.data;
    state.compareLabel = preset.name || "参数集";
    state.comparePresetId = presetId;
    state.compareMetrics = d.metrics || {};
    state.compareAdjusted = Boolean(d.runtime?.params_adjusted);
    state.compareSeries = {
      dates: d.dates || [],
      q_sim: d.q_sim || [],
      residuals: (d.q_sim || []).map((s, i) => (s != null && d.q_obs[i] != null) ? s - d.q_obs[i] : null),
    };
    renderCharts(state._runData);
    updateCompareSummary();
    updateManualPresetControls();
    showToast(`已生成参数集“${preset.name}”的对比曲线。`);
  } catch (err) {
    if (requestId !== state.activeCompareRequestId) return;
    state.compareSeries = null;
    state.compareMetrics = null;
    state.compareLabel = "";
    state.comparePresetId = "";
    state.compareAdjusted = false;
    if (state._runData) {
      renderCharts(state._runData);
      const meta = state._runData?.metadata || {};
      const cal = meta.metrics?.calibration || {};
      const val = meta.metrics?.validation || {};
      updateMetricsStrip(cal, val, meta);
    }
    if (host) {
      host.style.display = "";
      host.className = "hint-box status-fail";
      host.textContent = `参数集对比失败：${err.message}`;
    }
    updateManualPresetControls();
    showToast(err.message, true);
  }
}

// ===============================================================
//  TASKS
// ===============================================================

function taskProgressChartData(history, stageLabel = "") {
  const rows = (history || []).filter(row => Number.isFinite(Number(row?.gen)));
  if (rows.length < 2) return null;
  const gens = rows.map(row => Number(row.gen));
  const nseCal = rows.map(row => Number.isFinite(Number(row.nse_cal)) ? Number(row.nse_cal) : null);
  const nseVal = rows.map(row => Number.isFinite(Number(row.nse_val)) ? Number(row.nse_val) : null);
  const obj = rows.map(row => Number.isFinite(Number(row.obj)) ? Number(row.obj) : null);
  return {
    traces: [
      { x: gens, y: nseCal, name: "率定纳什效率系数", mode: "lines", line: { color: colors.qSim, width: 2 } },
      { x: gens, y: nseVal, name: "验证纳什效率系数", mode: "lines", line: { color: colors.qRain, width: 1.6, dash: "dot" } },
      { x: gens, y: obj, name: "综合评分值", mode: "lines", yaxis: "y2", line: { color: colors.residual, width: 1.6 } },
    ],
    layout: {
      margin: { t: 8, r: 38, b: 28, l: 36 },
      height: 180,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      legend: { orientation: "h", y: 1.18, x: 0, font: { size: 10 } },
      title: stageLabel ? { text: stageLabel, font: { size: 11 } } : undefined,
      xaxis: { title: "迭代 / 样本", tickfont: { size: 10 }, titlefont: { size: 10 } },
      yaxis: { title: "纳什效率系数", tickfont: { size: 10 }, titlefont: { size: 10 } },
      yaxis2: { title: "综合评分值", overlaying: "y", side: "right", tickfont: { size: 10 }, titlefont: { size: 10 } },
    },
  };
}

function renderTaskProgressCharts() {
  if (typeof Plotly === "undefined") return;
  document.querySelectorAll("[data-task-progress-chart]").forEach(host => {
    const taskId = host.dataset.taskProgressChart;
    const stage = host.dataset.taskProgressStage || "global";
    const task = state.tasks.find(item => item.id === taskId);
    const histories = task?.progress?.stages || {};
    const stageHistory = histories?.[stage]?.history || task?.progress?.history || [];
    const chart = taskProgressChartData(stageHistory, taskStageLabel(stage));
    if (!chart) return;
    Plotly.newPlot(host, chart.traces, chart.layout, {
      responsive: true,
      displayModeBar: false,
      staticPlot: true,
    });
  });
}

function renderTasks() {
  renderTaskFilterToolbar();
  const html = visibleTasks().map(t => {
    const isRunning = t.status === "running";
    const progress = t.progress;
    const contextSummary = taskContextSummary(t);
    const summaryLine = taskSummaryLine(t);
    const summaryClass = t.status === "completed" ? "status-ok" : t.status === "failed" ? "status-fail" : "";
    const stageEntries = Object.entries(progress?.stages || {})
      .filter(([, stageInfo]) => (stageInfo?.history || []).length >= 2)
      .sort((a, b) => {
        const order = { mc: 0, global: 1, refine: 2 };
        return (order[a[0]] ?? 99) - (order[b[0]] ?? 99);
      });
    const trendHtml = stageEntries.length
      ? stageEntries.map(([stageName]) =>
        `<div class="chart-host" data-task-progress-chart="${escapeHtml(t.id)}" data-task-progress-stage="${escapeHtml(stageName)}" style="height:180px;margin-top:8px"></div>`
      ).join("")
      : ((progress?.history || []).length >= 2
        ? `<div class="chart-host" data-task-progress-chart="${escapeHtml(t.id)}" data-task-progress-stage="${escapeHtml(progress?.stage || "global")}" style="height:180px;margin-top:8px"></div>`
        : "");
    const progressTitle = isRunning ? "当前阶段" : t.status === "completed" ? "最后进度" : "失败前进度";
    const progressHtml = progress ? `
      <div class="hint-box task-progress-note ${t.status === "completed" ? "status-ok" : t.status === "failed" ? "status-fail" : ""}">
        ${escapeHtml(progressTitle)}：${escapeHtml(taskStageLabel(progress.stage || "global"))}
        ${progress.gen ? ` · 第 ${escapeHtml(progress.gen)}/${escapeHtml(progress.maxiter || "\u2014")} 步` : ""}
        · 率定纳什效率系数 ${escapeHtml(formatNumber(progress.nse_cal, 4))}
        · 验证纳什效率系数 ${escapeHtml(formatNumber(progress.nse_val, 4))}
        · 综合评分值 ${escapeHtml(formatNumber(progress.obj, 4))}
        · 已耗时 ${escapeHtml(formatDurationSeconds(progress.elapsed_sec))}
        ${isRunning && progress.eta_sec !== null && progress.eta_sec !== undefined ? ` · 预计剩余 ${escapeHtml(formatDurationSeconds(progress.eta_sec))}` : ""}
        ${trendHtml}
      </div>` : "";
    return `
    <div class="list-item task-card ${isRunning ? "task-running" : ""}">
      <div class="task-card-topline">
        <span class="task-kicker">${escapeHtml(taskTypeLabel(t.task_type))}</span>
        <span class="task-updated">最近更新 ${escapeHtml(formatDateTime(t.updated_at))}</span>
        <span class="status-badge ${taskStatusClass(t.status)}">${escapeHtml(taskStatusLabel(t.status))}${isRunning ? "..." : ""}</span>
      </div>
      <div class="task-card-hero">
        <div class="task-card-title">
          <strong>${escapeHtml(taskPrimaryTitle(t))}</strong>
          ${contextSummary ? `<small class="task-meta-line">${escapeHtml(contextSummary)}</small>` : ""}
        </div>
      </div>
      ${renderTaskMilestones(t)}
      <div class="hint-box task-summary-box ${summaryClass}">${escapeHtml(summaryLine)}</div>
      ${progressHtml}
      ${renderTaskActions(t)}
      ${taskDebugDetails(t, { lines: isRunning ? 120 : 80 })}
    </div>`;
  }).join("") || '<div class="hint-box">当前筛选下暂无任务。</div>';
  $("#task-list").innerHTML = html;
  restoreVisibleLogViewports("#task-list [data-log-key]");
  renderTaskProgressCharts();
}

// ===============================================================
//  FORECAST RESTART
// ===============================================================

function forecastCandidateRuns() {
  const allowed = new Set(["calibration", "manual_result", "manual_starter", "forecast_restart"]);
  return state.runs.filter(run => {
    const type = runTypeValue(run);
    return Boolean(run?.path) && allowed.has(type);
  });
}

function forecastRunReady(run) {
  if (!run) return false;
  if (run.forecast_source_ready !== undefined) return Boolean(run.forecast_source_ready);
  return Boolean(run.path && run.studio_compatible);
}

function forecastRunReadinessText(run) {
  if (!run) return "未选择源结果";
  if (forecastRunReady(run)) return "可接续";
  if (run.optimized_params_available === false) return "缺少率定参数";
  if (run.state_snapshot_available === false) return "缺少状态快照";
  return "需用新版结果";
}

function selectedForecastRun() {
  const selectedPath = $("#forecast-source-run")?.value || state.forecastSourceRunPath || "";
  return forecastCandidateRuns().find(run => samePath(run.path, selectedPath)) || null;
}

function forecastInputType(run) {
  const stepHours = Number(run?.time_step_hours || run?.time_config?.time_step_hours || 24);
  return stepHours <= 1.5 ? "datetime-local" : "date";
}

function parseForecastTime(value) {
  const raw = String(value || "").trim();
  if (!raw) return null;
  const dateOnly = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]), 0, 0, 0, 0);
  }
  const normalized = raw.replace(" ", "T");
  const dt = new Date(normalized);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function formatForecastInputTime(date, stepHours) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "";
  const pad = value => String(value).padStart(2, "0");
  const y = date.getFullYear();
  const m = pad(date.getMonth() + 1);
  const d = pad(date.getDate());
  if (Number(stepHours || 24) <= 1.5) {
    return `${y}-${m}-${d}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }
  return `${y}-${m}-${d}`;
}

function forecastSuggestedStart(run) {
  const stepHours = Number(run?.time_step_hours || run?.time_config?.time_step_hours || 24);
  const stateTime = run?.state_snapshot_time || run?.time_config?.forecast_end || run?.time_config?.valid_end || run?.time_config?.calib_end || "";
  const dt = parseForecastTime(stateTime);
  if (!dt) return "";
  dt.setMinutes(dt.getMinutes() + Math.round(stepHours * 60));
  return formatForecastInputTime(dt, stepHours);
}

function forecastTimeComparable(value, run) {
  const stepHours = Number(run?.time_step_hours || run?.time_config?.time_step_hours || 24);
  const dt = parseForecastTime(value);
  return dt ? formatForecastInputTime(dt, stepHours) : String(value || "").trim();
}

function renderForecastSourceOptions() {
  const select = $("#forecast-source-run");
  if (!select) return;
  const candidates = forecastCandidateRuns();
  const current = state.forecastSourceRunPath || currentSelectedRunPath() || "";
  let selected = candidates.find(run => samePath(run.path, current));
  if (!selected) selected = candidates.find(forecastRunReady) || candidates[0] || null;
  state.forecastSourceRunPath = selected?.path || "";
  select.disabled = !candidates.length;
  select.innerHTML = candidates.length
    ? candidates.map(run => {
      const label = `${runDisplayName(run)} · ${runTypeLabel(runTypeValue(run))} · ${forecastRunReadinessText(run)}`;
      return `<option value="${escapeHtml(run.path)}" ${samePath(run.path, state.forecastSourceRunPath) ? "selected" : ""}>${escapeHtml(label)}</option>`;
    }).join("")
    : '<option value="">暂无可选源结果</option>';
}

function renderForecastSourceSummary() {
  const host = $("#forecast-source-summary");
  const openBtn = $("#forecast-open-source");
  const startBtn = $("#forecast-start-button");
  const hint = $("#forecast-hint");
  if (!host) return;
  const run = selectedForecastRun();
  if (openBtn) openBtn.disabled = !run?.path;
  if (startBtn) startBtn.disabled = !run?.path || !forecastRunReady(run);
  if (!run) {
    host.innerHTML = '<div class="hint-box status-warn" style="margin-top:12px">当前没有可作为预报起点的率定或手调结果。</div>';
    if (hint) {
      hint.textContent = "完成一次新版率定或手调重算后，可在这里直接接入未来气象驱动。";
      hint.className = "hint-box status-warn";
    }
    return;
  }
  const ready = forecastRunReady(run);
  const stateTime = run.state_snapshot_time || run.time_config?.forecast_end || run.time_config?.valid_end || run.time_config?.calib_end || "";
  const sourceStateTime = run.source_state_snapshot_time || "";
  const sourceType = runTypeLabel(runTypeValue(run));
  const objective = objectiveLabel(run.effective_objective_mode || run.objective_family || run.recorded_objective_family || "");
  const archive = run.forecast_input_archive || {};
  const parameterSource = forecastParameterSourceSummary(run.source_parameter_summary || {}, run);
  const archiveText = forecastArchiveSummaryText(archive, runTypeValue(run) === "forecast_restart" ? "未记录气象归档" : "待本次预报生成");
  const archiveDetail = forecastArchiveDetailText(archive);
  const suggestedStart = forecastSuggestedStart(run);
  host.innerHTML = `
    <div class="forecast-source-card ${ready ? "status-ok" : "status-warn"}">
      <div class="forecast-source-card-head">
        <strong>${escapeHtml(runDisplayName(run))}</strong>
        <span class="status-badge ${ready ? "status-ok" : "status-warn"}">${escapeHtml(forecastRunReadinessText(run))}</span>
      </div>
      <div class="forecast-source-meta">
        <span>结果类型</span><strong>${escapeHtml(sourceType)}</strong>
        <span>计算尺度</span><strong>${escapeHtml(profileLabel(runProfileValue(run)))}</strong>
        <span>状态时间</span><strong>${escapeHtml(stateTime || "未记录")}</strong>
        ${suggestedStart ? `<span>建议起报</span><strong>${escapeHtml(suggestedStart.replace("T", " "))}</strong>` : ""}
        ${sourceStateTime ? `<span>来源状态</span><strong>${escapeHtml(sourceStateTime)}</strong>` : ""}
        <span>目标函数</span><strong>${escapeHtml(objective)}</strong>
        <span>参数来源</span><strong title="${escapeHtml(parameterSource.detail)}">${escapeHtml(parameterSource.value)}</strong>
        <span>预报气象</span><strong title="${escapeHtml(archiveDetail)}">${escapeHtml(archiveText)}</strong>
      </div>
      <small>${escapeHtml(run.workspace_name || runWorkspaceName(run) || "未关联工作区")}</small>
    </div>
  `;
  const inputType = forecastInputType(run);
  ["forecast-start", "forecast-end"].forEach(id => {
    const input = document.getElementById(id);
    if (input && input.type !== inputType) input.type = inputType;
  });
  const startInput = $("#forecast-start");
  if (startInput && suggestedStart && !startInput.value) startInput.value = suggestedStart;
  if (hint) {
    hint.textContent = ready
      ? `预报运行将读取源结果的参数与末端状态，不重新率定；建议从 ${suggestedStart ? suggestedStart.replace("T", " ") : "源状态后一时间步"} 起报。若要从更晚时间起报，需要先补充历史气象强迫滚动更新状态。`
      : "该源结果不能直接接续，请优先使用新版率定、手调结果或已生成状态快照的预报结果。";
    hint.className = `hint-box ${ready ? "status-ok" : "status-warn"}`;
  }
}

function renderForecastTaskList() {
  const host = $("#forecast-task-list");
  if (!host) return;
  const tasks = state.tasks
    .filter(task => task.task_type === "forecast_restart")
    .sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
  if (!tasks.length) {
    host.innerHTML = '<div class="hint-box">暂无连续状态预报任务。</div>';
    return;
  }
  host.innerHTML = tasks.slice(0, 8).map(task => {
    const isRunning = task.status === "running";
    const summaryLine = taskSummaryLine(task);
    const summaryClass = task.status === "completed" ? "status-ok" : task.status === "failed" ? "status-fail" : "";
    return `
      <div class="list-item task-card ${isRunning ? "task-running" : ""}">
        <div class="task-card-topline">
          <span class="task-kicker">${escapeHtml(taskTypeLabel(task.task_type))}</span>
          <span class="task-updated">最近更新 ${escapeHtml(formatDateTime(task.updated_at))}</span>
          <span class="status-badge ${taskStatusClass(task.status)}">${escapeHtml(taskStatusLabel(task.status))}${isRunning ? "..." : ""}</span>
        </div>
        <div class="task-card-title">
          <strong>${escapeHtml(taskPrimaryTitle(task))}</strong>
          ${task.forecast_end ? `<small class="task-meta-line">预报至 ${escapeHtml(task.forecast_end)}</small>` : ""}
        </div>
        ${renderTaskMilestones(task)}
        <div class="hint-box task-summary-box ${summaryClass}">${escapeHtml(summaryLine)}</div>
        ${renderTaskActions(task)}
        ${taskDebugDetails(task, { lines: isRunning ? 80 : 40 })}
      </div>
    `;
  }).join("");
  restoreVisibleLogViewports("#forecast-task-list [data-log-key]");
}

function forecastResultRuns() {
  return state.runs
    .filter(run => runTypeValue(run) === "forecast_restart" && run?.path)
    .sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
}

function selectedForecastResultRun() {
  const selectedPath = $("#forecast-result-run")?.value || state.forecastResultRunPath || "";
  return forecastResultRuns().find(run => samePath(run.path, selectedPath)) || forecastResultRuns()[0] || null;
}

function setForecastResultButtons(run) {
  const hasRun = Boolean(run?.path);
  if ($("#forecast-open-result")) $("#forecast-open-result").disabled = !hasRun;
  if ($("#forecast-open-result-dir")) $("#forecast-open-result-dir").disabled = !hasRun;
  if ($("#forecast-export-excel")) $("#forecast-export-excel").disabled = !hasRun;
  if ($("#forecast-open-export-file")) $("#forecast-open-export-file").disabled = !state.lastForecastExportPath;
}

function renderForecastResultDetail(data = state.forecastResultData) {
  const run = data?.run || selectedForecastResultRun();
  setForecastResultButtons(run);
  if (!window.HBVStudioForecastView) return;
  if (!data?.run?.path) {
    window.HBVStudioForecastView.renderForecastResultEmpty("完成连续状态预报后，将在这里查看过程线、起报依据和输入资料。");
    return;
  }
  window.HBVStudioForecastView.renderForecastResultDetail(data, {
    escapeHtml,
    runDisplayName,
    shortPath,
    timeRangeText,
    forecastArchiveSummaryText,
    forecastArchiveDetailText,
    forecastParameterSourceSummary,
    profileLabel,
  });
}

async function loadForecastResultDetail(path) {
  const targetPath = String(path || "").trim();
  if (!targetPath) return;
  const requestId = nextForecastResultRequestId();
  state.forecastResultRunPath = targetPath;
  state.forecastResultLoadingPath = targetPath;
  state.lastForecastExportPath = "";
  if (window.HBVStudioForecastView) {
    window.HBVStudioForecastView.renderForecastResultLoading("正在读取连续状态预报结果。");
  }
  setForecastResultButtons({ path: targetPath });
  try {
    const payload = await apiGet(`/api/run?path=${encodeURIComponent(targetPath)}`);
    if (requestId !== state.activeForecastResultRequestId || !samePath(targetPath, state.forecastResultRunPath)) return;
    state.forecastResultData = payload.data;
    state.forecastResultLoadingPath = "";
    renderForecastResultDetail(payload.data);
  } catch (err) {
    if (requestId !== state.activeForecastResultRequestId) return;
    state.forecastResultData = null;
    state.forecastResultLoadingPath = "";
    if (window.HBVStudioForecastView) {
      window.HBVStudioForecastView.renderForecastResultEmpty(`预报结果读取失败：${err.message}`);
    }
    setForecastResultButtons(null);
  }
}

function renderForecastResultPanel() {
  const select = $("#forecast-result-run");
  if (!select) return;
  const runs = forecastResultRuns();
  if (!runs.length) {
    state.forecastResultRunPath = "";
    state.forecastResultData = null;
    state.forecastResultLoadingPath = "";
    select.disabled = true;
    select.innerHTML = '<option value="">暂无连续状态预报结果</option>';
    state.lastForecastExportPath = "";
    setForecastResultButtons(null);
    if (window.HBVStudioForecastView) {
      window.HBVStudioForecastView.renderForecastResultEmpty("完成连续状态预报后，将在这里查看过程线、起报依据和输入资料。");
    }
    return;
  }
  let selected = runs.find(run => samePath(run.path, state.forecastResultRunPath)) || runs[0];
  state.forecastResultRunPath = selected.path;
  select.disabled = false;
  select.innerHTML = runs.map(run => `
    <option value="${escapeHtml(run.path)}" ${samePath(run.path, selected.path) ? "selected" : ""}>
      ${escapeHtml(`${runDisplayName(run)} · ${timeRangeText(run.time_config?.forecast_start, run.time_config?.forecast_end, run.time_step_hours || run.time_config?.time_step_hours || 24)}`)}
    </option>
  `).join("");
  setForecastResultButtons(selected);
  if (state.forecastResultData?.run?.path && samePath(state.forecastResultData.run.path, selected.path)) {
    renderForecastResultDetail(state.forecastResultData);
  } else if (samePath(state.forecastResultLoadingPath, selected.path)) {
    if (window.HBVStudioForecastView) {
      window.HBVStudioForecastView.renderForecastResultLoading("正在读取连续状态预报结果。");
    }
  } else {
    loadForecastResultDetail(selected.path).catch(err => showToast(err.message, true));
  }
}

async function openForecastResultAnalysis() {
  const run = selectedForecastResultRun();
  if (!run?.path) return;
  setView("results");
  await loadRun(run.path);
}

async function exportForecastResultExcel() {
  const run = selectedForecastResultRun();
  const data = state.forecastResultData;
  const runPath = String(data?.run?.path || run?.path || "").trim();
  if (!runPath) {
    showToast("当前没有可导出的预报结果。", true);
    return;
  }
  const meta = data?.metadata || {};
  const series = data?.series || {};
  const start = meta.time_config?.forecast_start || meta.forecast_result?.forecast_start || series.dates?.[0] || "";
  const end = meta.time_config?.forecast_end || meta.forecast_result?.forecast_end || (series.dates || []).slice(-1)[0] || "";
  const fields = ["q_sim", "q_rain", "q_snow", "q_ice"];
  if (boundaryEnabledFromMeta(meta)) fields.push("q_boundary_inflow");
  const payload = await apiPost("/api/run/export-excel", {
    path: runPath,
    start_date: start,
    end_date: end,
    fields,
  });
  state.lastForecastExportPath = payload.data?.path || "";
  setForecastResultButtons(run || data?.run);
  const hint = $("#forecast-result-hint");
  if (hint) {
    hint.textContent = `已导出 ${payload.data?.row_count || 0} 行到 ${payload.data?.display_path || shortPath(state.lastForecastExportPath)}。`;
    hint.className = "hint-box status-ok";
  }
  showToast(`预报结果 Excel 已导出：${payload.data?.row_count || 0} 行`);
}

function renderForecastView() {
  if (!$("#forecast-source-run")) return;
  renderForecastSourceOptions();
  renderForecastSourceSummary();
  renderForecastTaskList();
  renderForecastResultPanel();
}

function selectLatestForecastSource() {
  const run = forecastCandidateRuns().find(forecastRunReady) || forecastCandidateRuns()[0] || null;
  if (!run) {
    showToast("当前没有可接续的源结果。", true);
    renderForecastView();
    return;
  }
  state.forecastSourceRunPath = run.path;
  renderForecastView();
}

async function startForecastRestart() {
  const run = selectedForecastRun();
  if (!run) { showToast("请先选择源结果。", true); return; }
  if (!forecastRunReady(run)) { showToast("源结果缺少率定参数或状态快照，不能启动连续状态预报。", true); return; }
  const forecastEnd = $("#forecast-end")?.value.trim() || "";
  const forecastStart = $("#forecast-start")?.value.trim() || "";
  const precDir = $("#forecast-prec-dir")?.value.trim() || "";
  const tempDir = $("#forecast-temp-dir")?.value.trim() || "";
  const evapDir = $("#forecast-evap-dir")?.value.trim() || "";
  if (!forecastEnd) { showToast("请填写预报结束时间。", true); return; }
  const expectedStart = forecastSuggestedStart(run);
  if (forecastStart && expectedStart && forecastTimeComparable(forecastStart, run) !== forecastTimeComparable(expectedStart, run)) {
    showToast(`预报开始时间必须紧接源状态快照，当前应从 ${expectedStart.replace("T", " ")} 起报。`, true);
    return;
  }
  if (!precDir || !tempDir || !evapDir) {
    showToast("请完整选择预报降水、气温和潜在蒸散发栅格目录。", true);
    return;
  }
  const payload = {
    source_run: run.path,
    config_path: run.workspace_config || state.wizardWorkspacePath || "",
    forecast_start: forecastStart,
    forecast_end: forecastEnd,
    forecast_prec_dir: precDir,
    forecast_temp_dir: tempDir,
    forecast_evap_dir: evapDir,
    profile: runProfileValue(run) || state.currentWorkspace?.率定模式 || "",
    objective_mode: run.effective_objective_mode || run.objective_family || run.recorded_objective_family || CURRENT_OBJECTIVE_FAMILY,
    prec_source: "custom_tif",
    glacier_mode: $("#forecast-glacier-mode")?.value || "inline",
  };
  try {
    const response = await apiPost("/api/forecast/restart/start", payload);
    showToast(`已启动：${response.task?.label || "连续状态预报"}`);
    await loadTasks();
    renderForecastView();
  } catch (err) {
    showToast(err.message, true);
  }
}

function handleTaskActionClick(e) {
  const openWorkspaceBtn = e.target.closest("[data-task-open-workspace]");
  if (openWorkspaceBtn) {
    loadWorkspace(openWorkspaceBtn.dataset.taskOpenWorkspace)
      .then(workflow => {
        navigateWizardStep(preferredWorkspaceLandingStep(workflow));
        setView("wizard");
      })
      .catch(er => showToast(er.message, true));
    return true;
  }
  const openResultBtn = e.target.closest("[data-task-open-result]");
  if (openResultBtn) {
    openLatestRunAndSwitch(openResultBtn.dataset.taskOpenResult).catch(er => showToast(er.message, true));
    return true;
  }
  const openRunDirBtn = e.target.closest("[data-task-open-run-dir]");
  if (openRunDirBtn) {
    openLocalPath(openRunDirBtn.dataset.taskOpenRunDir, "结果目录").catch(er => showToast(er.message, true));
    return true;
  }
  const copyTaskLogBtn = e.target.closest("[data-copy-task-log]");
  if (copyTaskLogBtn) {
    copyTextToClipboard(taskLogText(copyTaskLogBtn.dataset.copyTaskLog || ""), "日志").catch(err => showToast(err.message, true));
    return true;
  }
  return false;
}

// ===============================================================
//  DATA LOADING
// ===============================================================

async function loadDashboard() {
  try {
    const p = await apiGet("/api/dashboard");
    state.templates  = p.data.templates  || [];
    state.workspaces = p.data.workspaces || [];
    state.runs       = p.data.runs       || [];
    state.tasks      = p.data.tasks      || [];
  } catch (err) {
    const [templatesP, workspacesP, runsP, tasksP] = await Promise.allSettled([
      apiGet("/api/templates"),
      apiGet("/api/workspaces"),
      apiGet("/api/runs"),
      apiGet("/api/tasks"),
    ]);
    state.templates = templatesP.status === "fulfilled" ? (templatesP.value.data || []) : [];
    state.workspaces = workspacesP.status === "fulfilled" ? (workspacesP.value.data || []) : [];
    state.runs = runsP.status === "fulfilled" ? (runsP.value.data || []) : [];
    state.tasks = tasksP.status === "fulfilled" ? (tasksP.value.data || []) : [];
    if ([templatesP, workspacesP, runsP, tasksP].every(item => item.status !== "fulfilled")) {
      throw err;
    }
    showToast(`首页聚合接口加载失败，已切换为分项加载：${err.message}`, true);
  }
  if (state.dashboardLayoutPath && !state.workspaces.some(w => w.path === state.dashboardLayoutPath)) {
    state.dashboardLayoutPath = "";
    state.dashboardWorkspaceLayout = null;
  }
  renderTemplates();
  renderWorkspaceCards();
  renderDashboardWorkspaceLayout();
  renderRunList();
  renderTasks();
  renderForecastView();
  updateCounts();
  updateSidebar();
  if (state.wizardWorkspacePath && state.workspaces.some(w => w.path === state.wizardWorkspacePath)) {
    previewWorkspaceLayout(state.wizardWorkspacePath, { silent: true }).catch(() => {});
  }
}

async function loadTemplates() {
  const p = await apiGet("/api/templates");
  state.templates = p.data;
  renderTemplates();
  updateCounts();
}

async function loadWorkspaces() {
  const p = await apiGet("/api/workspaces");
  state.workspaces = p.data;
  if (state.dashboardLayoutPath && !state.workspaces.some(w => w.path === state.dashboardLayoutPath)) {
    state.dashboardLayoutPath = "";
    state.dashboardWorkspaceLayout = null;
  }
  renderWorkspaceCards();
  renderDashboardWorkspaceLayout();
  if (state.runs.length) {
    renderRunList();
  }
  updateCounts();
}

async function refreshCurrentWorkspaceWorkflow() {
  if (!state.wizardWorkspacePath) {
    state.currentWorkspaceWorkflow = null;
    updateSidebar();
    refreshCalibrationControls();
    return null;
  }
  const p = await apiGet(`/api/workspace/completeness?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&prec_source=${encodeURIComponent(getTaskRuntimePrecipSource())}`);
  state.currentWorkspaceWorkflow = p.data || null;
  updateSidebar();
  refreshCalibrationControls();
  return state.currentWorkspaceWorkflow;
}

async function refreshCurrentWorkspaceAdvice() {
  if (!state.wizardWorkspacePath) {
    state.currentWorkspaceAdvice = null;
    refreshCalibrationControls();
    return null;
  }
  const p = await apiGet(`/api/workspace/advice?config_path=${encodeURIComponent(state.wizardWorkspacePath)}&prec_source=${encodeURIComponent(getTaskRuntimePrecipSource())}`);
  state.currentWorkspaceAdvice = p.data || null;
  refreshCalibrationControls();
  return state.currentWorkspaceAdvice;
}

async function refreshCurrentWorkspaceLayout() {
  if (!state.wizardWorkspacePath) {
    state.currentWorkspaceLayout = null;
    state.currentWorkspaceLayoutPath = "";
    refreshWizardWorkspacePreview();
    return null;
  }
  const p = await apiGet(`/api/workspace/layout?config_path=${encodeURIComponent(state.wizardWorkspacePath)}`);
  state.currentWorkspaceLayout = p.data || null;
  state.currentWorkspaceLayoutPath = state.wizardWorkspacePath;
  refreshWizardWorkspacePreview();
  return state.currentWorkspaceLayout;
}

async function previewWorkspaceLayout(path, { silent = false } = {}) {
  state.dashboardLayoutPath = String(path || "").trim();
  renderWorkspaceCards();
  try {
    const p = await apiGet(`/api/workspace/layout?config_path=${encodeURIComponent(path)}`);
    state.dashboardWorkspaceLayout = p.data || null;
    renderDashboardWorkspaceLayout();
    return state.dashboardWorkspaceLayout;
  } catch (err) {
    state.dashboardWorkspaceLayout = null;
    renderDashboardWorkspaceLayout();
    if (!silent) showToast(err.message, true);
    throw err;
  }
}

async function loadWorkspace(path) {
  const p = await apiGet(`/api/workspace?path=${encodeURIComponent(path)}`);
  populateWizardFromConfig(p.data, p.path || path);
  await loadTaskManualPresets(p.path || path, { silent: true, calibrationProfile: p.data?.率定模式 || "" });
  const workflow = await refreshCurrentWorkspaceWorkflow();
  refreshCurrentWorkspaceAdvice().catch(() => {});
  refreshCurrentWorkspaceLayout().catch(() => {});
  renderTasks();
  updateManualStarterButtons();
  return workflow;
}

async function loadRuns() {
  const p = await apiGet("/api/runs");
  const previousSelected = currentSelectedRunPath();
  const previousRun = state.currentRun?.run || {};
  const previousRunPath = String(previousRun.path || "").trim();
  const previousUpdatedAt = Number(previousRun.updated_at || 0);
  const previousUpdatedAtNs = Number(previousRun.updated_at_ns || 0);
  state.runs = p.data;
  const currentSelected = currentSelectedRunPath();
  const selectionStable =
    (!previousSelected && !currentSelected) ||
    (previousSelected && currentSelected && samePath(previousSelected, currentSelected));
  if (selectionStable && previousSelected && !state.runs.some(run => samePath(run.path, previousSelected))) {
    clearRunDetail("当前选中的结果已不存在，请从左侧重新选择结果。");
  }
  renderResultsFilterToolbar();
  renderRunList();
  renderForecastView();
  updateCounts();
  const refreshedSelected = selectionStable && previousSelected && state.runs.find(run => samePath(run.path, previousSelected));
  const selectedStillCurrent =
    refreshedSelected &&
    previousRunPath &&
    samePath(refreshedSelected.path, previousRunPath) &&
    (
      Number(refreshedSelected.updated_at_ns || 0) > previousUpdatedAtNs ||
      (
        previousUpdatedAtNs <= 0 &&
        Number(refreshedSelected.updated_at || 0) > previousUpdatedAt
      )
    );
  if (selectedStillCurrent) {
    await loadRun(refreshedSelected.path);
  }
}

async function loadRun(path) {
  const targetPath = String(path || "").trim();
  const previousSelected = currentSelectedRunPath();
  const previousRunData = state.currentRun;
  const requestId = nextRunRequestId();
  let detailLoaded = false;
  state.selectedRunPath = targetPath || previousSelected;
  renderRunList();
  try {
    const p = await apiGet(`/api/run?path=${encodeURIComponent(path)}`);
    if (requestId !== state.activeRunRequestId) return;
    const filtersChanged = alignRunFiltersForSelection(p.data?.run || {});
    if (filtersChanged) {
      renderResultsFilterToolbar();
    }
    state.selectedRunPath = String(p.data?.run?.path || targetPath || previousSelected || "").trim();
    renderRunList();
    renderRunDetail(p.data);
    detailLoaded = true;
    try {
      await loadRunManualPresets(getRunManualPresetConfigPath(p.data), {
        silent: true,
        calibrationProfile: p.data?.metadata?.calibration_profile || p.data?.run?.calibration_profile || "",
      });
    } catch (presetErr) {
      if (requestId === state.activeRunRequestId) {
        showToast(`手调参数集加载失败：${presetErr.message}`, true);
      }
    }
    if (requestId !== state.activeRunRequestId) return;
    try {
      updateSidebar();
    } catch (sidebarErr) {
      showToast(sidebarErr.message, true);
    }
  } catch (err) {
    if (requestId !== state.activeRunRequestId) return;
    state.selectedRunPath = previousSelected;
    renderRunList();
    if (!detailLoaded) {
      if (previousRunData && previousSelected) {
        try {
          renderRunDetail(previousRunData);
          loadRunManualPresets(getRunManualPresetConfigPath(previousRunData), {
            silent: true,
            calibrationProfile: previousRunData?.metadata?.calibration_profile || previousRunData?.run?.calibration_profile || "",
          }).catch(() => {});
        } catch {
          clearRunDetail("结果加载失败，请从左侧重新选择结果。");
        }
      } else if (!previousSelected) {
        clearRunDetail("结果加载失败，请从左侧重新选择结果。");
      }
    }
    throw err;
  }
}

async function renameRun(path) {
  const targetPath = String(path || "").trim();
  if (!targetPath) return;
  const run = state.runs.find(item => samePath(item.path, targetPath)) || (samePath(state.currentRun?.run?.path, targetPath) ? state.currentRun?.run : null);
  const currentCustomTitle = String(run?.raw_title || "").trim();
  const currentDisplayName = runDisplayName(run);
  const nextTitle = window.prompt(
    `请输入结果标题。\n留空并确认，可恢复系统自动命名。\n当前显示：${currentDisplayName}`,
    currentCustomTitle,
  );
  if (nextTitle === null) return;
  const title = nextTitle.trim();
  if (!title && !currentCustomTitle) {
    showToast("当前已经在使用系统自动命名。");
    return;
  }
  if (title === currentCustomTitle) return;
  const response = await apiPost("/api/run/rename", { path: targetPath, title });
  await loadRuns();
  if (currentSelectedRunPath() && samePath(currentSelectedRunPath(), targetPath)) {
    await loadRun(targetPath).catch(() => {});
  }
  const finalName = runDisplayName(response.data?.run || run);
  showToast(title ? `已更新结果标题：${finalName}` : `已恢复系统自动命名：${finalName}`);
}

async function deleteRun(path) {
  const targetPath = String(path || "").trim();
  if (!targetPath) return;
  const run = state.runs.find(item => samePath(item.path, targetPath)) || (samePath(state.currentRun?.run?.path, targetPath) ? state.currentRun?.run : null);
  const name = runDisplayName(run) || shortPath(targetPath);
  if (!confirm(`确定要删除结果“${name}”吗？此操作会删除该结果目录下的图表、指标和参数记录。`)) return;
  await apiPost("/api/run/delete", { path: targetPath });
  if (currentSelectedRunPath() && samePath(currentSelectedRunPath(), targetPath)) {
    clearRunDetail("当前结果已删除，请从左侧重新选择结果。");
  }
  await loadRuns();
  await loadTasks();
  showToast(`已删除结果：${name}`);
}

async function loadTasks() {
  const previousTasks = new Map(state.tasks.map(t => [t.id, t]));
  const p = await apiGet("/api/tasks");
  state.tasks = p.data;
  renderTasks();
  renderForecastView();
  updateCounts();
  updateManualStarterButtons();
  const finishedTaskIds = state.tasks
    .filter(task => previousTasks.get(task.id)?.status === "running" && task.status !== "running")
    .map(task => task.id);
  const currentImport = findCurrentMeteoImportTask({ runningOnly: true });
  if (currentImport) {
    state.activeMeteoImportTaskId = currentImport.id;
    updateMeteoImportUi(currentImport);
    if (state.wizardStep === 7) {
      runInputCheck().catch(() => {});
    }
  } else if (state.activeMeteoImportTaskId) {
    const activeImport = state.tasks.find(t => t.id === state.activeMeteoImportTaskId);
    if (activeImport) updateMeteoImportUi(activeImport);
  }
  const currentPrep = findCurrentPrepTask({ runningOnly: true });
  if (currentPrep) {
    state.activePrepTaskId = currentPrep.id;
    updatePrepTaskUi(currentPrep);
  } else if (state.activePrepTaskId) {
    const activePrep = state.tasks.find(t => t.id === state.activePrepTaskId);
    if (activePrep) updatePrepTaskUi(activePrep);
  }
  const currentForward = findCurrentForwardSimTask({ runningOnly: true });
  if (currentForward) {
    state.activeForwardSimTaskId = currentForward.id;
    state.activeForwardSimSourceRunPath = String(currentForward.run_path || "").trim();
    updateForwardSimUi(currentForward);
  } else if (state.activeForwardSimTaskId) {
    const finishedForward = state.tasks.find(t => t.id === state.activeForwardSimTaskId);
    if (finishedForward) {
      const taskSourceRunPath = String(finishedForward.run_path || state.activeForwardSimSourceRunPath || "").trim();
      if (isForwardSimTaskForCurrentRun(finishedForward, taskSourceRunPath)) {
        updateForwardSimUi(finishedForward);
      }
      if (finishedForward.status !== "running") {
        state.activeForwardSimTaskId = "";
        state.activeForwardSimSourceRunPath = "";
        if (finishedForward.status === "completed" && finishedForward.result) {
          if (finishedForward.result.run_path && isForwardSimTaskForCurrentRun(finishedForward, taskSourceRunPath)) {
            await loadRuns().catch(() => {});
            await openLatestRunAndSwitch(finishedForward.result.run_path, { workspacePath: finishedForward.result.workspace_config || state.wizardWorkspacePath || "" });
          } else if (!finishedForward.result.run_path && isForwardSimTaskForCurrentRun(finishedForward, taskSourceRunPath)) {
            applyForwardSimulationResult(finishedForward.result);
          } else {
            showToast("保存并重算已完成，可在任务列表中查看结果。");
          }
        }
      }
    }
  }
  const newlyCompletedManualStart = state.tasks.find(task =>
    task.task_type === "manual_start" &&
    task.status === "completed" &&
    previousTasks.get(task.id)?.status === "running"
  );
  const newlyCompletedCalibration = state.tasks.find(task =>
    task.task_type === "calibration" &&
    task.status === "completed" &&
    previousTasks.get(task.id)?.status === "running"
  );
  const newlyCompletedForecast = state.tasks.find(task =>
    task.task_type === "forecast_restart" &&
    task.status === "completed" &&
    previousTasks.get(task.id)?.status === "running"
  );
  if (finishedTaskIds.length > 0) {
    clearInputCheckCache();
    await loadRuns();
    await loadWorkspaces();
    if (state.wizardWorkspacePath) {
      await Promise.allSettled([loadBootstrapStatus(), loadPrepSteps(), refreshCurrentWorkspaceWorkflow()]);
      refreshCurrentWorkspaceAdvice().catch(() => {});
    }
    if (newlyCompletedManualStart) {
      const runPath = newlyCompletedManualStart.result?.run_path || newlyCompletedManualStart.run_path || "";
      if (runPath) {
        await openLatestRunAndSwitch(runPath, { workspacePath: newlyCompletedManualStart.config_path || "" });
        showToast("手调起点已生成，已打开结果页。");
      }
    }
    if (newlyCompletedCalibration) {
      const runPath = newlyCompletedCalibration.result?.run_path || newlyCompletedCalibration.run_path || newlyCompletedCalibration.detected_runs?.[0] || latestEditableRunPath();
      if (runPath) {
        await openLatestRunAndSwitch(runPath, { workspacePath: newlyCompletedCalibration.result?.workspace_config || newlyCompletedCalibration.config_path || "" });
        showToast("率定完成，已打开结果页，可继续手动调参。");
      }
    }
    if (newlyCompletedForecast) {
      const runPath = newlyCompletedForecast.result?.run_path || newlyCompletedForecast.run_path || newlyCompletedForecast.detected_runs?.[0] || "";
      if (runPath) {
        await loadRuns().catch(() => {});
        state.forecastResultRunPath = runPath;
        state.forecastResultData = null;
        renderForecastResultPanel();
        if (state.currentView === "forecast") {
          showToast("连续状态预报已完成，已更新预报结果。");
        }
      }
    }
  }
}

// ===============================================================
//  TEMPLATE ACTIONS
// ===============================================================

async function instantiateTemplate(templateId) {
  const suggested = templateId === "tuotuohe-daily-builtin" ? "沱沱河_工作区" : "新流域工作区";
  const name = window.prompt("复制后的工作区名称", suggested);
  if (!name) return;
  try {
    const p = await apiPost("/api/template/instantiate", { template_id: templateId, workspace_name: name });
    showToast(`已复制模板：${shortPath(p.data.workspace_path)}`);
    await loadDashboard();
    await loadWorkspace(p.data.workspace_path);
    navigateWizardStep(1);
    setView("wizard");
  } catch (err) {
    showToast(err.message, true);
  }
}

async function syncTuotuoheData() {
  try {
    const p = await apiPost("/api/template/sync-tuotuohe", {});
    showToast(`已启动：${p.task.label}`);
    await loadTasks();
  } catch (err) {
    showToast(err.message, true);
  }
}

// ===============================================================
//  PATH MODAL
// ===============================================================

function workspaceRuntimeRoot() {
  return String(state.currentWorkspace?.运行目录 || "").trim();
}

function workspaceConfigDir() {
  const raw = String(state.wizardWorkspacePath || "").trim().replace(/\\/g, "/");
  if (!raw.includes("/")) return "";
  return raw.slice(0, raw.lastIndexOf("/"));
}

function preferredPathForTarget(target, kind = "file") {
  const remembered = state.pathModal.lastVisited?.[target];
  if (remembered) return remembered;
  const runtimeRoot = workspaceRuntimeRoot();
  if (kind === "dir" && runtimeRoot) return runtimeRoot;
  if (/^wz-import-(prec|temp|evap)-dir$/.test(target) && runtimeRoot) return runtimeRoot;
  if (/^wz-custom-/.test(target) && runtimeRoot) return runtimeRoot;
  if (target === "wz-hourly-prec-dir" && runtimeRoot) return runtimeRoot;
  return workspaceConfigDir() || runtimeRoot || "";
}

function openPathModal(target, kind, extensions) {
  state.pathModal.open = true;
  state.pathModal.target = target;
  state.pathModal.kind = kind;
  state.pathModal.extensions = extensions;
  $("#path-modal").classList.remove("hidden");
  const currentValue = document.getElementById(target)?.value.trim() || "";
  const startPath = currentValue || preferredPathForTarget(target, kind);
  loadPathListing(startPath).catch(err => showToast(err.message, true));
}

function closePathModal() {
  $("#path-modal").classList.add("hidden");
  state.pathModal.open = false;
}

async function loadPathListing(pathValue) {
  const extParam = state.pathModal.extensions.length
    ? `&extensions=${encodeURIComponent(state.pathModal.extensions.join(","))}`
    : "";
  const kindParam = `&kind=${encodeURIComponent(state.pathModal.kind || "file")}`;
  const p = await apiGet(`/api/fs/list?path=${encodeURIComponent(pathValue || "")}${extParam}${kindParam}`);
  // Map snake_case API keys to camelCase state keys (do NOT use Object.assign — it creates duplicate keys)
  state.pathModal.currentPath = p.data.current_path || "";
  state.pathModal.parentPath  = p.data.parent_path || null;
  state.pathModal.roots       = p.data.roots || [];
  state.pathModal.directories = p.data.directories || [];
  state.pathModal.files       = p.data.files || [];
  state.pathModal.fileCount = Number(p.data.file_count || 0);
  state.pathModal.shownFileCount = Number(p.data.shown_file_count || state.pathModal.files.length || 0);
  state.pathModal.filesTruncated = Boolean(p.data.files_truncated);

  const isDir = state.pathModal.kind === "dir";
  $("#path-modal-title").textContent = isDir ? "选择文件夹" : "选择文件";
  $("#path-modal-use-current").style.display = isDir ? "" : "none";
  $("#path-modal-current").value = state.pathModal.currentPath;
  $("#path-modal-roots").innerHTML = state.pathModal.roots.map(r =>
    `<button class="browser-entry" data-root-path="${escapeHtml(r)}">${escapeHtml(r)}</button>`
  ).join("");
  $("#path-modal-directories").innerHTML = state.pathModal.directories.map(d =>
    `<div class="browser-entry-row">
      <button class="browser-entry browser-entry-nav" data-dir-path="${escapeHtml(d.path)}">${escapeHtml(d.name)}</button>
      ${isDir ? `<button class="browser-entry-select" data-select-dir="${escapeHtml(d.path)}" title="选取此文件夹">✓</button>` : ""}
    </div>`
  ).join("") || '<div class="hint-box">当前目录下没有子文件夹。</div>';
  if (isDir) {
    const previewFiles = state.pathModal.files.map(f =>
      `<div class="browser-entry browser-entry-preview">${escapeHtml(f.name)}</div>`
    ).join("");
    const previewHint = state.pathModal.files.length
      ? `<div class="hint-box ${state.pathModal.filesTruncated ? "status-warn" : ""}">当前为文件夹选择模式，仅预览前 ${state.pathModal.shownFileCount} 个文件${state.pathModal.fileCount ? `（共识别 ${state.pathModal.fileCount} 个）` : ""}，不会展开完整文件列表，因此大栅格目录仍会更快。</div>`
      : '<div class="hint-box">当前为文件夹选择模式。这里仅做内容预览，不会展开完整文件列表，因此大栅格目录会更快。</div>';
    $("#path-modal-files").innerHTML = `${previewHint}${previewFiles}`;
  } else {
    const fileButtons = state.pathModal.files.map(f =>
      `<button class="browser-entry" data-file-path="${escapeHtml(f.path)}">${escapeHtml(f.name)}</button>`
    ).join("");
    const truncateHint = state.pathModal.filesTruncated
      ? `<div class="hint-box status-warn">当前目录文件较多，仅显示前 ${state.pathModal.shownFileCount} 个，共 ${state.pathModal.fileCount} 个。</div>`
      : "";
    $("#path-modal-files").innerHTML = `${truncateHint}${fileButtons}` || '<div class="hint-box">当前目录下没有符合条件的文件。</div>';
  }
}

function applySelectedPath(pathValue) {
  const input = document.getElementById(state.pathModal.target);
  if (!input) return;
  input.value = pathValue;
  state.pathModal.lastVisited[state.pathModal.target] = state.pathModal.kind === "dir"
    ? pathValue
    : String(pathValue || "").replace(/\\/g, "/").replace(/\/[^/]+$/, "");
  input.dispatchEvent(new Event("change", { bubbles: true }));
  closePathModal();
}

// ===============================================================
//  EVENT BINDING
// ===============================================================

function bindBrowseEvents() {
  $all(".browse-button").forEach(btn => {
    btn.addEventListener("click", () => {
      openPathModal(
        btn.dataset.target,
        btn.dataset.browseKind || "file",
        (btn.dataset.extensions || "").split(",").filter(Boolean),
      );
    });
  });

  $("#close-path-modal").addEventListener("click", closePathModal);
  $("#path-modal-go-up").addEventListener("click", () => {
    if (state.pathModal.parentPath) loadPathListing(state.pathModal.parentPath).catch(e => showToast(e.message, true));
  });
  $("#path-modal-use-current").addEventListener("click", () => {
    if (state.pathModal.currentPath && state.pathModal.kind === "dir") applySelectedPath(state.pathModal.currentPath);
  });
  $("#path-modal-roots").addEventListener("click", e => {
    const n = e.target.closest("[data-root-path]");
    if (n) loadPathListing(n.dataset.rootPath).catch(er => showToast(er.message, true));
  });
  $("#path-modal-directories").addEventListener("click", e => {
    // "选取此文件夹" button
    const sel = e.target.closest("[data-select-dir]");
    if (sel) { applySelectedPath(sel.dataset.selectDir); return; }
    // Navigate into folder
    const n = e.target.closest("[data-dir-path]");
    if (n) loadPathListing(n.dataset.dirPath).catch(er => showToast(er.message, true));
  });
  $("#path-modal-files").addEventListener("click", e => {
    const n = e.target.closest("[data-file-path]");
    if (n && state.pathModal.kind === "file") applySelectedPath(n.dataset.filePath);
  });
}

function bindEvents() {
  // nav
  $all(".nav-item").forEach(btn => btn.addEventListener("click", async () => {
    const targetView = btn.dataset.viewTarget;
    if (state.currentView === "wizard" && targetView !== "wizard" && state.wizardWorkspacePath) {
      try {
        const validation = await saveCurrentWizardStep();
        if (targetView === "calibration") {
          if (!enforceWizardValidation(validation)) return;
          const ready = await ensureReadyForCalibration({ forceCheck: false });
          if (!ready) {
            showToast("当前工作区尚未满足率定条件，已保留在向导页。", true);
            return;
          }
        }
      } catch {
        return;
      }
    }
    setView(targetView);
  }));

  // refresh
  $("#refresh-all-button").addEventListener("click", () => refreshAll().catch(e => showToast(e.message, true)));
  $("#quit-app-button")?.addEventListener("click", () => {
    requestQuitApp().catch(err => showToast(err.message, true));
  });

  // --- dashboard ---
  $("#new-project-button").addEventListener("click", () => {
    resetWizard();
    setView("wizard");
  });

  $("#workspace-card-list").addEventListener("click", e => {
    // delete button
    const delBtn = e.target.closest("[data-delete-path]");
    if (delBtn) {
      e.stopPropagation();
      const name = delBtn.closest(".workspace-card")?.querySelector("strong")?.textContent || "";
      if (!confirm(`确定要删除工作区「${name}」吗？此操作仅删除配置文件，不会删除运行目录中的数据。`)) return;
      apiPost("/api/workspace/delete", { path: delBtn.dataset.deletePath })
        .then(() => { showToast("已删除工作区"); loadDashboard(); })
        .catch(err => showToast(err.message, true));
      return;
    }
    const previewBtn = e.target.closest("[data-preview-workspace]");
    if (previewBtn) {
      e.stopPropagation();
      previewWorkspaceLayout(previewBtn.dataset.previewWorkspace)
        .catch(() => {});
      return;
    }
    const resultsBtn = e.target.closest("[data-view-workspace-runs]");
    if (resultsBtn) {
      e.stopPropagation();
      openLatestRunAndSwitch("", { workspacePath: resultsBtn.dataset.viewWorkspaceRuns })
        .catch(er => showToast(er.message, true));
      return;
    }
    const openBtn = e.target.closest("[data-open-workspace]");
    if (openBtn) {
      e.stopPropagation();
      loadWorkspace(openBtn.dataset.openWorkspace)
        .then(workflow => {
          navigateWizardStep(preferredWorkspaceLandingStep(workflow));
          setView("wizard");
        })
        .catch(er => showToast(er.message, true));
      return;
    }
    const card = e.target.closest("[data-workspace-path]");
    if (!card) return;
    loadWorkspace(card.dataset.workspacePath)
      .then(workflow => {
        navigateWizardStep(preferredWorkspaceLandingStep(workflow));
        setView("wizard");
      })
      .catch(er => showToast(er.message, true));
  });
  ["#workspace-layout-panel", "#wz-workspace-layout-preview"].forEach(selector => {
    $(selector)?.addEventListener("click", e => {
      const copyBtn = e.target.closest("[data-layout-copy-path]");
      if (copyBtn) {
        copyTextToClipboard(copyBtn.dataset.layoutCopyPath, copyBtn.dataset.layoutLabel || "路径").catch(err => showToast(err.message, true));
        return;
      }
      const openBtn = e.target.closest("[data-layout-open-path]");
      if (openBtn) {
        openLocalPath(openBtn.dataset.layoutOpenPath, openBtn.dataset.layoutLabel || "目录").catch(err => showToast(err.message, true));
        return;
      }
      const viewRunsBtn = e.target.closest("[data-layout-view-runs]");
      if (viewRunsBtn) {
        openLatestRunAndSwitch("", { workspacePath: viewRunsBtn.dataset.layoutViewRuns }).catch(err => showToast(err.message, true));
        return;
      }
      const jumpBtn = e.target.closest("[data-layout-jump-step]");
      if (jumpBtn) {
        jumpToWorkspaceTarget(jumpBtn.dataset.layoutConfig, jumpBtn.dataset.layoutJumpStep).catch(err => showToast(err.message, true));
      }
    });
  });

  $("#template-list").addEventListener("click", e => {
    const inst = e.target.closest("[data-template-instantiate]");
    const sync = e.target.closest("[data-template-sync]");
    if (inst) instantiateTemplate(inst.dataset.templateInstantiate);
    if (sync) syncTuotuoheData();
  });

  // --- wizard step nav ---

  // step 1 special "next" button
  $("#wz-next-1").addEventListener("click", async () => {
    try {
      const validation = await saveCurrentWizardStep();
      if (!enforceWizardValidation(validation, 1)) return;
      const target = isFullUpstream() ? 2 : 2; // always go to 2 from 1
      navigateWizardStep(2);
    } catch { /* toast already shown */ }
  });
  $("#wz-name").addEventListener("input", () => {
    if (!state.currentWorkspace) {
      state.wizardWorkspacePath = workspacePathForName($("#wz-name").value.trim() || "");
    }
    refreshWizardWorkspacePreview();
  });
  document.querySelectorAll('input[name="wz-timescale"]').forEach(r => r.addEventListener("change", () => {
    refreshWizardWorkspacePreview();
    if ($("#wz-obs-csv")?.value.trim()) {
      detectObs().catch(() => {});
    }
  }));
  document.querySelectorAll('input[name="wz-object"]').forEach(r => r.addEventListener("change", refreshWizardWorkspacePreview));

  // generic wz-next / wz-prev buttons
  document.addEventListener("click", async (e) => {
    const nextBtn = e.target.closest(".wz-next[data-to]");
    const prevBtn = e.target.closest(".wz-prev[data-to]");
    if (nextBtn) {
      try {
        const validation = await saveCurrentWizardStep();
        if (!enforceWizardValidation(validation)) return;
        navigateWizardStep(Number(nextBtn.dataset.to));
      } catch { /* toast already shown */ }
    }
    if (prevBtn) {
      navigateWizardStep(Number(prevBtn.dataset.to));
    }
  });

  // wizard progress bar step buttons
  $all(".wizard-step[data-step]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const target = Number(btn.dataset.step);
      if (target > state.wizardStep) {
        try {
          const validation = await saveCurrentWizardStep();
          if (!enforceWizardValidation(validation)) return;
        } catch {
          return;
        }
      }
      navigateWizardStep(target);
    });
  });

  // obs auto-detect
  $("#wz-obs-csv").addEventListener("change", () => {
    if (!$("#wz-obs-csv").value.trim()) {
      state.obsInfo = null;
      updateObservationHint();
      return;
    }
    detectObs();
  });
  WIZARD_TIME_FIELDS.forEach(selector => {
    $(selector)?.addEventListener("change", () => {
      updateObservationHint();
      clearBoundaryPreview();
    });
  });
  $("#wz-time-basis")?.addEventListener("change", () => {
    updateEventModeHint();
    updateObservationHint();
    clearBoundaryPreview();
    clearInputCheckCache();
  });
  $("#wz-event-file")?.addEventListener("input", () => {
    updateEventModeHint();
    clearInputCheckCache();
  });
  $("#wz-event-file")?.addEventListener("change", () => {
    updateEventModeHint();
    clearInputCheckCache();
  });

  // auto-split time periods
  $("#wz-auto-split-time").addEventListener("click", () => autoSplitTime());

  // auto-compute CFMAX/FAO56 when SHP changes
  $("#wz-basin-shp").addEventListener("change", () => autoComputeElevation());

  // boundary preview
  $("#wz-boundary-preview-btn").addEventListener("click", () => previewBoundary());
  ["#wz-boundary-csv", "#wz-boundary-date", "#wz-boundary-flow", "#wz-gap-fill"].forEach(selector => {
    $(selector)?.addEventListener("change", clearBoundaryPreview);
    $(selector)?.addEventListener("input", clearBoundaryPreview);
  });

  // bootstrap (step 5)
  $("#wz-run-bootstrap").addEventListener("click", () => runBootstrap());
  $("#wz-refresh-bootstrap").addEventListener("click", () => loadBootstrapStatus());
  $("#wz-copy-bootstrap-log")?.addEventListener("click", () => {
    copyTextToClipboard($("#wz-bootstrap-log")?.textContent || "", "日志").catch(err => showToast(err.message, true));
  });
  $("#wz-import-gis-btn").addEventListener("click", () => importGisFiles());

  // GIS mode toggle
  document.querySelectorAll('input[name="wz-gis-mode"]').forEach(r => r.addEventListener("change", updateGisMode));

  // meteo mode toggle
  document.querySelectorAll('input[name="wz-meteo-mode"]').forEach(r => r.addEventListener("change", updateMeteoMode));
  $("#wz-import-meteo-btn").addEventListener("click", () => importMeteoFiles());
  $("#wz-check-era5-api")?.addEventListener("click", () => {
    refreshEra5ApiStatus({ force: true }).catch(err => showToast(err.message, true));
  });
  $("#wz-open-era5-home")?.addEventListener("click", async () => {
    const status = state.cdsApiStatus;
    const path = status?.home_dir || status?.path;
    await openLocalPath(path, "用户目录");
  });
  $("#wz-copy-pipeline-log")?.addEventListener("click", () => {
    copyTextToClipboard($("#wz-pipeline-task-log")?.textContent || "", "日志").catch(err => showToast(err.message, true));
  });
  $("#wz-copy-import-log")?.addEventListener("click", () => {
    copyTextToClipboard($("#wz-import-meteo-log")?.textContent || "", "日志").catch(err => showToast(err.message, true));
  });

  // prep steps (step 6) - delegated
  $("#prep-step-list").addEventListener("click", e => {
    const overwriteBtn = e.target.closest("[data-run-step-overwrite]");
    if (overwriteBtn) {
      runPrepStep(overwriteBtn.dataset.runStepOverwrite, { overwrite: true });
      return;
    }
    const btn = e.target.closest("[data-run-step]");
    if (btn) runPrepStep(btn.dataset.runStep);
  });

  // input check (step 7)
  $("#wz-check-results").addEventListener("click", e => {
    const btn = e.target.closest("[data-go-step]");
    if (!btn) return;
    goToWizardTarget(Number(btn.dataset.goStep), btn.dataset.goSelector || "");
  });
  $("#wz-run-check").addEventListener("click", () => runInputCheck({ force: true, detail: true }));
  $("#wz-go-calibration").addEventListener("click", async () => {
    const ready = await ensureReadyForCalibration({ forceCheck: false });
    if (ready) {
      setView("calibration");
    } else {
      showToast("输入检查未通过，无法进入率定页。", true);
    }
  });

  // --- calibration ---
  $("#go-recommended-step")?.addEventListener("click", () => {
    if (state.currentWorkspaceWorkflow?.ready_for_calibration) {
      showToast("当前工作区已经通过输入检查，无需再回到建模向导补步骤。");
      return;
    }
    const target = (() => {
      const rec = (state.currentWorkspaceAdvice?.recommendations || []).find(item => item.target_step);
      return rec ? inferIssueTarget(rec.detail, rec.target_step || 7) : { step: state.currentWorkspaceAdvice?.recommended_step || state.currentWorkspaceWorkflow?.next_step || 7, selector: "" };
    })();
    goToWizardTarget(target.step, target.selector || "");
  });
  $("#open-latest-result")?.addEventListener("click", () => {
    const workspacePath = state.wizardWorkspacePath || state.runWorkspaceFilterPath || "";
    openLatestRunAndSwitch("", {
      workspacePath,
      createStarterIfMissing: true,
    }).catch(err => showToast(err.message, true));
  });
  $("#start-manual-starter")?.addEventListener("click", () => {
    startManualStarterResult({
      workspacePath: state.wizardWorkspacePath,
      openWhenDone: true,
    }).catch(err => showToast(err.message, true));
  });
  $("#results-generate-manual-starter")?.addEventListener("click", () => {
    startManualStarterResult({
      workspacePath: manualStarterWorkspacePath(),
      openWhenDone: true,
    }).catch(err => showToast(err.message, true));
  });
  $("#start-task-button").addEventListener("click", () => startCalibration());
  $("#apply-recommended-calibration")?.addEventListener("click", () => applyRecommendedCalibrationSettings());
  $("#task-kind").addEventListener("change", refreshCalibrationControls);
  document.querySelectorAll('input[name="task-objective-mode-radio"]').forEach(input => {
    input.addEventListener("change", () => setObjectiveMode(input.value));
  });
  ["#task-glacier-mode", "#task-param-bounds-profile", "#task-quick-days", "#task-method", "#task-objective-mode",
   "#task-workers", "#task-maxiter", "#task-popsize", "#task-seed",
   "#task-mc-samples", "#task-init-preset", "#task-init-bound-shrink"
  ].forEach(sel => {
    const el = $(sel);
    if (el) {
      el.addEventListener("input", refreshCalibrationControls);
      el.addEventListener("change", refreshCalibrationControls);
    }
  });
  $("#task-prec-source")?.addEventListener("change", handleTaskPrecipSourceChange);

  // --- forecast restart ---
  $("#forecast-source-run")?.addEventListener("change", () => {
    state.forecastSourceRunPath = $("#forecast-source-run")?.value || "";
    renderForecastSourceSummary();
  });
  $("#forecast-use-latest")?.addEventListener("click", selectLatestForecastSource);
  $("#forecast-open-source")?.addEventListener("click", () => {
    const run = selectedForecastRun();
    if (run?.path) openLocalPath(run.path, "源结果目录").catch(err => showToast(err.message, true));
  });
  $("#forecast-result-run")?.addEventListener("change", () => {
    state.forecastResultRunPath = $("#forecast-result-run")?.value || "";
    state.forecastResultData = null;
    state.forecastResultLoadingPath = "";
    state.lastForecastExportPath = "";
    renderForecastResultPanel();
  });
  $("#forecast-open-result")?.addEventListener("click", () => {
    openForecastResultAnalysis().catch(err => showToast(err.message, true));
  });
  $("#forecast-open-result-dir")?.addEventListener("click", () => {
    const run = selectedForecastResultRun();
    if (run?.path) openLocalPath(run.path, "预报结果目录").catch(err => showToast(err.message, true));
  });
  $("#forecast-export-excel")?.addEventListener("click", () => {
    exportForecastResultExcel().catch(err => showToast(err.message, true));
  });
  $("#forecast-open-export-file")?.addEventListener("click", () => {
    if (state.lastForecastExportPath) openLocalPath(state.lastForecastExportPath, "导出文件").catch(err => showToast(err.message, true));
  });
  $("#forecast-start-button")?.addEventListener("click", () => startForecastRestart());
  $("#forecast-task-list")?.addEventListener("click", e => {
    handleTaskActionClick(e);
  });
  $("#forecast-task-list")?.addEventListener("toggle", e => {
    const details = e.target.closest?.("[data-task-debug-id]");
    if (!details) return;
    const taskId = details.dataset.taskDebugId || "";
    if (!taskId) return;
    state.taskDebugOpen[taskId] = details.open;
  }, true);

  // --- results ---
  $("#results-filter-toolbar")?.addEventListener("click", e => {
    const workspaceBtn = e.target.closest("[data-run-filter-path]");
    if (workspaceBtn) {
      setRunWorkspaceFilter(workspaceBtn.dataset.runFilterPath || "");
      return;
    }
    const profileBtn = e.target.closest("[data-run-filter-profile]");
    if (profileBtn) {
      setRunProfileFilter(profileBtn.dataset.runFilterProfile || "");
      return;
    }
    const stageBtn = e.target.closest("[data-run-filter-type]");
    if (stageBtn) {
      setRunTypeFilter(stageBtn.dataset.runFilterType || "");
      return;
    }
    const typeBtn = e.target.closest("[data-run-filter-editability]");
    if (typeBtn) {
      setRunEditabilityFilter(typeBtn.dataset.runFilterEditability || "all");
    }
  });
  $("#task-filter-toolbar")?.addEventListener("click", e => {
    const workspaceBtn = e.target.closest("[data-task-filter-workspace]");
    if (workspaceBtn && !workspaceBtn.disabled) {
      setTaskWorkspaceFilterMode(workspaceBtn.dataset.taskFilterWorkspace || "current");
      return;
    }
    const statusBtn = e.target.closest("[data-task-filter-status]");
    if (statusBtn) {
      setTaskStatusFilter(statusBtn.dataset.taskFilterStatus || "active");
      return;
    }
    const typeBtn = e.target.closest("[data-task-filter-type]");
    if (typeBtn) {
      setTaskTypeFilter(typeBtn.dataset.taskFilterType || "all");
    }
  });
  $("#run-list").addEventListener("click", e => {
    const filterBtn = e.target.closest("[data-filter-run-workspace]");
    if (filterBtn) {
      e.stopPropagation();
      setRunWorkspaceFilter(filterBtn.dataset.filterRunWorkspace || "");
      return;
    }
    const openBtn = e.target.closest("[data-open-run-dir]");
    if (openBtn) {
      e.stopPropagation();
      openLocalPath(openBtn.dataset.openRunDir, "结果目录").catch(er => showToast(er.message, true));
      return;
    }
    const renameBtn = e.target.closest("[data-rename-run]");
    if (renameBtn) {
      e.stopPropagation();
      renameRun(renameBtn.dataset.renameRun).catch(er => showToast(er.message, true));
      return;
    }
    const deleteBtn = e.target.closest("[data-delete-run]");
    if (deleteBtn) {
      e.stopPropagation();
      deleteRun(deleteBtn.dataset.deleteRun).catch(er => showToast(er.message, true));
      return;
    }
    const n = e.target.closest("[data-run-path]");
    if (n) loadRun(n.dataset.runPath).catch(er => showToast(er.message, true));
  });
  $("#run-engineering-panel")?.addEventListener("click", e => {
    const renameBtn = e.target.closest("[data-rename-run]");
    if (renameBtn) {
      renameRun(renameBtn.dataset.renameRun).catch(er => showToast(er.message, true));
      return;
    }
    const openDirBtn = e.target.closest("[data-run-summary-open-dir]");
    if (openDirBtn) {
      openLocalPath(openDirBtn.dataset.runSummaryOpenDir, "结果目录").catch(er => showToast(er.message, true));
      return;
    }
    const openReportBtn = e.target.closest("[data-run-summary-open-report]");
    if (openReportBtn) {
      openLocalPath(openReportBtn.dataset.runSummaryOpenReport, "过程复核报告").catch(er => showToast(er.message, true));
      return;
    }
    const openWorkspaceDirBtn = e.target.closest("[data-run-summary-open-workspace-dir]");
    if (openWorkspaceDirBtn) {
      openLocalPath(openWorkspaceDirBtn.dataset.runSummaryOpenWorkspaceDir, "工程目录").catch(er => showToast(er.message, true));
      return;
    }
    const deleteBtn = e.target.closest("[data-delete-run]");
    if (deleteBtn) {
      deleteRun(deleteBtn.dataset.deleteRun).catch(er => showToast(er.message, true));
      return;
    }
    const filterWorkspaceBtn = e.target.closest("[data-run-summary-filter-workspace]");
    if (filterWorkspaceBtn) {
      setRunWorkspaceFilter(filterWorkspaceBtn.dataset.runSummaryFilterWorkspace || "");
      return;
    }
    const openWorkspaceBtn = e.target.closest("[data-run-summary-open-workspace]");
    if (openWorkspaceBtn) {
      loadWorkspace(openWorkspaceBtn.dataset.runSummaryOpenWorkspace)
        .then(workflow => {
          navigateWizardStep(preferredWorkspaceLandingStep(workflow));
          setView("wizard");
        })
        .catch(er => showToast(er.message, true));
    }
  });
  $("#metadata-grid")?.addEventListener("click", e => {
    const openDirBtn = e.target.closest("[data-run-detail-open-dir]");
    if (openDirBtn) {
      openLocalPath(openDirBtn.dataset.runDetailOpenDir, "结果目录").catch(er => showToast(er.message, true));
      return;
    }
    const openReportBtn = e.target.closest("[data-run-detail-open-report]");
    if (openReportBtn) {
      openLocalPath(openReportBtn.dataset.runDetailOpenReport, "过程复核报告").catch(er => showToast(er.message, true));
    }
  });
  $("#btn-run-export")?.addEventListener("click", () => {
    exportCurrentRunExcel().catch(err => showToast(err.message, true));
  });
  $("#btn-open-export-file")?.addEventListener("click", () => {
    openLocalPath(state.lastRunExportPath, "导出文件").catch(err => showToast(err.message, true));
  });
  $("#task-list")?.addEventListener("click", e => {
    handleTaskActionClick(e);
  });
  $("#task-list")?.addEventListener("toggle", e => {
    const details = e.target.closest?.("[data-task-debug-id]");
    if (!details) return;
    const taskId = details.dataset.taskDebugId || "";
    if (!taskId) return;
    state.taskDebugOpen[taskId] = details.open;
  }, true);
  document.addEventListener("scroll", e => {
    const target = e.target;
    if (!(target instanceof HTMLElement)) return;
    if (!target.matches("[data-log-key]")) return;
    rememberLogViewport(target);
  }, true);
  $("#btn-resimulate").addEventListener("click", () => runForwardSimulation());
  $("#btn-reset-params").addEventListener("click", () => resetParamsToOriginal());
  $("#btn-copy-resim-log")?.addEventListener("click", () => {
    copyTextToClipboard($("#resim-log")?.textContent || "", "日志").catch(err => showToast(err.message, true));
  });
  $("#btn-save-manual-preset")?.addEventListener("click", () => saveCurrentManualPreset().catch(err => showToast(err.message, true)));
  $("#btn-load-manual-preset")?.addEventListener("click", () => loadSelectedManualPreset().catch(err => showToast(err.message, true)));
  $("#btn-delete-manual-preset")?.addEventListener("click", () => deleteSelectedManualPreset().catch(err => showToast(err.message, true)));
  $("#btn-compare-manual-preset")?.addEventListener("click", () => compareSelectedManualPresetSimulation().catch(err => showToast(err.message, true)));
  $("#btn-clear-manual-compare")?.addEventListener("click", () => clearManualPresetComparison());
  $("#manual-preset-select")?.addEventListener("change", () => {
    const preset = selectedManualPreset();
    if ($("#manual-preset-name")) $("#manual-preset-name").value = preset?.name || "";
    clearStaleManualPresetComparison({ silent: true });
    renderManualPresetDiff();
    updateCompareSummary();
    updateManualPresetControls();
  });
  $("#manual-phase-toolbar")?.addEventListener("click", e => {
    const btn = e.target.closest("[data-manual-group]");
    if (!btn) return;
    state.manualParamGroup = btn.dataset.manualGroup || "all";
    updateManualGroupToolbar();
    if (state._runData) renderParamSliders(state._runData);
  });

  // path modal
  bindBrowseEvents();

  // temperature/PET/prec source change → conditional fields
  const tempSelect = $("#wz-temp-source");
  if (tempSelect) tempSelect.addEventListener("change", updateConditionalFields);
  const petSelect = $("#wz-pet-source");
  if (petSelect) petSelect.addEventListener("change", updateConditionalFields);
  const precSelect = $("#wz-prec-source");
  if (precSelect) precSelect.addEventListener("change", updateConditionalFields);
  ["#wz-station-prec", "#wz-station-meta"].forEach(sel => {
    const el = $(sel);
    if (el) {
      el.addEventListener("input", () => {
        renderPrecipStrategyStatus();
        renderStationPrecipCheckOverview();
      });
      el.addEventListener("change", () => {
        renderPrecipStrategyStatus();
        renderStationPrecipCheckOverview();
      });
    }
  });

  // radio cards
  setupRadioCards();
}

// ===============================================================
//  REFRESH & POLLING
// ===============================================================

async function refreshAll() {
  if (state.currentView === "wizard" && state.wizardWorkspacePath) {
    await saveCurrentWizardStep();
  }
  await loadDashboard();
  refreshCalibrationControls();
  if (state.wizardWorkspacePath) {
    await loadBootstrapStatus();
    await loadPrepSteps();
    await loadTaskManualPresets(state.wizardWorkspacePath, { silent: true });
    await refreshCurrentWorkspaceWorkflow();
    refreshCurrentWorkspaceAdvice().catch(() => {});
  } else {
    state.taskManualPresets = [];
    state.taskManualPresetConfigPath = "";
    renderManualPresetOptions();
    updateManualPresetControls();
    state.currentWorkspaceAdvice = null;
    refreshCalibrationControls();
  }
}

function startPolling() {
  if (startPolling._started) return;
  startPolling._started = true;

  const pollTasks = async () => {
    try {
      await loadTasks();
    } catch {}
    const hasRunning = state.tasks.some(t => t.status === "running");
    if (hasRunning) {
      setTimeout(() => loadTasks().catch(() => {}), 1500);
    }
    const delay = hasRunning ? 3000 : 8000;
    setTimeout(pollTasks, delay);
  };

  const pollRuns = async () => {
    const hasRunning = state.tasks.some(t => t.status === "running");
    const shouldRefreshRuns = hasRunning || state.currentView === "dashboard" || state.currentView === "forecast" || state.currentView === "results";
    if (shouldRefreshRuns) {
      try {
        await loadRuns();
      } catch {}
    }
    const delay = hasRunning ? 12000 : 20000;
    setTimeout(pollRuns, delay);
  };

  pollTasks();
  pollRuns();
}

// ===============================================================
//  INIT
// ===============================================================

async function init() {
  bindEvents();
  window.addEventListener("pagehide", notifyWindowUnload);
  renderRunExportFields();
  updateConditionalFields();
  updateGisMode();
  refreshWizardWorkspacePreview();
  renderDashboardWorkspaceLayout();

  try {
    const health = await apiGet("/api/health");
    const connectedAt = health.server_time ? String(health.server_time).split(" ").pop() : new Date().toLocaleTimeString();
    setServiceState(true, `本地服务已连接 · ${connectedAt}`);
    await refreshAll();
    startPolling();
  } catch (err) {
    setServiceState(false, "未连接到本地服务");
    showToast(err.message, true);
  }
}

window.addEventListener("DOMContentLoaded", init);
