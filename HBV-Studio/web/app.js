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

const viewRenderers = {
  dashboard: renderDashboardView,
  wizard: renderWizardView,
  calibration: renderCalibrationView,
  forecast: renderForecastView,
  results: renderResultsView,
};

const frontendModuleContracts = [
  {
    script: "./js/apiClient.js",
    global: "HBVStudioApiClient",
    exports: ["apiGet", "apiPost", "createLatestRequestGuard"],
  },
  {
    script: "./js/chartPalette.js",
    global: "HBVStudioChartPalette",
    exports: ["chartColors"],
  },
  {
    script: "./js/runView.js",
    global: "HBVStudioRunView",
    exports: [
      "compactTimeText",
      "forecastFriendlyRunName",
      "isGeneratedRunName",
      "objectiveFamilyKey",
      "objectiveVersionBadge",
      "objectiveVersionStatus",
      "readableRunReferenceName",
      "runDisplayName",
      "runDisplaySubtitle",
      "runEditabilityLabel",
      "runMetricsText",
      "runTimeText",
      "runTypeBadge",
      "runTypeLabel",
      "runTypeValue",
      "runWorkspaceName",
      "timeRangeText",
    ],
  },
  {
    script: "./js/resultMetadata.js",
    global: "HBVStudioResultMetadata",
    exports: [
      "analyzeIceContribution",
      "boundaryEnabledFromMeta",
      "boundaryModuleSummary",
      "componentFractionBasisText",
      "componentFractionReport",
      "componentFractionText",
      "dataCacheSummary",
      "glacierFractionReport",
      "glacierFractionValue",
      "glacierModuleSummary",
      "iceContributionDetailText",
      "optimizationPolishSummary",
      "optimizationRefineSummary",
      "optimizationResultLabel",
      "optimizationSummary",
      "replayCompatibilityInfo",
      "runPrecipSummary",
    ],
  },
  {
    script: "./js/resultsView.js",
    global: "HBVStudioResultsView",
    exports: ["alignedRunFiltersForSelection", "clearRunComparisonState", "clearRunDetailState", "clearRunDetailViewState", "filterRuns", "forwardSimulationErrorState", "forwardSimulationPollingErrorState", "forwardSimulationPreflight", "forwardSimulationRequestContext", "forwardSimulationResultState", "forwardSimulationStartState", "forwardSimulationTaskUiState", "latestEditableRunPath", "manualStarterControlState", "resultFilterToolbarState", "resultMetricItems", "resultMetricStripState", "renderFilterToolbar", "renderMetricStrip", "renderRunCard", "renderRunCards", "renderRunDetailMetadata", "renderRunEngineeringSummary", "renderRunExportFields", "resultChartPayloads", "resultsFilterBreakdown", "resultsFilterHint", "runCardsState", "runComparisonClearViewState", "runComparisonErrorState", "runComparisonPreflight", "runComparisonRequestContext", "runComparisonRequestStillCurrent", "runComparisonSuccessState", "runDetailState", "runExportFields", "runExportFieldsState", "runExportPanelState", "runExportPayload", "runExportSuccess", "runListState", "runManualPresetLoadErrorState", "runManualPresetLoadStartState", "runManualPresetLoadSuccessState", "runProfileValue", "runsForWorkspace", "selectedRunExportFields", "selectedRunPath", "runStepHours", "workspaceHasEditableRun"],
  },
  {
    script: "./js/stationPrecip.js",
    global: "HBVStudioStationPrecip",
    exports: [
      "stationPrecipCheckFromValidation",
      "stationPrecipModeDescription",
      "stationPrecipModeLabel",
      "precipStrategyStatusState",
      "renderPrecipStrategyStatusCards",
      "stationPrecipFallbackCheck",
      "renderTaskScopeSummary",
      "renderEventCoverageMatrix",
      "renderStationEventCoverage",
    ],
  },
  {
    script: "./js/eventMode.js",
    global: "HBVStudioEventMode",
    exports: [
      "floodEventEvaluation",
      "floodEventMetricItems",
      "floodEventObjectiveText",
      "floodEventRows",
      "floodEventStatusText",
      "eventChartEvents",
      "initialStatePolicyLabel",
      "renderFloodEventChart",
      "renderEventWindowSummary",
      "renderEventForcingCoverage",
      "renderEventObservationCoverage",
      "renderWizardEventSummary",
      "wizardEventSummaryState",
      "renderInputTimeSummary",
      "renderValidationEventSections",
    ],
  },
  {
    script: "./js/engineeringFocusView.js",
    global: "HBVStudioEngineeringFocusView",
    exports: ["engineeringFocusChecksState", "renderEngineeringFocusChecks"],
  },
  {
    script: "./js/parameterLibrary.js",
    global: "HBVStudioParameterLibrary",
    exports: [
      "normalizeKey",
      "scopeLabel",
      "renderPresetOptions",
      "manualPresetDiffSummary",
      "manualPresetDiffView",
      "manualPresetDiffPanelState",
      "compareMetricSummary",
      "manualPresetCompareSummary",
      "manualPresetCompareView",
      "manualPresetComparePanelState",
      "manualPresetComparePendingView",
      "manualPresetCompareErrorView",
      "findPresetById",
      "manualPresetListPath",
      "manualPresetConfigPathFromRunData",
      "manualPresetProfileState",
      "taskManualPresetLoadErrorState",
      "taskManualPresetLoadStartState",
      "taskManualPresetLoadSuccessState",
      "manualPresetTaskSyncState",
      "shouldClearManualPresetComparison",
      "manualPresetSelectionChangeState",
      "manualPresetControlState",
      "manualPresetControlViewState",
      "manualPresetSavePreflight",
      "manualPresetLoadPreflight",
      "manualPresetDeletePreflight",
      "manualPresetSavePayload",
      "manualPresetDeletePayload",
      "manualPresetSaveSuccessState",
      "manualPresetSaveSelectionState",
      "manualPresetLoadSuccessState",
      "manualPresetDeleteViewState",
      "manualPresetDeleteSuccessState",
      "manualPresetAppliedParams",
      "manualPresetApplyState",
      "manualParamUpdateState",
      "manualParamResetState",
      "manualParamResetViewState",
      "manualGroupParamNames",
      "manualPhaseGuide",
      "manualChangeSummary",
      "manualChangeSummaryPanelState",
      "renderParamSliders",
      "manualContextFromRunData",
      "manualContextWarning",
      "manualPresetContextWarningState",
      "taskPresetContext",
      "taskContextWarnings",
      "renderTaskContextHint",
      "forecastParameterContext",
    ],
  },
  {
    script: "./js/forecastView.js",
    global: "HBVStudioForecastView",
    exports: [
      "forecastArchiveDetailText",
      "forecastArchiveManifest",
      "forecastArchiveSummaryText",
      "forecastArchiveVariableItems",
      "forecastArchiveVariables",
      "forecastCandidateRuns",
      "forecastCompletedResultState",
      "forecastInputCheckDecision",
      "forecastInputCheckDelay",
      "forecastInputCheckError",
      "forecastInputPayload",
      "forecastInputCheckTimerState",
      "forecastInputType",
      "forecastParameterSourceSummary",
      "forecastResultButtonState",
      "forecastResultDetailState",
      "forecastResultExportPayload",
      "forecastResultExportState",
      "forecastResultExportSuccess",
      "forecastResultLoadErrorState",
      "forecastResultLoadStartState",
      "forecastResultLoadSuccessState",
      "forecastResultPanelState",
      "forecastResultSelectionState",
      "forecastRestartPreflight",
      "forecastRestartPayload",
      "forecastResultRuns",
      "forecastRunReady",
      "forecastRunReadinessText",
      "forecastSelectedSourceRun",
      "forecastSelectedResultRun",
      "forecastSourceOptionsState",
      "forecastSourceButtonState",
      "forecastSourceSelectionState",
      "forecastSuggestedStart",
      "forecastTimeComparable",
      "formatForecastInputTime",
      "parseForecastTime",
      "pickForecastSourceRun",
      "renderForecastSourceOptions",
      "renderForecastSourceSummary",
      "renderForecastResultOptions",
      "forecastRestartTasks",
      "forecastTaskListState",
      "renderForecastTaskCard",
      "renderForecastResultEmpty",
      "renderForecastResultLoading",
      "renderForecastInputSummary",
      "renderForecastTaskList",
      "renderForecastTaskInputCheckSummary",
      "renderForecastResultDetail",
      "restartStateRows",
    ],
  },
  {
    script: "./js/dashboardView.js",
    global: "HBVStudioDashboardView",
    exports: ["renderTemplates", "renderWorkspaceCards", "templateListState", "workspaceCardsState"],
  },
  {
    script: "./js/mapLayerPlan.js",
    global: "HBVStudioMapLayerPlan",
    exports: ["buildMapLibreLayerPlan", "buildMapLibreStyle"],
  },
  {
    script: "./js/geoPreview.js",
    global: "HBVStudioGeoPreview",
    exports: ["renderOverview"],
  },
  {
    script: "./js/workspaceLayout.js",
    global: "HBVStudioWorkspaceLayout",
    exports: ["aliasForPath", "render", "workspaceLayoutHtml"],
  },
  {
    script: "./js/dataPrepView.js",
    global: "HBVStudioDataPrepView",
    exports: ["formatPrepBlockedMessage", "formatPrepDisplayTitle", "prepPanelSummary", "prepTaskUiState", "renderBootstrapStatus", "renderInputCheckError", "renderInputCheckImportBlock", "renderInputCheckProgress", "renderInputCheckResults", "renderPrepStepList"],
  },
  {
    script: "./js/taskView.js",
    global: "HBVStudioTaskView",
    exports: [
      "cleanTaskLogMessage",
      "filterTasks",
      "methodLabel",
      "optimizationMethodLabel",
      "renderTaskActions",
      "renderTaskCard",
      "renderTaskFilterToolbar",
      "renderTaskList",
      "renderTaskMilestones",
      "taskContextSummary",
      "taskDebugDetails",
      "taskLastMeaningfulLog",
      "taskPrimaryTitle",
      "taskProgressChartData",
      "taskStageLabel",
      "taskStatusClass",
      "taskStatusLabel",
      "taskSummaryLine",
      "taskListState",
      "taskTypeLabel",
    ],
  },
];

const GIS_STEP_IDS = new Set(["clip_dem", "flow_acc", "masked_flow", "elevation_zone", "glacier_mask", "glacier_elev"]);
const CHECK_STEP_IDS = new Set(["check_inputs"]);

const colors = window.HBVStudioChartPalette.chartColors();

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

const CURRENT_OBJECTIVE_FAMILY = "daily_unified_professional_v1";
const FLOOD_EVENT_OBJECTIVE_FAMILY = "flood_event_calibration_v1";
const LEGACY_OBJECTIVE_FAMILIES = new Set(["weighted_daily_universal", "weighted_multi_criteria"]);
const runDetailRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();
const cdsApiStatusRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();
const forecastInputCheckRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();
const forecastResultRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();
const runManualPresetRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();
const taskManualPresetRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();
const compareRequestGuard = window.HBVStudioApiClient.createLatestRequestGuard();

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
  currentWorkspaceGeoOverview: null,
  dashboardWorkspaceLayout: null,
  dashboardLayoutPath: "",
  dashboardGeoOverview: null,
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
  compareSeries: null,
  compareMetrics: null,
  compareLabel: "",
  comparePresetId: "",
  compareAdjusted: false,
  runManualPresets: [],
  runManualPresetConfigPath: "",
  taskManualPresets: [],
  taskManualPresetConfigPath: "",
  forecastSourceRunPath: "",
  forecastResultRunPath: "",
  forecastResultData: null,
  forecastResultLoadingPath: "",
  forecastInputCheckTimer: null,
  lastForecastExportPath: "",
  prepSteps: [],
  prepStatus: {},
  cdsApiStatus: null,
  cdsApiNeedSignature: "",
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

function validateFrontendModules() {
  const missing = [];
  frontendModuleContracts.forEach(contract => {
    const module = window[contract.global];
    if (!module) {
      missing.push(contract.global);
      return;
    }
    contract.exports.forEach(name => {
      if (typeof module[name] !== "function") missing.push(`${contract.global}.${name}`);
    });
  });
  if (missing.length) {
    showToast(`前端模块未完整加载：${missing.slice(0, 4).join("、")}${missing.length > 4 ? "…" : ""}`, true);
  }
  return missing;
}

function formatNumber(v, digits = 3) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "\u2014";
  return Number(v).toFixed(digits);
}

function finiteNumber(v) {
  const numeric = Number(v);
  return Number.isFinite(numeric) ? numeric : null;
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
  return window.HBVStudioRunView.runTypeValue(run);
}

function runTypeLabel(value, fallback = "") {
  return window.HBVStudioRunView.runTypeLabel(value, fallback);
}

function runDisplayName(run) {
  return window.HBVStudioRunView.runDisplayName(run, { workspaceLabelByPath, formatDateTime });
}

function isGeneratedRunName(value) {
  return window.HBVStudioRunView.isGeneratedRunName(value);
}

function forecastFriendlyRunName(run) {
  return window.HBVStudioRunView.forecastFriendlyRunName(run, { workspaceLabelByPath, formatDateTime });
}

function readableRunReferenceName(value, fallback = "") {
  return window.HBVStudioRunView.readableRunReferenceName(value, fallback);
}

function runDisplaySubtitle(run) {
  return window.HBVStudioRunView.runDisplaySubtitle(run);
}

function runWorkspaceName(run) {
  return window.HBVStudioRunView.runWorkspaceName(run, { workspaceLabelByPath });
}

function runTimeText(run) {
  return window.HBVStudioRunView.runTimeText(run, { formatDateTime });
}

function compactTimeText(value, stepHours = 24) {
  return window.HBVStudioRunView.compactTimeText(value, stepHours);
}

function timeRangeText(start, end, stepHours = 24) {
  return window.HBVStudioRunView.timeRangeText(start, end, stepHours);
}

function runEditabilityLabel(run) {
  return window.HBVStudioRunView.runEditabilityLabel(run);
}

function runMetricsText(run) {
  return window.HBVStudioRunView.runMetricsText(run);
}

function runTypeBadge(run) {
  return window.HBVStudioRunView.runTypeBadge(run, { escapeHtml });
}

function objectiveFamilyKey(metaOrRun = {}) {
  return window.HBVStudioRunView.objectiveFamilyKey(metaOrRun);
}

function objectiveVersionStatus(metaOrRun = {}) {
  return window.HBVStudioRunView.objectiveVersionStatus(metaOrRun, {
    currentObjectiveFamily: CURRENT_OBJECTIVE_FAMILY,
    floodEventObjectiveFamily: FLOOD_EVENT_OBJECTIVE_FAMILY,
    legacyObjectiveFamilies: LEGACY_OBJECTIVE_FAMILIES,
  });
}

function objectiveVersionBadge(run) {
  return window.HBVStudioRunView.objectiveVersionBadge(run, {
    escapeHtml,
    currentObjectiveFamily: CURRENT_OBJECTIVE_FAMILY,
    floodEventObjectiveFamily: FLOOD_EVENT_OBJECTIVE_FAMILY,
    legacyObjectiveFamilies: LEGACY_OBJECTIVE_FAMILIES,
  });
}

function visibleRuns() {
  return window.HBVStudioResultsView.filterRuns(
    state.runs,
    {
      workspacePath: state.runWorkspaceFilterPath,
      profile: state.runProfileFilter,
      type: state.runTypeFilter,
      editability: state.runEditabilityFilter,
    },
    { samePath, runTypeValue }
  );
}

function runsForWorkspace(path) {
  return window.HBVStudioResultsView.runsForWorkspace(state.runs, path, { samePath });
}

function currentSelectedRunPath() {
  return window.HBVStudioResultsView.selectedRunPath({
    selectedRunPath: state.selectedRunPath,
    currentRun: state.currentRun,
  });
}

function normalizeCalibrationProfile(value, fallback = "") {
  const profile = String(value || "").trim().toLowerCase();
  return profile || fallback;
}

function workspaceHasEditableRun(path) {
  return window.HBVStudioResultsView.workspaceHasEditableRun(state.runs, path, { samePath });
}

function visibleTasks() {
  return window.HBVStudioTaskView.filterTasks(
    state.tasks,
    {
      workspaceMode: state.taskWorkspaceFilterMode,
      workspacePath: state.wizardWorkspacePath,
      status: state.taskStatusFilter,
      type: state.taskTypeFilter,
    },
    { samePath }
  );
}

function latestEditableRunPath(runs = visibleRuns()) {
  return window.HBVStudioResultsView.latestEditableRunPath(runs);
}

function renderTaskFilterToolbar() {
  const host = $("#task-filter-toolbar");
  if (!host) return;
  const rendered = window.HBVStudioTaskView.renderTaskFilterToolbar({
    tasks: state.tasks,
    workspaceMode: state.taskWorkspaceFilterMode,
    workspacePath: state.wizardWorkspacePath,
    status: state.taskStatusFilter,
    type: state.taskTypeFilter,
  }, { escapeHtml, samePath, workspaceLabelByPath });
  applyDomUpdates(rendered.domUpdates);
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
  if (!host) return;
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
  const toolbar = window.HBVStudioResultsView.resultFilterToolbarState({
    workspaceOptions,
    profileOptions,
    stageOptions,
    editabilityOptions,
    selectedWorkspacePath: state.runWorkspaceFilterPath,
    selectedProfile: state.runProfileFilter,
    selectedType: state.runTypeFilter,
    selectedEditability: state.runEditabilityFilter,
  }, { escapeHtml, samePath });
  applyDomUpdates(toolbar.domUpdates);
  const shown = visibleRuns();
  const workspaceText = state.runWorkspaceFilterPath ? `工作区“${workspaceLabelByPath(state.runWorkspaceFilterPath)}”` : "全部工作区";
  const profileText = state.runProfileFilter ? profileLabel(state.runProfileFilter) : "全部尺度";
  const stageText = state.runTypeFilter ? runTypeLabel(state.runTypeFilter) : "全部阶段";
  const abilityText = state.runEditabilityFilter === "editable" ? "可继续手调" : state.runEditabilityFilter === "readonly" ? "仅查看" : "全部手调能力";
  const breakdown = window.HBVStudioResultsView.resultsFilterBreakdown(shown, { runTypeValue }).text;
  const filterHint = window.HBVStudioResultsView.resultsFilterHint({
    filtersActive: Boolean(state.runWorkspaceFilterPath || state.runProfileFilter || state.runTypeFilter || state.runEditabilityFilter !== "all"),
    totalRuns: state.runs.length,
    shownCount: shown.length,
    workspaceText,
    profileText,
    stageText,
    abilityText,
    breakdown,
  });
  applyDomUpdates(filterHint.domUpdates);
}

function clearRunDetail(message = "请先从左侧选择一个结果。") {
  runDetailRequestGuard.cancel();
  runManualPresetRequestGuard.cancel();
  compareRequestGuard.cancel();
  const viewState = window.HBVStudioResultsView.clearRunDetailViewState(message);
  Object.assign(state, viewState.statePatch);
  applyDomUpdates(viewState.domUpdates);
  if (viewState.shouldRenderRunExportFields && $("#run-export-fields")) renderRunExportFields();
  if (viewState.shouldRenderManualPresetOptions) renderManualPresetOptions();
  if (viewState.shouldUpdateManualPresetControls) updateManualPresetControls();
  if (viewState.shouldRenderManualPresetDiff) renderManualPresetDiff();
  if (viewState.shouldUpdateCompareSummary) updateCompareSummary();
  viewState.chartIds.forEach(id => {
    if (window.Plotly) {
      try { window.Plotly.purge(id); } catch {}
    }
    const el = document.getElementById(id);
    if (el) el.innerHTML = viewState.chartFallbackHtml;
  });
  if (viewState.shouldUpdateManualStarterButtons) updateManualStarterButtons();
  if (viewState.shouldUpdateSidebar) updateSidebar();
}

function applyDomUpdates(updates = []) {
  updates.forEach(update => {
    const el = $(update.selector);
    if (!el) return;
    if (Object.prototype.hasOwnProperty.call(update, "html")) el.innerHTML = update.html;
    if (Object.prototype.hasOwnProperty.call(update, "text")) el.textContent = update.text;
    if (Object.prototype.hasOwnProperty.call(update, "className")) el.className = update.className;
    if (Object.prototype.hasOwnProperty.call(update, "type")) el.type = update.type;
    if (Object.prototype.hasOwnProperty.call(update, "step")) el.step = update.step;
    if (Object.prototype.hasOwnProperty.call(update, "value")) el.value = update.value;
    if (Object.prototype.hasOwnProperty.call(update, "disabled")) el.disabled = update.disabled;
    if (Object.prototype.hasOwnProperty.call(update, "visible")) el.style.display = update.visible ? "" : "none";
  });
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
  const controlState = window.HBVStudioResultsView.manualStarterControlState({
    calibrationWorkspacePath,
    resultsWorkspacePath,
    runningCalibrationTask,
    runningResultsTask,
    totalRuns: state.runs.length,
    workspaceFilterActive: Boolean(state.runWorkspaceFilterPath),
    resultsWorkspaceRunCount,
  });
  const calibrationBtn = $("#start-manual-starter");
  if (calibrationBtn) {
    calibrationBtn.disabled = controlState.calibration.disabled;
    calibrationBtn.textContent = controlState.calibration.text;
  }
  const resultsWrap = $("#results-empty-actions");
  const resultsBtn = $("#results-generate-manual-starter");
  if (resultsWrap) {
    resultsWrap.style.display = controlState.results.visible ? "" : "none";
  }
  if (resultsBtn) {
    resultsBtn.disabled = controlState.results.disabled;
    resultsBtn.textContent = controlState.results.text;
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
  return window.HBVStudioResultsView.runProfileValue(run);
}

function alignRunFiltersForSelection(run) {
  if (!run) return false;
  const aligned = window.HBVStudioResultsView.alignedRunFiltersForSelection(
    run,
    {
      workspacePath: state.runWorkspaceFilterPath,
      profile: state.runProfileFilter,
      type: state.runTypeFilter,
      editability: state.runEditabilityFilter,
    },
    visibleRuns(),
    { samePath, runTypeValue }
  );
  state.runWorkspaceFilterPath = aligned.filters.workspacePath;
  state.runProfileFilter = aligned.filters.profile;
  state.runTypeFilter = aligned.filters.type;
  state.runEditabilityFilter = aligned.filters.editability;
  return aligned.changed;
}

function layoutStatusClass(item) {
  if (!item?.exists) return "status-fail";
  if (item.kind === "file") return "status-ok";
  return Number(item.count || 0) > 0 ? "status-ok" : "status-warn";
}

function renderGeoOverview(overview) {
  return window.HBVStudioGeoPreview?.renderOverview(overview, { escapeHtml }) || "";
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

function renderWorkspaceLayout(layout, hostSelector, options = {}) {
  window.HBVStudioWorkspaceLayout?.render(layout, hostSelector, options, {
    select: $,
    escapeHtml,
    slashPath,
    layoutStatusClass,
    renderGeoOverview,
  });
}

function directoryAliasLabel(path) {
  return window.HBVStudioWorkspaceLayout?.aliasForPath(path, { slashPath }) || "";
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
  return window.HBVStudioParameterLibrary.manualGroupParamNames(group, names, MANUAL_GROUP_PARAMS);
}

function updateManualGroupToolbar() {
  $all("[data-manual-group]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.manualGroup === state.manualParamGroup);
  });
}

function updateManualPhaseGuide(paramNames = []) {
  const host = $("#manual-phase-guide");
  if (!host) return;
  const guide = window.HBVStudioParameterLibrary.manualPhaseGuide(
    state.manualParamGroup,
    paramNames,
    MANUAL_GROUP_META,
    MANUAL_GROUP_PARAMS,
  );
  host.textContent = guide.text;
  host.className = guide.className;
}

function updateManualChangeSummary() {
  const host = $("#manual-change-summary");
  if (!host) return;
  const summary = window.HBVStudioParameterLibrary.manualChangeSummaryPanelState(
    state._runParams,
    state._runOrigParams,
    state.manualParamGroup,
    MANUAL_GROUP_PARAMS,
  );
  host.style.display = summary.visible ? "" : "none";
  host.className = summary.className;
  host.textContent = summary.text;
}

function renderManualPresetDiff() {
  const host = $("#manual-preset-diff");
  if (!host) return;
  const preset = selectedManualPreset();
  const baseline = state._runOrigParams || {};
  const view = window.HBVStudioParameterLibrary.manualPresetDiffPanelState(
    preset,
    baseline,
    { contextWarning: manualPresetContextWarning(preset) },
    { formatNumber },
  );
  host.style.display = view.visible ? "" : "none";
  host.className = view.className;
  host.textContent = view.text;
}

function manualPresetContextWarning(preset, data = state._runData) {
  return window.HBVStudioParameterLibrary?.manualPresetContextWarningState(
    preset,
    data,
    {
      effectiveObjectiveMode,
      objectiveLabel,
      precipSourceLabel: getConfiguredPrecipSourceLabel,
      boundsLabel: value => PARAM_BOUNDS_PROFILE_LABELS[value] || value,
    },
  )?.text || "";
}

function timeBasisLabel(value) {
  const key = String(value || "").trim().toLowerCase();
  if (key === "event_windows") return "洪水事件窗口";
  if (key === "forecast_window") return "预报窗口";
  return "连续时段";
}

function selectedTaskManualPreset() {
  const presetId = $("#task-init-preset")?.value || "";
  return window.HBVStudioParameterLibrary.findPresetById(state.taskManualPresets, presetId);
}

function currentTaskPresetContext() {
  const profile = normalizeCalibrationProfile(state.currentWorkspace?.率定模式, "daily");
  return window.HBVStudioParameterLibrary.taskPresetContext({
    workspace: state.currentWorkspace,
    profile,
    objectiveMode: $("#task-objective-mode")?.value || CURRENT_OBJECTIVE_FAMILY,
    precSource: getTaskRuntimePrecipSource(),
    glacierMode: $("#task-glacier-mode")?.value || "inline",
    paramBoundsProfile: $("#task-param-bounds-profile")?.value || "qtp_alpine_default",
    precipitationMode: getSelectedRadio("wz-precip-mode"),
    taskTimeBasis: $("#wz-time-basis")?.value,
  });
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
  compareRequestGuard.cancel();
  const clearState = window.HBVStudioResultsView.runComparisonClearViewState(state._runData, { silent });
  Object.assign(state, clearState.statePatch);
  applyDomUpdates(clearState.domUpdates);
  if (clearState.shouldRestoreRun) {
    renderCharts(clearState.chartData);
    updateMetricsStrip(clearState.calibrationMetrics, clearState.validationMetrics, clearState.metricMetadata);
  }
  updateManualPresetControls();
  if (clearState.shouldToast) showToast(clearState.toastText);
}

function updateCompareSummary() {
  const view = window.HBVStudioParameterLibrary.manualPresetComparePanelState({
    runData: state._runData,
    compareMetrics: state.compareMetrics,
    compareLabel: state.compareLabel,
    adjusted: state.compareAdjusted,
  });
  applyDomUpdates(view.domUpdates);
}

function clearStaleManualPresetComparison({ silent = true } = {}) {
  if (!window.HBVStudioParameterLibrary.shouldClearManualPresetComparison(selectedManualPreset(), state.comparePresetId)) return;
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
  return window.HBVStudioTaskView?.taskStageLabel(stage) || "未知阶段";
}

function taskStatusLabel(status) {
  return window.HBVStudioTaskView?.taskStatusLabel(status) || String(status || "未知");
}

function taskStatusClass(status) {
  return window.HBVStudioTaskView?.taskStatusClass(status) || "status-warn";
}

function taskTypeLabel(taskType) {
  return window.HBVStudioTaskView?.taskTypeLabel(taskType) || "任务";
}

function methodLabel(method) {
  return window.HBVStudioTaskView?.methodLabel(method) || String(method || "未设置");
}

function optimizationMethodLabel(optimization) {
  return window.HBVStudioTaskView?.optimizationMethodLabel(optimization) || methodLabel(optimization?.method);
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

function engineeringFocusHelpers() {
  return {
    escapeHtml,
    focusStatusClass,
    focusStatusLabel,
    formatNumber,
    renderStationEventCoverage: (check, helpers) => window.HBVStudioStationPrecip.renderStationEventCoverage(check, helpers),
  };
}

function renderEngineeringFocusChecks(checks = [], options = {}) {
  return window.HBVStudioEngineeringFocusView.renderEngineeringFocusChecks(checks, options, engineeringFocusHelpers());
}

function engineeringFocusChecksState(selector, checks = [], options = {}) {
  return window.HBVStudioEngineeringFocusView.engineeringFocusChecksState(selector, checks, options, engineeringFocusHelpers());
}

function stationPrecipModeLabel(mode) {
  return window.HBVStudioStationPrecip.stationPrecipModeLabel(mode);
}

function renderPrecipStrategyStatus() {
  const host = $("#wz-precip-strategy-status");
  if (!host) return;
  const mode = getSelectedRadio("wz-precip-mode") || "grid_only";
  const stationPrec = $("#wz-station-prec")?.value.trim() || "";
  const stationMeta = $("#wz-station-meta")?.value.trim() || "";
  const status = window.HBVStudioStationPrecip.precipStrategyStatusState(
    { mode, stationPrec, stationMeta },
    { escapeHtml, shortPath },
  );
  applyDomUpdates(status.domUpdates);
}

function renderStationPrecipCheckOverview(validation = null) {
  const host = $("#wz-station-check-overview");
  if (!host) return;
  const mode = getSelectedRadio("wz-precip-mode") || state.currentWorkspace?.气象策略?.降水方案 || "grid_only";
  const check = window.HBVStudioStationPrecip.stationPrecipCheckFromValidation(validation);
  if (check) {
    applyDomUpdates(engineeringFocusChecksState("#wz-station-check-overview", [check], { title: "站点降水专项检查" }).domUpdates);
    return;
  }
  const stationPrec = $("#wz-station-prec")?.value.trim() || state.currentWorkspace?.气象策略?.站点降水_csv || "";
  const stationMeta = $("#wz-station-meta")?.value.trim() || state.currentWorkspace?.气象策略?.站点信息_csv || "";
  const fallback = window.HBVStudioStationPrecip.stationPrecipFallbackCheck(
    { mode, stationPrec, stationMeta },
    { shortPath },
  );
  applyDomUpdates(engineeringFocusChecksState("#wz-station-check-overview", [fallback], { title: "站点降水专项检查" }).domUpdates);
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
    warnings.push("当前按洪水事件检查资料；观测覆盖将在第 7 步按各场洪水时段核验。");
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
      ? "当前按洪水事件组织资料。系统只检查每场洪水内部资料，事件之间允许间断。"
      : "已选择洪水事件，请提供事件表。推荐表头为：编号、开始时间、结束时间。";
  } else {
    host.className = "hint-box";
    host.textContent = "连续时段要求完整覆盖预热、率定和验证期；洪水事件只要求每场洪水内部资料连续。";
  }
}

function clearWizardEventSummary() {
  const host = $("#wz-event-file-summary");
  if (host) host.innerHTML = "";
}

function renderWizardEventSummary(eventInfo = null, observationCoverage = null) {
  const host = $("#wz-event-file-summary");
  if (!host) return;
  if (!window.HBVStudioEventMode?.wizardEventSummaryState) {
    return;
  }
  const summary = window.HBVStudioEventMode.wizardEventSummaryState(eventInfo, observationCoverage, {
    escapeHtml,
    statusClass: focusStatusClass,
    shortPath,
  });
  applyDomUpdates(summary.domUpdates);
}

function clearBoundaryPreview() {
  const host = $("#wz-boundary-preview");
  if (host) host.innerHTML = "";
}

function taskPrimaryTitle(task) {
  return window.HBVStudioTaskView?.taskPrimaryTitle(task) || taskTypeLabel(task?.task_type);
}

function taskContextSummary(task) {
  return window.HBVStudioTaskView?.taskContextSummary(task, {
    workspaceLabelByPath,
    shortPath,
    samePath,
    profileLabel,
  }) || "";
}

function cleanTaskLogMessage(line) {
  return window.HBVStudioTaskView?.cleanTaskLogMessage(line) || String(line || "").trim();
}

function taskLastMeaningfulLog(task) {
  return window.HBVStudioTaskView?.taskLastMeaningfulLog(task, { shortPath }) || "";
}

function renderTaskMilestones(task) {
  return window.HBVStudioTaskView?.renderTaskMilestones(task, { escapeHtml }) || "";
}

function taskSummaryLine(task) {
  return window.HBVStudioTaskView?.taskSummaryLine(task, {
    shortPath,
    formatNumber,
    formatDurationSeconds,
    optimizationResultLabel,
    optimizationRefineSummary,
  }) || "";
}

function renderTaskActions(task) {
  return window.HBVStudioTaskView?.renderTaskActions(task, { escapeHtml, samePath }) || "";
}

function taskDebugDetails(task, { lines = 80 } = {}) {
  return window.HBVStudioTaskView?.taskDebugDetails(task, { lines }, {
    escapeHtml,
    taskDebugOpen: state.taskDebugOpen,
  }) || "";
}

function dataPathAlias(path, fallback = "—") {
  const alias = directoryAliasLabel(path || "");
  if (alias) return alias;
  return shortPath(path) || fallback;
}

function dataCacheSummary(meta) {
  return window.HBVStudioResultMetadata.dataCacheSummary(meta);
}

function glacierModuleSummary(meta) {
  return window.HBVStudioResultMetadata.glacierModuleSummary(meta);
}

function boundaryModuleSummary(meta) {
  return window.HBVStudioResultMetadata.boundaryModuleSummary(meta);
}


function boundaryEnabledFromMeta(meta) {
  return window.HBVStudioResultMetadata.boundaryEnabledFromMeta(meta);
}


function replayCompatibilityInfo(meta) {
  return window.HBVStudioResultMetadata.replayCompatibilityInfo(meta, { shortPath });
}


function optimizationResultLabel(optimization) {
  return window.HBVStudioResultMetadata.optimizationResultLabel(optimization);
}

function optimizationRefineSummary(optimization) {
  return window.HBVStudioResultMetadata.optimizationRefineSummary(optimization);
}

function optimizationPolishSummary(optimization) {
  return window.HBVStudioResultMetadata.optimizationPolishSummary(optimization);
}

function optimizationSummary(meta) {
  return window.HBVStudioResultMetadata.optimizationSummary(meta, {
    optimizationMethodLabel,
    formatNumber,
  });
}

function runPrecipSummary(meta) {
  return window.HBVStudioResultMetadata.runPrecipSummary(meta, {
    dataPathAlias,
    getConfiguredPrecipSourceLabel,
    getRuntimePrecipDirectoryLabel,
  });
}

function componentFractionReport(meta = {}) {
  return window.HBVStudioResultMetadata.componentFractionReport(meta);
}

function componentFractionText(report = {}) {
  return window.HBVStudioResultMetadata.componentFractionText(report);
}

function componentFractionBasisText(report = {}) {
  return window.HBVStudioResultMetadata.componentFractionBasisText(report);
}

function glacierFractionReport(meta) {
  return window.HBVStudioResultMetadata.glacierFractionReport(meta);
}

function glacierFractionValue(report) {
  return window.HBVStudioResultMetadata.glacierFractionValue(report);
}

function analyzeIceContribution(data) {
  return window.HBVStudioResultMetadata.analyzeIceContribution(data);
}

function iceContributionDetailText(analysis) {
  return window.HBVStudioResultMetadata.iceContributionDetailText(analysis);
}

function formatMetricValue(value, digits = 4, suffix = "") {
  const num = Number(value);
  return Number.isFinite(num) ? `${formatNumber(num, digits)}${suffix}` : "—";
}

function floodEventRows(meta = {}) {
  return window.HBVStudioEventMode.floodEventRows(meta, {
    formatMetricValue,
    formatNumber,
  });
}

function renderFloodEventChart(meta = {}, plotCfg = {}) {
  if (window.HBVStudioEventMode?.renderFloodEventChart) {
    window.HBVStudioEventMode.renderFloodEventChart(meta, plotCfg, { finiteNumber, formatMetricValue });
  }
}

function forecastArchiveVariableItems(archive = {}) {
  return window.HBVStudioForecastView.forecastArchiveVariableItems(archive, { timeRangeText, shortPath });
}

function forecastArchiveSummaryText(archive = {}, fallback = "未记录预报气象归档") {
  return window.HBVStudioForecastView.forecastArchiveSummaryText(archive, fallback, { timeRangeText, shortPath });
}

function forecastArchiveDetailText(archive = {}, fallback = "预报完成后将归档实际使用的降水、气温和潜在蒸散发栅格") {
  return window.HBVStudioForecastView.forecastArchiveDetailText(archive, fallback, { timeRangeText, shortPath });
}

function forecastParameterSourceSummary(source = {}, fallback = {}) {
  return window.HBVStudioForecastView.forecastParameterSourceSummary(source, fallback, {
    objectiveLabel,
    profileLabel,
    readableRunReferenceName,
  });
}

function forecastParameterContextHtml(run = {}) {
  const builder = window.HBVStudioParameterLibrary?.forecastParameterContext;
  if (!builder) return "";
  const currentProfile = normalizeCalibrationProfile(state.currentWorkspace?.率定模式, "");
  const currentContext = {
    workspace_config: state.wizardWorkspacePath || "",
    workspace_name: workspaceLabelByPath(state.wizardWorkspacePath),
    profile: currentProfile,
    time_step_hours: Number(state.currentWorkspace?.时间步长_小时 || (currentProfile === "hourly" ? 1 : 24)),
    objective_mode: $("#task-objective-mode")?.value || CURRENT_OBJECTIVE_FAMILY,
    prec_source: getTaskRuntimePrecipSource(),
    precipitation_mode: getSelectedRadio("wz-precip-mode") || state.currentWorkspace?.气象策略?.降水方案 || "",
  };
  const info = builder(run, currentContext, {
    profileLabel,
    objectiveLabel,
    precipSourceLabel: getConfiguredPrecipSourceLabel,
    stationPrecipModeLabel,
    formatNumber,
    samePath,
  });
  const rows = Array.isArray(info?.rows) ? info.rows : [];
  const statusClass = focusStatusClass(info?.status || "ok");
  return `
    <div class="forecast-parameter-context ${statusClass}">
      <div class="forecast-parameter-context-head">
        <span>参数适用性</span>
        <strong>${escapeHtml(info?.source_workspace || "未记录来源工作区")}</strong>
      </div>
      ${rows.length ? `
        <div class="forecast-parameter-context-grid">
          ${rows.map(([label, value]) => `
            <span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "—")}</strong>
          `).join("")}
        </div>
      ` : ""}
      <small>${escapeHtml(info?.note || "连续状态预报读取源结果参数和起报状态，不重新率定参数。")}</small>
    </div>
  `;
}

function restartStateRows(meta = {}) {
  return window.HBVStudioForecastView.restartStateRows(meta, {
    shortPath,
    timeRangeText,
    forecastArchiveDetailText,
    forecastArchiveSummaryText,
    forecastArchiveVariableItems,
    forecastParameterSourceSummary,
  });
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
  const content = window.HBVStudioResultsView.renderRunEngineeringSummary(data, {
    escapeHtml,
    componentFractionBasisText,
    componentFractionReport,
    componentFractionText,
    floodEventEvaluation,
    floodEventStatusText,
    hydrologySummaryValue,
    isStudioEditableRun,
    replayCompatibilityInfo,
    runTypeLabel,
    runWorkspaceFilterPath: state.runWorkspaceFilterPath,
    samePath,
    shortPath,
  });
  applyDomUpdates(content.domUpdates);
}

// --------------- API helpers ---------------

async function apiGet(path) {
  return window.HBVStudioApiClient.apiGet(path);
}

async function apiPost(path, body) {
  return window.HBVStudioApiClient.apiPost(path, body);
}

// --------------- service pill ---------------

function setServiceState(ok, msg) {
  const pill = $("#service-pill");
  pill.textContent = msg;
  pill.classList.remove("connected", "error");
  pill.classList.add(ok ? "connected" : "error");
}

// --------------- view switching ---------------

function renderDashboardView() {
  renderTemplates();
  renderWorkspaceCards();
  renderDashboardWorkspaceLayout();
}

function renderWizardView() {
  refreshWizardWorkspacePreview();
  renderPrepSteps();
}

function renderCalibrationView() {
  refreshCalibrationControls();
  renderManualPresetOptions();
  updateManualPresetControls();
}

function renderResultsView() {
  renderResultsFilterToolbar();
  renderRunList();
  if (state.currentRun) renderRunDetail(state.currentRun);
}

function renderView(view) {
  const renderer = viewRenderers[view];
  if (renderer) renderer();
}

function setView(view) {
  if (!viewMeta[view]) view = "dashboard";
  state.currentView = view;
  $all(".view").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  $all(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.viewTarget === view));
  $("#page-title").textContent    = viewMeta[view].title;
  $("#page-subtitle").textContent = viewMeta[view].subtitle;
  renderView(view);
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
  return window.HBVStudioParameterLibrary.manualPresetConfigPathFromRunData(data);
}

function getTaskManualPresetConfigPath() {
  return String(state.wizardWorkspacePath || "").trim();
}

function resolveManualPresetProfile(configPath = "", explicitProfile = "") {
  return window.HBVStudioParameterLibrary.manualPresetProfileState(configPath, explicitProfile, {
    runConfigPath: state._runData?.metadata?.workspace_config,
    runCalibrationProfile: state._runData?.metadata?.calibration_profile,
    taskConfigPath: state.wizardWorkspacePath,
    workspaceProfile: state.currentWorkspace?.率定模式,
  }, { samePath, normalizeProfile: normalizeCalibrationProfile }).profile;
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
  const controlState = window.HBVStudioParameterLibrary.manualPresetControlViewState({
    editable: isStudioEditableRun(state._runData),
    configPath: getRunManualPresetConfigPath(),
    preset: selectedManualPreset(),
    compareSeries: state.compareSeries,
    compareMetrics: state.compareMetrics,
  });
  controlState.controls.forEach(({ selector, disabled }) => {
    const el = $(selector);
    if (el) el.disabled = disabled;
  });
}

async function loadRunManualPresets(configPath = getRunManualPresetConfigPath(), { silent = false, calibrationProfile = "" } = {}) {
  const path = String(configPath || "").trim();
  const resolvedProfile = resolveManualPresetProfile(path, calibrationProfile);
  const requestToken = runManualPresetRequestGuard.next();
  const loadStart = window.HBVStudioResultsView.runManualPresetLoadStartState(path, state.runManualPresetConfigPath, { samePath });
  Object.assign(state, loadStart.statePatch);
  if (!loadStart.shouldRequest) {
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
    return [];
  }
  if (loadStart.shouldRender) {
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
  }
  try {
    const p = await apiGet(window.HBVStudioParameterLibrary.manualPresetListPath(path, resolvedProfile, "all"));
    if (!runManualPresetRequestGuard.isActive(requestToken) || !samePath(path, state.runManualPresetConfigPath)) {
      return p.data?.presets || [];
    }
    const loadSuccess = window.HBVStudioResultsView.runManualPresetLoadSuccessState(p.data || {});
    Object.assign(state, loadSuccess.statePatch);
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
    clearStaleManualPresetComparison({ silent: true });
    return loadSuccess.presets;
  } catch (err) {
    if (!runManualPresetRequestGuard.isActive(requestToken) || !samePath(path, state.runManualPresetConfigPath)) {
      return [];
    }
    const loadError = window.HBVStudioResultsView.runManualPresetLoadErrorState();
    Object.assign(state, loadError.statePatch);
    renderManualPresetOptions();
    updateManualPresetControls();
    renderManualPresetDiff();
    clearStaleManualPresetComparison({ silent: true });
    if (!silent) showToast(err.message, true);
    return loadError.presets;
  }
}

async function loadTaskManualPresets(configPath = getTaskManualPresetConfigPath(), { silent = false, calibrationProfile = "" } = {}) {
  const path = String(configPath || "").trim();
  const resolvedProfile = resolveManualPresetProfile(path, calibrationProfile);
  const requestToken = taskManualPresetRequestGuard.next();
  const loadStart = window.HBVStudioParameterLibrary.taskManualPresetLoadStartState(path, state.taskManualPresetConfigPath, { samePath });
  Object.assign(state, loadStart.statePatch);
  if (!loadStart.shouldRequest) {
    renderManualPresetOptions();
    refreshCalibrationControls();
    return [];
  }
  if (loadStart.shouldRender) {
    renderManualPresetOptions();
    refreshCalibrationControls();
  }
  try {
    const p = await apiGet(window.HBVStudioParameterLibrary.manualPresetListPath(path, resolvedProfile, "all"));
    if (!taskManualPresetRequestGuard.isActive(requestToken) || !samePath(path, state.taskManualPresetConfigPath)) {
      return p.data?.presets || [];
    }
    const loadSuccess = window.HBVStudioParameterLibrary.taskManualPresetLoadSuccessState(p.data || {});
    Object.assign(state, loadSuccess.statePatch);
    renderManualPresetOptions();
    refreshCalibrationControls();
    return loadSuccess.presets;
  } catch (err) {
    if (!taskManualPresetRequestGuard.isActive(requestToken) || !samePath(path, state.taskManualPresetConfigPath)) {
      return [];
    }
    const loadError = window.HBVStudioParameterLibrary.taskManualPresetLoadErrorState();
    Object.assign(state, loadError.statePatch);
    renderManualPresetOptions();
    refreshCalibrationControls();
    if (!silent) showToast(err.message, true);
    return loadError.presets;
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
        renderWizardEventSummary(
          result.validation?.event_windows || null,
          result.validation?.event_observation_coverage || null,
        );
      }
    }
    if (step === 1) {
      await loadWorkspaces();
      previewWorkspaceLayout(state.wizardWorkspacePath, { silent: true }).catch(() => {});
      refreshCurrentWorkspaceLayout().catch(() => {});
    } else if (step === 2) {
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
    renderWizardEventSummary(validation.event_windows || null, validation.event_observation_coverage || null);
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
  state.currentWorkspaceGeoOverview = null;
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
  state.currentWorkspaceGeoOverview = null;
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
  taskManualPresetRequestGuard.cancel();
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
    if (!host) return;
    host.innerHTML = window.HBVStudioDataPrepView?.renderBootstrapStatus(items, { escapeHtml })
      || '<div class="hint-box">暂无 GIS 步骤状态信息。</div>';
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
  const logBox = $("#resim-log");
  if (!logBox || !task) return;
  const uiState = window.HBVStudioResultsView.forwardSimulationTaskUiState(
    task,
    { nowSeconds: Date.now() / 1000 },
    { formatDurationSeconds, formatNumber },
  );
  if (!uiState.shouldRender) return;
  applyDomUpdates(uiState.domUpdates);
  setLogBoxContent(logBox, uiState.log.lines, "results:resim-log");
}

function applyForwardSimulationResult(result) {
  const resultState = window.HBVStudioResultsView.forwardSimulationResultState(result);
  if (!resultState.ok) return;
  renderCharts(resultState.chartData);
  updateMetricsStrip(
    resultState.calibrationMetrics,
    resultState.validationMetrics,
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
      const errorState = window.HBVStudioResultsView.forwardSimulationPollingErrorState(err);
      applyDomUpdates(errorState.domUpdates);
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

function formatPrepDisplayTitle(index, title) {
  return window.HBVStudioDataPrepView?.formatPrepDisplayTitle(index, title) || `${index}. ${String(title || "").replace(/^\d+\.\s*/, "").trim()}`;
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
  const summary = window.HBVStudioDataPrepView.prepPanelSummary(getWizardMeteoSources());
  hint.textContent = summary.text;
  hint.className = summary.className;
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
  const requestToken = cdsApiStatusRequestGuard.next();
  state.cdsApiNeedSignature = needSignature;
  state.cdsApiStatus = { loading: true };
  renderEra5ApiPanel();
  try {
    const payload = await apiGet("/api/cdsapi/status");
    if (!cdsApiStatusRequestGuard.isActive(requestToken)) return;
    state.cdsApiStatus = payload.data || {};
  } catch (err) {
    if (!cdsApiStatusRequestGuard.isActive(requestToken)) return;
    state.cdsApiStatus = { error: err.message };
  }
  renderEra5ApiPanel();
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
  if (!host) return;
  if (!state.wizardWorkspacePath) {
    host.innerHTML = window.HBVStudioDataPrepView?.renderPrepStepList(
      { workspaceSelected: false },
      { escapeHtml },
    ) || '<div class="hint-box">先选择或创建工作区。</div>';
    return;
  }
  const steps = buildVisiblePrepSteps();
  updatePrepPanelSummary(steps);
  host.innerHTML = window.HBVStudioDataPrepView?.renderPrepStepList(
    {
      workspaceSelected: true,
      steps,
      prepStatus: state.prepStatus,
      allSteps: state.prepSteps,
    },
    {
      escapeHtml,
      isGisStepId: id => GIS_STEP_IDS.has(id),
    },
  ) || "";
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
  const uiState = window.HBVStudioDataPrepView.prepTaskUiState(task);
  hint.style.display = uiState.hint.visible ? "" : "none";
  hint.textContent = uiState.hint.text;
  hint.className = uiState.hint.className;
  if (uiState.log.visible) {
    logBox.style.display = "";
    setLogBoxContent(logBox, uiState.log.lines, uiState.log.key);
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
    host.innerHTML = window.HBVStudioDataPrepView.renderInputCheckImportBlock(runningImport, { escapeHtml });
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
    host.innerHTML = window.HBVStudioDataPrepView.renderInputCheckProgress({ stage: checkStage, elapsed }, { escapeHtml });
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

    const html = window.HBVStudioDataPrepView.renderInputCheckResults({
      validation,
      comp,
      detail,
      stage,
      detailData,
      advice,
    }, {
      escapeHtml,
      inferIssueTarget,
      renderEngineeringFocusChecks,
      renderIssueJumpButton,
      renderValidationEventSections: value => window.HBVStudioEventMode.renderValidationEventSections(value, {
        escapeHtml,
        statusClass: focusStatusClass,
        shortPath,
      }),
    });

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
    host.innerHTML = window.HBVStudioDataPrepView.renderInputCheckError({
      message: err.message,
      stage: checkStage,
      elapsed,
    }, { escapeHtml });
    return null;
  }
}

// ===============================================================
//  DASHBOARD
// ===============================================================

function renderWorkspaceCards() {
  if (!state.workspaces.length) {
    state.dashboardWorkspaceLayout = null;
    state.dashboardGeoOverview = null;
    state.dashboardLayoutPath = "";
    const cards = window.HBVStudioDashboardView.workspaceCardsState([], { escapeHtml });
    applyDomUpdates(cards.domUpdates);
    return;
  }
  const cards = window.HBVStudioDashboardView.workspaceCardsState(state.workspaces, {
    escapeHtml,
    objectLabels,
    profileBadge,
    selectedPath: state.dashboardLayoutPath,
    shortPath,
    workspaceNextStepText,
  });
  applyDomUpdates(cards.domUpdates);
}

function renderTemplates() {
  const templates = window.HBVStudioDashboardView.templateListState(state.templates, {
    escapeHtml,
    objectLabels,
    profileBadge,
  });
  applyDomUpdates(templates.domUpdates);
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
  return window.HBVStudioParameterLibrary.findPresetById(state.runManualPresets, presetId);
}

function applyManualPresetToCurrentRun(preset) {
  const applied = window.HBVStudioParameterLibrary.manualPresetApplyState(
    state._runParams,
    state._runOrigParams,
    preset,
    { contextWarning: manualPresetContextWarning(preset) },
  );
  if (!applied.applied) return;
  state._runParams = applied.params;
  applied.paramUpdates.forEach(({ name, value, changed }) => {
    const slider = $(`[data-param-slider="${name}"]`);
    const input = $(`[data-param-input="${name}"]`);
    if (slider) slider.value = value;
    if (input) input.value = value;
    const item = slider?.closest(".param-slider-item");
    if (item) item.classList.toggle("changed", changed);
  });
  applyDomUpdates(applied.domUpdates);
  updateManualChangeSummary();
}

async function saveCurrentManualPreset() {
  const configPath = getRunManualPresetConfigPath();
  const name = $("#manual-preset-name").value.trim();
  const preflight = window.HBVStudioParameterLibrary.manualPresetSavePreflight({
    configPath,
    editable: isStudioEditableRun(state._runData),
    name,
    params: state._runParams,
    runData: state._runData,
  });
  if (!preflight.ok) {
    showToast(preflight.message, true);
    return;
  }
  const payload = await apiPost("/api/manual-preset/save", window.HBVStudioParameterLibrary.manualPresetSavePayload({
    configPath,
    scope: $("#manual-preset-scope")?.value || "workspace",
    runData: state._runData,
    workspaceProfile: state.currentWorkspace?.率定模式,
    objectiveMode: effectiveObjectiveMode(state._runData?.metadata || {}),
    paramBoundsProfile: $("#task-param-bounds-profile")?.value,
    runtimePrecipSource: getTaskRuntimePrecipSource(),
    glacierMode: $("#task-glacier-mode")?.value,
    name,
    params: state._runParams,
  }));
  await loadRunManualPresets(configPath, { silent: true });
  const taskSync = window.HBVStudioParameterLibrary.manualPresetTaskSyncState(configPath, getTaskManualPresetConfigPath(), {
    workspaceProfile: state.currentWorkspace?.率定模式,
    runCalibrationProfile: state._runData?.metadata?.calibration_profile,
  }, { samePath });
  if (taskSync.shouldSync) {
    await loadTaskManualPresets(taskSync.sourceConfigPath, {
      silent: true,
      calibrationProfile: taskSync.calibrationProfile,
    });
  }
  const saveState = window.HBVStudioParameterLibrary.manualPresetSaveSuccessState(payload.data || {}, name);
  const saveSelection = window.HBVStudioParameterLibrary.manualPresetSaveSelectionState(saveState.savedId, taskSync);
  if ($("#manual-preset-select")) $("#manual-preset-select").value = saveSelection.runPresetSelectValue;
  if (saveSelection.shouldSelectTaskPreset && $("#task-init-preset")) $("#task-init-preset").value = saveSelection.taskPresetSelectValue;
  updateManualPresetControls();
  refreshCalibrationControls();
  renderManualPresetDiff();
  showToast(saveState.toastText);
}

async function loadSelectedManualPreset() {
  const preset = selectedManualPreset();
  const preflight = window.HBVStudioParameterLibrary.manualPresetLoadPreflight(preset);
  if (!preflight.ok) {
    showToast(preflight.message, true);
    return;
  }
  const loadState = window.HBVStudioParameterLibrary.manualPresetLoadSuccessState(preflight.preset, preflight.presetName);
  $("#manual-preset-name").value = loadState.inputName;
  applyManualPresetToCurrentRun(preflight.preset);
  renderManualPresetDiff();
  showToast(loadState.toastText);
}

async function deleteSelectedManualPreset() {
  const preset = selectedManualPreset();
  const configPath = getRunManualPresetConfigPath();
  const preflight = window.HBVStudioParameterLibrary.manualPresetDeletePreflight(configPath, preset);
  if (!preflight.ok) {
    showToast(preflight.message, true);
    return;
  }
  const deleteView = window.HBVStudioParameterLibrary.manualPresetDeleteViewState(preflight.presetName);
  if (!window.confirm(deleteView.confirmText)) return;
  await apiPost("/api/manual-preset/delete", window.HBVStudioParameterLibrary.manualPresetDeletePayload(preflight.configPath, preflight.preset));
  await loadRunManualPresets(preflight.configPath, { silent: true });
  const taskSync = window.HBVStudioParameterLibrary.manualPresetTaskSyncState(preflight.configPath, getTaskManualPresetConfigPath(), {
    workspaceProfile: state.currentWorkspace?.率定模式,
    runCalibrationProfile: state._runData?.metadata?.calibration_profile,
  }, { samePath });
  if (taskSync.shouldSync) {
    await loadTaskManualPresets(taskSync.sourceConfigPath, {
      silent: true,
      calibrationProfile: taskSync.calibrationProfile,
    });
  }
  const deleteSuccess = window.HBVStudioParameterLibrary.manualPresetDeleteSuccessState(preflight, state.comparePresetId);
  if (deleteSuccess.shouldClearComparison) clearManualPresetComparison(deleteSuccess.clearComparisonOptions);
  if ($("#manual-preset-name")) $("#manual-preset-name").value = deleteSuccess.inputName;
  refreshCalibrationControls();
  renderManualPresetDiff();
  showToast(deleteView.toastText);
}

function renderRunList() {
  const host = $("#run-list");
  const selectedRunPath = currentSelectedRunPath();
  const workspaceFilterPath = String(state.runWorkspaceFilterPath || "").trim();
  const workspaceRunCount = workspaceFilterPath ? runsForWorkspace(workspaceFilterPath).length : state.runs.length;
  renderResultsFilterToolbar();
  const runs = visibleRuns();
  const listState = window.HBVStudioResultsView.runListState({
    totalRuns: state.runs.length,
    visibleCount: runs.length,
    workspaceFilterPath,
    workspaceRunCount,
    workspaceFilterLabel: workspaceFilterPath ? workspaceLabelByPath(workspaceFilterPath) : "",
    manualStarterWorkspaceLabel: manualStarterWorkspacePath() ? workspaceLabelByPath(manualStarterWorkspacePath()) : "",
    hasCurrentRun: Boolean(state.currentRun),
  }, { escapeHtml });
  if (listState.updateHint) {
    applyDomUpdates(listState.domUpdates);
  }
  if (listState.status !== "ready") {
    host.innerHTML = listState.listHtml;
    updateManualStarterButtons();
    return;
  }
  updateManualStarterButtons();
  const cards = window.HBVStudioResultsView.runCardsState(runs, {
    escapeHtml,
    formatMetricValue,
    formatNumber,
    hydrologySummaryValue,
    objectiveVersionBadge,
    runDisplayName,
    runDisplaySubtitle,
    runTypeBadge,
    runWorkspaceFilterPath: state.runWorkspaceFilterPath,
    runWorkspaceName,
    samePath,
    selectedRunPath,
  });
  applyDomUpdates(cards.domUpdates);
}

function renderRunDetail(data) {
  const detailState = window.HBVStudioResultsView.runDetailState(data, {
    selectedRunPath: state.selectedRunPath,
  }, { isStudioEditableRun });
  const { metadata: meta, calibrationMetrics: cal, validationMetrics: val } = detailState;
  compareRequestGuard.cancel();
  Object.assign(state, detailState.statePatch);

  renderRunEngineeringSummary(data);
  updateMetricsStrip(cal, val, meta);
  configureRunExportPanel(data);
  renderCharts(data);
  updateManualGroupToolbar();
  renderParamSliders(data);
  applyDomUpdates(detailState.domUpdates);
  if (detailState.shouldUpdateManualPresetControls) updateManualPresetControls();
  if (detailState.shouldRenderManualPresetDiff) renderManualPresetDiff();
  if (detailState.shouldUpdateCompareSummary) updateCompareSummary();
  if (detailState.shouldUpdateManualStarterButtons) updateManualStarterButtons();

  const detailMetadata = window.HBVStudioResultsView.renderRunDetailMetadata(data, {
    compactTimeText,
    componentFractionBasisText,
    componentFractionReport,
    componentFractionText,
    currentRunStepHours,
    escapeHtml,
    floodEventRows,
    hydrologySummaryValue,
    isStudioEditableRun,
    paramBoundsProfileLabels: PARAM_BOUNDS_PROFILE_LABELS,
    restartStateRows,
    runMetricsText,
    runTypeLabel,
    shortPath,
    timeRangeText,
    workspaceLabelByPath,
  });
  applyDomUpdates(detailMetadata.domUpdates);
}

function updateMetricsStrip(cal, val, meta) {
  const items = window.HBVStudioResultsView.resultMetricItems(cal, val, meta, {
    profileLabel,
    formatNumber,
    eventMetricItems: item => window.HBVStudioEventMode.floodEventMetricItems(item, { formatNumber }),
  });
  const strip = window.HBVStudioResultsView.resultMetricStripState(items, { escapeHtml });
  applyDomUpdates(strip.domUpdates);
}

function renderRunExportFields() {
  const host = $("#run-export-fields");
  if (!host) return;
  const fields = window.HBVStudioResultsView.runExportFields({
    boundaryEnabled: boundaryEnabledFromMeta(state.currentRun?.metadata || {}),
  });
  const rendered = window.HBVStudioResultsView.runExportFieldsState(fields, { escapeHtml });
  applyDomUpdates(rendered.domUpdates);
}

function currentRunStepHours(data = state.currentRun) {
  return window.HBVStudioResultsView.runStepHours(data);
}

function configureRunExportPanel(data) {
  renderRunExportFields();
  const panel = window.HBVStudioResultsView.runExportPanelState(data, {
    lastExportPath: state.lastRunExportPath,
  }, {
    formatInputTime: toWizardInputTimeValue,
  });
  applyDomUpdates(panel.domUpdates);
}

function selectedRunExportFields() {
  return window.HBVStudioResultsView.selectedRunExportFields($all("[data-run-export-field]"));
}

async function exportCurrentRunExcel() {
  const exportRequest = window.HBVStudioResultsView.runExportPayload(
    state.currentRun,
    selectedRunExportFields(),
    {
      start: $("#run-export-start")?.value || "",
      end: $("#run-export-end")?.value || "",
    },
    { fromInputTime: fromWizardInputTimeValue },
  );
  if (!exportRequest.ok) {
    showToast(exportRequest.message, true);
    return;
  }
  const payload = await apiPost("/api/run/export-excel", exportRequest.payload);
  const exportSuccess = window.HBVStudioResultsView.runExportSuccess(payload.data || {}, { shortPath });
  Object.assign(state, exportSuccess.statePatch);
  applyDomUpdates(exportSuccess.domUpdates);
  showToast(exportSuccess.toastText);
}

function renderCharts(data) {
  const drawPlot = (id, traces, layout, config) => {
    const host = document.getElementById(id);
    if (!host || !window.Plotly) return;
    try { window.Plotly.purge(host); } catch {}
    host.innerHTML = "";
    try {
      const plot = Plotly.newPlot(host, traces, layout, config);
      if (plot && typeof plot.catch === "function") plot.catch(() => {});
    } catch {}
  };
  const plotCfg = { responsive: true };
  const chartPayloads = window.HBVStudioResultsView.resultChartPayloads(data, {
    compareSeries: state.compareSeries,
    compareLabel: state.compareLabel,
    boundaryEnabled: boundaryEnabledFromMeta(data?.metadata || {}),
  }, { colors });
  drawPlot("hydrograph-chart", chartPayloads.hydrograph.traces, chartPayloads.hydrograph.layout, plotCfg);
  renderFloodEventChart(data?.metadata || {}, plotCfg);
  drawPlot("component-chart", chartPayloads.component.traces, chartPayloads.component.layout, plotCfg);
  drawPlot("residual-chart", chartPayloads.residual.traces, chartPayloads.residual.layout, plotCfg);
}

function renderParamSliders(data) {
  const meta = data.metadata || {};
  const params = meta.optimized_params || {};
  const bounds = meta.parameter_profile?.bounds || {};
  const rendered = window.HBVStudioParameterLibrary.renderParamSliders({
    editable: isStudioEditableRun(data),
    params,
    bounds,
    group: state.manualParamGroup,
    groupParams: MANUAL_GROUP_PARAMS,
    labels: PARAM_LABELS,
  }, { escapeHtml });
  applyDomUpdates(rendered.domUpdates);
  updateManualPhaseGuide(rendered.paramNames || []);
  if (rendered.status !== "ready") {
    updateManualChangeSummary();
    return;
  }

  // Bind slider ↔ input sync
  $all("[data-param-slider]").forEach(slider => {
    const name = slider.dataset.paramSlider;
    const input = $(`[data-param-input="${name}"]`);
    const item = slider.closest(".param-slider-item");
    const applyValue = numeric => {
      const update = window.HBVStudioParameterLibrary.manualParamUpdateState(
        state._runParams,
        state._runOrigParams,
        name,
        numeric,
      );
      if (!update.applied) return;
      state._runParams = update.params;
      item.classList.toggle("changed", update.changed);
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
  const reset = window.HBVStudioParameterLibrary.manualParamResetViewState(state._runOrigParams, state._runData);
  if (!reset.reset) return;
  state._runParams = reset.params;
  reset.paramUpdates.forEach(({ name, value, changed }) => {
    const slider = $(`[data-param-slider="${name}"]`);
    const input = $(`[data-param-input="${name}"]`);
    if (slider) slider.value = value;
    if (input) input.value = value;
    const item = slider?.closest(".param-slider-item");
    if (item) item.classList.toggle("changed", changed);
  });
  if (reset.shouldRestoreRun) renderCharts(reset.chartData);
  if (reset.shouldUpdateMetrics) updateMetricsStrip(reset.calibrationMetrics, reset.validationMetrics, reset.metricMetadata);
  applyDomUpdates(reset.domUpdates);
  updateManualChangeSummary();
  updateCompareSummary();
}

async function runForwardSimulation() {
  const preflight = window.HBVStudioResultsView.forwardSimulationPreflight(
    state._runData,
    state._runParams,
    { isStudioEditableRun },
  );
  if (!preflight.ok) {
    showToast(preflight.message, true);
    return;
  }
  const startState = window.HBVStudioResultsView.forwardSimulationStartState();
  applyDomUpdates(startState.domUpdates);
  const requestContext = window.HBVStudioResultsView.forwardSimulationRequestContext(state._runData, state._runParams);
  try {
    const payload = await apiPost("/api/simulate/forward/start", requestContext.payload);
    const task = payload.task;
    if (task) {
      updateForwardSimUi(task);
      await loadTasks();
      await pollForwardSimulationTask(task.id, requestContext.runPath);
    }
  } catch (err) {
    const errorState = window.HBVStudioResultsView.forwardSimulationErrorState(err);
    applyDomUpdates(errorState.domUpdates);
  }
}

async function compareSelectedManualPresetSimulation() {
  const preset = selectedManualPreset();
  const preflight = window.HBVStudioResultsView.runComparisonPreflight(preset, state._runData, { isStudioEditableRun });
  if (!preflight.ok) {
    showToast(preflight.message, true);
    return;
  }
  const pendingView = window.HBVStudioParameterLibrary.manualPresetComparePendingView(preset);
  applyDomUpdates(pendingView.domUpdates);
  const requestToken = compareRequestGuard.next();
  const requestContext = window.HBVStudioResultsView.runComparisonRequestContext(preset, state._runData);
  try {
    const payload = await apiPost("/api/simulate/forward", requestContext.payload);
    if (!compareRequestGuard.isActive(requestToken)) return;
    if (!window.HBVStudioResultsView.runComparisonRequestStillCurrent(requestContext, state._runData, selectedManualPreset(), { samePath })) return;
    const successState = window.HBVStudioResultsView.runComparisonSuccessState(preset, payload.data || {});
    Object.assign(state, successState.statePatch);
    renderCharts(state._runData);
    updateCompareSummary();
    updateManualPresetControls();
    showToast(successState.toastText);
  } catch (err) {
    if (!compareRequestGuard.isActive(requestToken)) return;
    const errorState = window.HBVStudioResultsView.runComparisonErrorState(err, {
      compareErrorView: window.HBVStudioParameterLibrary.manualPresetCompareErrorView,
    });
    Object.assign(state, errorState.statePatch);
    if (state._runData) {
      renderCharts(state._runData);
      const meta = state._runData?.metadata || {};
      const cal = meta.metrics?.calibration || {};
      const val = meta.metrics?.validation || {};
      updateMetricsStrip(cal, val, meta);
    }
    applyDomUpdates(errorState.domUpdates);
    updateManualPresetControls();
    showToast(errorState.toastText, true);
  }
}

// ===============================================================
//  TASKS
// ===============================================================

function renderTaskProgressCharts() {
  if (typeof Plotly === "undefined") return;
  document.querySelectorAll("[data-task-progress-chart]").forEach(host => {
    const taskId = host.dataset.taskProgressChart;
    const stage = host.dataset.taskProgressStage || "global";
    const task = state.tasks.find(item => item.id === taskId);
    const histories = task?.progress?.stages || {};
    const stageHistory = histories?.[stage]?.history || task?.progress?.history || [];
    const chart = window.HBVStudioTaskView.taskProgressChartData(stageHistory, taskStageLabel(stage), { colors });
    if (!chart) return;
    try {
      const plot = Plotly.newPlot(host, chart.traces, chart.layout, {
        responsive: true,
        displayModeBar: false,
        staticPlot: true,
      });
      if (plot && typeof plot.catch === "function") plot.catch(() => {});
    } catch {}
  });
}

function renderTasks() {
  renderTaskFilterToolbar();
  const taskList = window.HBVStudioTaskView.taskListState(visibleTasks(), {
    escapeHtml,
    formatDateTime,
    formatDurationSeconds,
    formatNumber,
    optimizationRefineSummary,
    optimizationResultLabel,
    profileLabel,
    samePath,
    shortPath,
    taskDebugOpen: state.taskDebugOpen,
    workspaceLabelByPath,
  });
  applyDomUpdates(taskList.domUpdates);
  restoreVisibleLogViewports("#task-list [data-log-key]");
  renderTaskProgressCharts();
}

// ===============================================================
//  FORECAST RESTART
// ===============================================================

function forecastCandidateRuns() {
  return window.HBVStudioForecastView.forecastCandidateRuns(state.runs, { runTypeValue });
}

function forecastRunReady(run) {
  return window.HBVStudioForecastView.forecastRunReady(run);
}

function forecastRunReadinessText(run) {
  return window.HBVStudioForecastView.forecastRunReadinessText(run);
}

function selectedForecastRun() {
  const selectedPath = $("#forecast-source-run")?.value || state.forecastSourceRunPath || "";
  return window.HBVStudioForecastView.forecastSelectedSourceRun(forecastCandidateRuns(), selectedPath, { samePath });
}

function forecastInputType(run) {
  return window.HBVStudioForecastView.forecastInputType(run);
}

function forecastSuggestedStart(run) {
  return window.HBVStudioForecastView.forecastSuggestedStart(run);
}

function forecastTimeComparable(value, run) {
  return window.HBVStudioForecastView.forecastTimeComparable(value, run);
}

function renderForecastSourceOptions() {
  const select = $("#forecast-source-run");
  if (!select) return;
  const candidates = forecastCandidateRuns();
  const current = state.forecastSourceRunPath || currentSelectedRunPath() || "";
  const sourceOptionsState = window.HBVStudioForecastView.forecastSourceOptionsState(candidates, current, { samePath, forecastRunReady });
  Object.assign(state, sourceOptionsState.statePatch);
  const rendered = window.HBVStudioForecastView.renderForecastSourceOptions(
    candidates,
    sourceOptionsState.selectedPath,
    { escapeHtml, forecastFriendlyRunName, forecastRunReadinessText, samePath },
  );
  applyDomUpdates(rendered.domUpdates);
}

function renderForecastSourceSummary() {
  const host = $("#forecast-source-summary");
  if (!host) return;
  const run = selectedForecastRun();
  const buttons = window.HBVStudioForecastView.forecastSourceButtonState(run, { forecastRunReady });
  applyDomUpdates(buttons.domUpdates);
  const rendered = window.HBVStudioForecastView.renderForecastSourceSummary(run, {
    escapeHtml,
    forecastArchiveDetailText,
    forecastArchiveSummaryText,
    forecastFriendlyRunName,
    forecastParameterContextHtml,
    forecastParameterSourceSummary,
    forecastRunReady,
    forecastRunReadinessText,
    forecastSuggestedStart,
    objectiveLabel,
    profileLabel,
    runDisplayName,
    runProfileValue,
    runTypeLabel,
    runTypeValue,
    runWorkspaceName,
  });
  if (run) {
    const inputType = forecastInputType(run);
    ["forecast-start", "forecast-end"].forEach(id => {
      const input = document.getElementById(id);
      if (input && input.type !== inputType) input.type = inputType;
    });
  }
  const startInput = $("#forecast-start");
  if (startInput && rendered.suggestedStart && !startInput.value) startInput.value = rendered.suggestedStart;
  applyDomUpdates(rendered.domUpdates);
}

function forecastInputPayload(run = selectedForecastRun()) {
  return window.HBVStudioForecastView.forecastInputPayload(run, {
    forecast_start: $("#forecast-start")?.value,
    forecast_end: $("#forecast-end")?.value,
    forecast_prec_dir: $("#forecast-prec-dir")?.value,
    forecast_temp_dir: $("#forecast-temp-dir")?.value,
    forecast_evap_dir: $("#forecast-evap-dir")?.value,
  }, { fallbackConfigPath: state.wizardWorkspacePath });
}

function renderForecastInputSummary(check = null, stateLabel = "") {
  if (!window.HBVStudioForecastView?.renderForecastInputSummary) return;
  window.HBVStudioForecastView.renderForecastInputSummary(check, stateLabel, {
    escapeHtml,
    focusStatusClass,
    focusStatusLabel,
    formatNumber,
    shortPath,
    renderParameterContextHtml: forecastParameterContextHtml,
    renderStationScopeSummary: window.HBVStudioStationPrecip?.renderTaskScopeSummary,
  });
}

async function refreshForecastInputCheck({ loading = false } = {}) {
  const run = selectedForecastRun();
  if (!run?.path) {
    forecastInputCheckRequestGuard.cancel();
    renderForecastInputSummary(null);
    return null;
  }
  const requestToken = forecastInputCheckRequestGuard.next();
  if (loading) renderForecastInputSummary(null, "loading");
  try {
    const response = await apiPost("/api/forecast/input-check", forecastInputPayload(run));
    if (!forecastInputCheckRequestGuard.isActive(requestToken)) return;
    const check = response.data || null;
    renderForecastInputSummary(check);
    return check;
  } catch (err) {
    if (!forecastInputCheckRequestGuard.isActive(requestToken)) return;
    const check = window.HBVStudioForecastView.forecastInputCheckError(err);
    renderForecastInputSummary(check);
    return check;
  }
}

function scheduleForecastInputCheck(delay = 350) {
  clearTimeout(state.forecastInputCheckTimer);
  const delayMs = window.HBVStudioForecastView.forecastInputCheckDelay(delay);
  const timer = setTimeout(() => {
    refreshForecastInputCheck().catch(err => showToast(err.message, true));
  }, delayMs);
  Object.assign(state, window.HBVStudioForecastView.forecastInputCheckTimerState(timer).statePatch);
}

function renderForecastTaskList() {
  const host = $("#forecast-task-list");
  if (!host) return;
  const taskList = window.HBVStudioForecastView.forecastTaskListState(state.tasks, {
    escapeHtml,
    focusStatusClass,
    focusStatusLabel,
    formatDateTime,
    renderTaskActions,
    renderTaskMilestones,
    shortPath,
    taskDebugDetails,
    taskPrimaryTitle,
    taskStatusClass,
    taskStatusLabel,
    taskSummaryLine,
    taskTypeLabel,
  });
  applyDomUpdates(taskList.domUpdates);
  restoreVisibleLogViewports("#forecast-task-list [data-log-key]");
}

function forecastResultRuns() {
  return window.HBVStudioForecastView.forecastResultRuns(state.runs, { runTypeValue });
}

function selectedForecastResultRun() {
  const selectedPath = $("#forecast-result-run")?.value || state.forecastResultRunPath || "";
  return window.HBVStudioForecastView.forecastSelectedResultRun(forecastResultRuns(), selectedPath, { samePath });
}

function setForecastResultButtons(run) {
  const buttons = window.HBVStudioForecastView.forecastResultButtonState(run, state.lastForecastExportPath);
  applyDomUpdates(buttons.domUpdates);
}

function renderForecastResultDetail(data = state.forecastResultData) {
  const detailState = window.HBVStudioForecastView.forecastResultDetailState(data, selectedForecastResultRun());
  setForecastResultButtons(detailState.buttonRun);
  if (!window.HBVStudioForecastView) return;
  if (detailState.renderMode === "empty") {
    window.HBVStudioForecastView.renderForecastResultEmpty("完成连续状态预报后，将在这里查看过程线、起报依据和输入资料。");
    return;
  }
  window.HBVStudioForecastView.renderForecastResultDetail(detailState.detailData, {
    escapeHtml,
    runDisplayName: forecastFriendlyRunName,
    shortPath,
    timeRangeText,
    forecastArchiveSummaryText,
    forecastArchiveDetailText,
    forecastParameterSourceSummary,
    profileLabel,
  });
}

async function loadForecastResultDetail(path) {
  const loadStart = window.HBVStudioForecastView.forecastResultLoadStartState(path);
  if (!loadStart.ok) {
    forecastResultRequestGuard.cancel();
    return;
  }
  const requestToken = forecastResultRequestGuard.next();
  Object.assign(state, loadStart.statePatch);
  if (window.HBVStudioForecastView) {
    window.HBVStudioForecastView.renderForecastResultLoading("正在读取连续状态预报结果。");
  }
  setForecastResultButtons(loadStart.buttonRun);
  try {
    const payload = await apiGet(`/api/run?path=${encodeURIComponent(loadStart.targetPath)}`);
    if (!forecastResultRequestGuard.isActive(requestToken) || !samePath(loadStart.targetPath, state.forecastResultRunPath)) return;
    const loadSuccess = window.HBVStudioForecastView.forecastResultLoadSuccessState(payload.data);
    Object.assign(state, loadSuccess.statePatch);
    renderForecastResultDetail(loadSuccess.detailData);
  } catch (err) {
    if (!forecastResultRequestGuard.isActive(requestToken)) return;
    const loadError = window.HBVStudioForecastView.forecastResultLoadErrorState(err);
    Object.assign(state, loadError.statePatch);
    if (window.HBVStudioForecastView) {
      window.HBVStudioForecastView.renderForecastResultEmpty(`预报结果读取失败：${err.message}`);
    }
    setForecastResultButtons(loadError.buttonRun);
  }
}

function renderForecastResultPanel() {
  const select = $("#forecast-result-run");
  if (!select) return;
  const runs = forecastResultRuns();
  const panel = window.HBVStudioForecastView.forecastResultPanelState(
    runs,
    state.forecastResultRunPath,
    { currentData: state.forecastResultData, loadingPath: state.forecastResultLoadingPath },
    { samePath },
  );
  const rendered = window.HBVStudioForecastView.renderForecastResultOptions(
    runs,
    panel.selectedPath,
    { escapeHtml, forecastFriendlyRunName, samePath, timeRangeText },
  );
  if (!panel.hasRuns) {
    forecastResultRequestGuard.cancel();
    Object.assign(state, panel.statePatch);
    applyDomUpdates(rendered.domUpdates);
    setForecastResultButtons(null);
    if (window.HBVStudioForecastView) {
      window.HBVStudioForecastView.renderForecastResultEmpty("完成连续状态预报后，将在这里查看过程线、起报依据和输入资料。");
    }
    return;
  }
  const selected = panel.selected || rendered.selected || runs[0];
  Object.assign(state, panel.statePatch);
  applyDomUpdates(rendered.domUpdates);
  setForecastResultButtons(selected);
  if (panel.renderMode === "detail") {
    renderForecastResultDetail(state.forecastResultData);
  } else if (panel.renderMode === "loading") {
    if (window.HBVStudioForecastView) {
      window.HBVStudioForecastView.renderForecastResultLoading("正在读取连续状态预报结果。");
    }
  } else if (panel.loadPath) {
    loadForecastResultDetail(panel.loadPath).catch(err => showToast(err.message, true));
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
  const exportPayload = window.HBVStudioForecastView.forecastResultExportPayload(data, run, { boundaryEnabledFromMeta });
  if (!exportPayload) {
    showToast("当前没有可导出的预报结果。", true);
    return;
  }
  const payload = await apiPost("/api/run/export-excel", exportPayload);
  const exportState = window.HBVStudioForecastView.forecastResultExportState(payload.data || {});
  Object.assign(state, exportState.statePatch);
  setForecastResultButtons(run || data?.run);
  const exportSuccess = window.HBVStudioForecastView.forecastResultExportSuccess(
    payload.data || {},
    exportState.exportPath,
    { shortPath },
  );
  applyDomUpdates(exportSuccess.domUpdates);
  showToast(exportSuccess.toastText);
}

function renderForecastView() {
  if (!$("#forecast-source-run")) return;
  renderForecastSourceOptions();
  renderForecastSourceSummary();
  if (state.currentView === "forecast") scheduleForecastInputCheck(0);
  renderForecastTaskList();
  renderForecastResultPanel();
}

function selectLatestForecastSource() {
  const run = window.HBVStudioForecastView.pickForecastSourceRun(forecastCandidateRuns(), "", { samePath, forecastRunReady });
  if (!run) {
    showToast("当前没有可用于预报的源结果。", true);
    renderForecastView();
    return;
  }
  Object.assign(state, window.HBVStudioForecastView.forecastSourceSelectionState(run.path).statePatch);
  renderForecastView();
}

async function startForecastRestart() {
  const run = selectedForecastRun();
  if (!run) { showToast("请先选择源结果。", true); return; }
  if (!forecastRunReady(run)) { showToast("源结果缺少率定参数或起报状态，不能启动连续状态预报。", true); return; }
  const forecastEnd = $("#forecast-end")?.value.trim() || "";
  const forecastStart = $("#forecast-start")?.value.trim() || "";
  const precDir = $("#forecast-prec-dir")?.value.trim() || "";
  const tempDir = $("#forecast-temp-dir")?.value.trim() || "";
  const evapDir = $("#forecast-evap-dir")?.value.trim() || "";
  const preflight = window.HBVStudioForecastView.forecastRestartPreflight(run, {
    forecast_start: forecastStart,
    forecast_end: forecastEnd,
    forecast_prec_dir: precDir,
    forecast_temp_dir: tempDir,
    forecast_evap_dir: evapDir,
  }, { forecastRunReady, forecastSuggestedStart, forecastTimeComparable });
  if (!preflight.ok) {
    showToast(preflight.message, true);
    return;
  }
  const startButton = $("#forecast-start-button");
  if (startButton) startButton.disabled = true;
  const inputCheck = await refreshForecastInputCheck({ loading: true });
  const checkDecision = window.HBVStudioForecastView.forecastInputCheckDecision(inputCheck);
  if (checkDecision.blocked) {
    showToast(checkDecision.message, true);
    renderForecastSourceSummary();
    return;
  }
  if (checkDecision.message) {
    showToast(checkDecision.message, checkDecision.isError);
  }
  const payload = window.HBVStudioForecastView.forecastRestartPayload(run, {
    forecast_start: forecastStart,
    forecast_end: forecastEnd,
    forecast_prec_dir: precDir,
    forecast_temp_dir: tempDir,
    forecast_evap_dir: evapDir,
    glacier_mode: $("#forecast-glacier-mode")?.value,
  }, {
    fallbackConfigPath: state.wizardWorkspacePath,
    profile: runProfileValue(run) || state.currentWorkspace?.率定模式 || "",
    defaultObjectiveMode: CURRENT_OBJECTIVE_FAMILY,
  });
  try {
    const response = await apiPost("/api/forecast/restart/start", payload);
    showToast(`已启动：${response.task?.label || "连续状态预报"}`);
    await loadTasks();
    renderForecastView();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    renderForecastSourceSummary();
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
    state.dashboardGeoOverview = null;
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
    state.dashboardGeoOverview = null;
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

async function loadWorkspaceGeoOverview(path, { silent = true } = {}) {
  const target = String(path || "").trim();
  if (!target) return null;
  try {
    const p = await apiGet(`/api/geo/overview?config_path=${encodeURIComponent(target)}`);
    return p.data || null;
  } catch (err) {
    if (!silent) showToast(err.message, true);
    return {
      status: "error",
      available_layer_count: 0,
      layers: [],
      message: err.message || "空间预览读取失败",
    };
  }
}

async function refreshCurrentWorkspaceLayout() {
  if (!state.wizardWorkspacePath) {
    state.currentWorkspaceLayout = null;
    state.currentWorkspaceLayoutPath = "";
    state.currentWorkspaceGeoOverview = null;
    refreshWizardWorkspacePreview();
    return null;
  }
  const p = await apiGet(`/api/workspace/layout?config_path=${encodeURIComponent(state.wizardWorkspacePath)}`);
  state.currentWorkspaceLayout = p.data || null;
  state.currentWorkspaceLayoutPath = state.wizardWorkspacePath;
  state.currentWorkspaceGeoOverview = await loadWorkspaceGeoOverview(state.wizardWorkspacePath);
  if (state.currentWorkspaceLayout) {
    state.currentWorkspaceLayout.geo_overview = state.currentWorkspaceGeoOverview;
  }
  refreshWizardWorkspacePreview();
  return state.currentWorkspaceLayout;
}

async function previewWorkspaceLayout(path, { silent = false } = {}) {
  state.dashboardLayoutPath = String(path || "").trim();
  renderWorkspaceCards();
  try {
    const p = await apiGet(`/api/workspace/layout?config_path=${encodeURIComponent(path)}`);
    state.dashboardWorkspaceLayout = p.data || null;
    state.dashboardGeoOverview = await loadWorkspaceGeoOverview(path);
    if (state.dashboardWorkspaceLayout) {
      state.dashboardWorkspaceLayout.geo_overview = state.dashboardGeoOverview;
    }
    renderDashboardWorkspaceLayout();
    return state.dashboardWorkspaceLayout;
  } catch (err) {
    state.dashboardWorkspaceLayout = null;
    state.dashboardGeoOverview = null;
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
  const requestToken = runDetailRequestGuard.next();
  let detailLoaded = false;
  state.selectedRunPath = targetPath || previousSelected;
  renderRunList();
  try {
    const p = await apiGet(`/api/run?path=${encodeURIComponent(path)}`);
    if (!runDetailRequestGuard.isActive(requestToken)) return;
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
      if (runDetailRequestGuard.isActive(requestToken)) {
        showToast(`手调参数集加载失败：${presetErr.message}`, true);
      }
    }
    if (!runDetailRequestGuard.isActive(requestToken)) return;
    try {
      updateSidebar();
    } catch (sidebarErr) {
      showToast(sidebarErr.message, true);
    }
  } catch (err) {
    if (!runDetailRequestGuard.isActive(requestToken)) return;
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
      const completedResult = window.HBVStudioForecastView.forecastCompletedResultState(newlyCompletedForecast);
      if (completedResult.ok) {
        await loadRuns().catch(() => {});
        Object.assign(state, completedResult.statePatch);
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
    const selectionState = window.HBVStudioForecastView.forecastSourceSelectionState($("#forecast-source-run")?.value || "");
    Object.assign(state, selectionState.statePatch);
    renderForecastSourceSummary();
    scheduleForecastInputCheck(0);
  });
  ["#forecast-start", "#forecast-end", "#forecast-prec-dir", "#forecast-temp-dir", "#forecast-evap-dir"].forEach(sel => {
    const el = $(sel);
    if (!el) return;
    el.addEventListener("input", () => scheduleForecastInputCheck());
    el.addEventListener("change", () => scheduleForecastInputCheck(0));
  });
  $("#forecast-use-latest")?.addEventListener("click", selectLatestForecastSource);
  $("#forecast-open-source")?.addEventListener("click", () => {
    const run = selectedForecastRun();
    if (run?.path) openLocalPath(run.path, "源结果目录").catch(err => showToast(err.message, true));
  });
  $("#forecast-result-run")?.addEventListener("change", () => {
    const selectionState = window.HBVStudioForecastView.forecastResultSelectionState($("#forecast-result-run")?.value || "");
    Object.assign(state, selectionState.statePatch);
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
    const selectionState = window.HBVStudioParameterLibrary.manualPresetSelectionChangeState(preset, state.comparePresetId);
    if ($("#manual-preset-name")) $("#manual-preset-name").value = selectionState.inputName;
    if (selectionState.shouldClearComparison) clearManualPresetComparison(selectionState.clearComparisonOptions);
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
  validateFrontendModules();
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
