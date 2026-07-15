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

  function fallbackText(value, fallback = "") {
    const text = String(value || "").trim();
    return text || fallback;
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

  function taskProgressChartData(history = [], stageLabel = "", helpers = {}) {
    const colors = helpers.colors || {
      qSim: "#0e7490",
      qRain: "#1d4ed8",
      residual: "#b91c1c",
    };
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

  function taskListQueryState() {
    return {
      tasksPath: "/api/tasks",
    };
  }

  function taskListDataState(data = []) {
    const tasks = Array.isArray(data) ? data : [];
    return {
      tasks,
      statePatch: { tasks },
    };
  }

  function taskById(tasks = [], taskId = "") {
    if (taskId === null || taskId === undefined) return null;
    const targetId = String(taskId);
    return (Array.isArray(tasks) ? tasks : []).find(task => String(task?.id ?? "") === targetId) || null;
  }

  function hasRunningTasks(tasks = []) {
    return (Array.isArray(tasks) ? tasks : []).some(task => task?.status === "running");
  }

  function previousTaskRecord(previousTasks = null, taskId = "") {
    if (!previousTasks || taskId === null || taskId === undefined) return null;
    if (typeof previousTasks.get === "function") {
      return previousTasks.get(taskId) || previousTasks.get(String(taskId)) || null;
    }
    if (Array.isArray(previousTasks)) {
      return taskById(previousTasks, taskId);
    }
    if (typeof previousTasks === "object") {
      return previousTasks[taskId] || previousTasks[String(taskId)] || null;
    }
    return null;
  }

  function taskWasRunning(previousTasks = null, task = null) {
    return previousTaskRecord(previousTasks, task?.id)?.status === "running";
  }

  function newlyFinishedTaskIds(tasks = [], previousTasks = null) {
    return (Array.isArray(tasks) ? tasks : [])
      .filter(task => taskWasRunning(previousTasks, task) && task?.status !== "running")
      .map(task => task.id);
  }

  function newlyCompletedTask(tasks = [], previousTasks = null, taskType = "") {
    const targetType = String(taskType || "").trim();
    if (!targetType) return null;
    return (Array.isArray(tasks) ? tasks : []).find(task =>
      task?.task_type === targetType &&
      task?.status === "completed" &&
      taskWasRunning(previousTasks, task)
    ) || null;
  }

  function normalizeTaskFilters(filters = {}) {
    return {
      workspaceMode: String(filters.workspaceMode || "current").trim().toLowerCase() || "current",
      workspacePath: String(filters.workspacePath || "").trim(),
      status: String(filters.status || "active").trim().toLowerCase() || "active",
      type: String(filters.type || "all").trim().toLowerCase() || "all",
    };
  }

  function taskMatchesType(task, type) {
    if (type === "all") return true;
    if (type === "calibration") return task?.task_type === "calibration";
    if (type === "prep") return ["data_prep", "bootstrap", "meteo_import"].includes(task?.task_type);
    if (type === "simulate") return ["forward_sim", "manual_start", "forecast_restart"].includes(task?.task_type);
    if (type === "support") return ["self_check", "sync"].includes(task?.task_type);
    return true;
  }

  function filterTasks(tasks, filters = {}, helpers = {}) {
    const items = Array.isArray(tasks) ? tasks : [];
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const normalized = normalizeTaskFilters(filters);
    return items.filter(task => {
      if (normalized.workspaceMode === "current" && normalized.workspacePath) {
        if (!samePath(task?.config_path, normalized.workspacePath)) return false;
      }
      if (normalized.status === "active" && task?.status !== "running") return false;
      if (normalized.status === "unfinished" && task?.status === "completed") return false;
      if (normalized.status === "failed" && task?.status !== "failed") return false;
      return taskMatchesType(task, normalized.type);
    });
  }

  function renderFilterGroup(label, options = [], attrName, selectedValue = "", helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    return `
      <div class="results-filter-group">
        <span class="results-filter-label">${escapeHtml(label)}</span>
        ${options.map(item => `
          <button class="phase-chip ${String(item.value || "") === String(selectedValue || "") ? "active" : ""}" ${attrName}="${escapeHtml(item.value)}" ${item.disabled ? "disabled" : ""}>
            ${escapeHtml(item.label)}
          </button>
        `).join("")}
      </div>
    `;
  }

  function renderTaskFilterToolbar(model = {}, helpers = {}) {
    const workspaceLabelByPath = helpers.workspaceLabelByPath || (() => "未命名工作区");
    const filters = normalizeTaskFilters({
      workspaceMode: model.workspaceMode,
      workspacePath: model.workspacePath,
      status: model.status,
      type: model.type,
    });
    const workspacePath = String(filters.workspacePath || "").trim();
    const workspaceOptions = [
      {
        value: "current",
        label: workspacePath ? `当前工作区：${workspaceLabelByPath(workspacePath)}` : "当前工作区（未选择）",
        disabled: !workspacePath,
      },
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
    const toolbarHtml = [
      renderFilterGroup("范围", workspaceOptions, "data-task-filter-workspace", filters.workspaceMode, helpers),
      renderFilterGroup("状态", statusOptions, "data-task-filter-status", filters.status, helpers),
      renderFilterGroup("类型", typeOptions, "data-task-filter-type", filters.type, helpers),
    ].join("");
    const shown = filterTasks(model.tasks || [], filters, helpers);
    const running = shown.filter(task => task?.status === "running").length;
    const failed = shown.filter(task => task?.status === "failed").length;
    const total = Array.isArray(model.tasks) ? model.tasks.length : 0;
    const scopeText = filters.workspaceMode === "current" && workspacePath
      ? `当前工作区“${workspaceLabelByPath(workspacePath)}”`
      : "全部工作区";
    const hintText = `当前显示 ${shown.length}/${total} 个任务 · 运行中 ${running} · 失败 ${failed} · 范围：${scopeText}`;
    const hintClassName = `hint-box ${failed > 0 && filters.status !== "active" ? "status-warn" : ""}`.trim();
    return {
      toolbarHtml,
      hintText,
      hintClassName,
      shownCount: shown.length,
      total,
      running,
      failed,
      domUpdates: [
        { selector: "#task-filter-toolbar", html: toolbarHtml },
        { selector: "#task-filter-hint", text: hintText, className: hintClassName },
      ],
    };
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

  function taskLabelParts(task) {
    return String(task?.label || "").split("|").map(part => part.trim()).filter(Boolean);
  }

  function taskPrimaryTitle(task) {
    const parts = taskLabelParts(task);
    if (task?.task_type === "data_prep") return task.step_title || parts[1] || parts[0] || task.label || "数据准备";
    return parts[0] || task.label || taskTypeLabel(task?.task_type);
  }

  function taskContextSummary(task, helpers = {}) {
    const workspaceLabelByPath = helpers.workspaceLabelByPath || (() => "");
    const shortPath = helpers.shortPath || fallbackText;
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
    const profileLabel = helpers.profileLabel || fallbackText;
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

  function summarizeTaskLogMessage(line, helpers = {}) {
    const shortPath = helpers.shortPath || fallbackText;
    const tagged = parseTaskTagLine(line);
    let message = tagged ? tagged.message : String(line || "").trim();
    if (tagged && ["缓存写入", "缓存命中", "扫描", "导入", "校验"].includes(tagged.tag)) {
      message = `${tagged.tag}：${message}`;
    }
    message = message.replace(/(->\s*)([A-Za-z]:[\\/][^\s]+)$/i, (_, prefix, rawPath) => `${prefix}${shortPath(rawPath)}`);
    return message;
  }

  function taskLastMeaningfulLog(task, helpers = {}) {
    const lines = (task?.output || []).map(line => String(line || "").trim()).filter(Boolean);
    return lines.length ? summarizeTaskLogMessage(lines[lines.length - 1], helpers) : "";
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
    else if (/保存状态|状态快照|源状态/.test(stageText)) phase = 1;
    return ["读取源结果", "读取起报状态", "读取参数", "加载模型", "检查起报", "检查气象", "归档气象", "加载数据", "整理起报", "执行预报", "写出结果", "生成元数据", "完成"].map((label, idx) => {
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

  function renderTaskMilestones(task, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const entries = taskMilestoneEntries(task);
    if (!entries.length) return "";
    return `
      <div class="task-chip-row">
        ${entries.map(item => `<span class="task-chip is-${escapeHtml(item.status || "pending")}">${escapeHtml(item.label || "")}</span>`).join("")}
      </div>
    `;
  }

  function calibrationTaskSummary(task, helpers = {}) {
    const formatNumber = helpers.formatNumber || fallbackText;
    const formatDurationSeconds = helpers.formatDurationSeconds || fallbackText;
    const optimizationResultLabel = helpers.optimizationResultLabel || (() => "");
    const optimizationRefineSummary = helpers.optimizationRefineSummary || (() => "未记录");
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
      return taskLastMeaningfulLog(task, helpers) || "率定任务失败。";
    }
    if (progress) {
      const stepText = progress.maxiter ? `第 ${progress.gen}/${progress.maxiter} 步` : `第 ${progress.gen || "—"} 步`;
      const timeText = `已耗时 ${formatDurationSeconds(progress.elapsed_sec)}${progress.eta_sec !== null && progress.eta_sec !== undefined ? `，预计剩余 ${formatDurationSeconds(progress.eta_sec)}` : ""}`;
      return `${taskStageLabel(progress.stage || "global")} · ${stepText} · 率定纳什效率系数 ${formatNumber(progress.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(progress.nse_val, 4)}，综合评分值 ${formatNumber(progress.obj, 4)} · ${timeText}`;
    }
    return taskLastMeaningfulLog(task, helpers) || task?.ui_progress?.label || task?.ui_progress?.stage || "率定任务已启动，正在加载模型与驱动，首个进度点尚未写出。";
  }

  function workflowTaskSummary(task, helpers = {}) {
    const snapshot = workflowTaskSnapshot(task);
    if (task?.status === "failed") {
      return taskLastMeaningfulLog(task, helpers) || snapshot.failedMessage || "任务执行失败。";
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
    return taskLastMeaningfulLog(task, helpers) || "任务已创建，正在等待脚本输出。";
  }

  function meteoImportTaskSummary(task, helpers = {}) {
    const progress = task?.ui_progress || {};
    if (task?.status === "running") {
      const lastLog = taskLastMeaningfulLog(task, helpers);
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
      const periods = result.periods || {};
      const periodParts = [
        ["降水", periods.prec],
        ["气温", periods.temp],
        ["蒸散发", periods.evap],
      ].filter(([, value]) => String(value || "").trim()).map(([label, value]) => `${label}：${value}`);
      const coverage = periodParts.length
        ? periodParts.join("；")
        : "旧版导入结果未记录气象起止时间，请在输入检查中重新核验";
      return `${coverage}；${result.aligned ? "网格已一致。" : "已自动裁剪对齐到 DEM 网格。"}${tail}`;
    }
    return taskLastMeaningfulLog(task, helpers) || "气象导入失败。";
  }

  function forwardSimTaskSummary(task, helpers = {}) {
    const formatNumber = helpers.formatNumber || fallbackText;
    if (task?.status === "running") {
      const stage = task?.ui_progress?.stage || "正在保存并重算当前结果。";
      const lastLog = taskLastMeaningfulLog(task, helpers);
      return lastLog && lastLog !== stage ? `${stage} · ${lastLog}` : stage;
    }
    if (task?.status === "completed" && task?.result) {
      const metrics = task.result.metrics || {};
      return task.result.run_path
        ? `手调结果已保存：率定纳什效率系数 ${formatNumber(metrics.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(metrics.nse_val, 4)}。`
        : `结果重算完成：率定纳什效率系数 ${formatNumber(metrics.nse_cal, 4)}，验证纳什效率系数 ${formatNumber(metrics.nse_val, 4)}。`;
    }
    return taskLastMeaningfulLog(task, helpers) || "保存并重算失败。";
  }

  function manualStartTaskSummary(task, helpers = {}) {
    const formatNumber = helpers.formatNumber || fallbackText;
    if (task?.status === "running") {
      const stage = task?.ui_progress?.stage || "正在生成手调起点。";
      const lastLog = taskLastMeaningfulLog(task, helpers);
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
    return taskLastMeaningfulLog(task, helpers) || "手调起点生成失败。";
  }

  function forecastRestartTaskSummary(task, helpers = {}) {
    if (task?.status === "running") {
      const stage = task?.ui_progress?.stage || "正在执行连续状态预报。";
      const lastLog = taskLastMeaningfulLog(task, helpers);
      return lastLog && lastLog !== stage ? `${stage} · ${lastLog}` : stage;
    }
    if (task?.status === "completed" && task?.result) {
      const result = task.result || {};
      const meta = result.metadata?.forecast_result || {};
      const range = meta.forecast_start && meta.forecast_end ? `${meta.forecast_start} 至 ${meta.forecast_end}` : "未来时段";
      return result.run_path ? `连续状态预报已生成：${range}。` : "连续状态预报已完成。";
    }
    return taskLastMeaningfulLog(task, helpers) || "连续状态预报失败。";
  }

  function selfCheckTaskSummary(task, helpers = {}) {
    if (task?.status === "running") {
      return task?.ui_progress?.stage || "正在检查本地环境、脚本与关键依赖。";
    }
    if (task?.status === "completed") return "系统自检完成。";
    return taskLastMeaningfulLog(task, helpers) || "系统自检失败。";
  }

  function taskSummaryLine(task, helpers = {}) {
    if (task?.task_type === "calibration") return calibrationTaskSummary(task, helpers);
    if (task?.task_type === "bootstrap" || task?.task_type === "data_prep") return workflowTaskSummary(task, helpers);
    if (task?.task_type === "meteo_import") return meteoImportTaskSummary(task, helpers);
    if (task?.task_type === "manual_start") return manualStartTaskSummary(task, helpers);
    if (task?.task_type === "forward_sim") return forwardSimTaskSummary(task, helpers);
    if (task?.task_type === "forecast_restart") return forecastRestartTaskSummary(task, helpers);
    if (task?.task_type === "self_check") return selfCheckTaskSummary(task, helpers);
    if (task?.status === "completed") return "任务已完成。";
    if (task?.status === "failed") return taskLastMeaningfulLog(task, helpers) || "任务失败。";
    return taskLastMeaningfulLog(task, helpers) || "任务已创建，等待输出。";
  }

  function renderTaskActions(task, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const samePath = helpers.samePath || ((a, b) => String(a || "") === String(b || ""));
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

  function taskDebugDetails(task, options = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const taskDebugOpen = helpers.taskDebugOpen || {};
    const lines = Number(options.lines || 80);
    const output = (task?.output || []);
    if (!output.length) return "";
    const shownLines = output.slice(-lines);
    const rememberedOpen = Boolean(taskDebugOpen?.[task.id]);
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

  function taskProgressStageEntries(task) {
    const progress = task?.progress;
    const stageEntries = Object.entries(progress?.stages || {})
      .filter(([, stageInfo]) => (stageInfo?.history || []).length >= 2)
      .sort((a, b) => {
        const order = { mc: 0, global: 1, refine: 2 };
        return (order[a[0]] ?? 99) - (order[b[0]] ?? 99);
      });
    if (stageEntries.length) {
      return stageEntries.map(([stageName]) => stageName);
    }
    return (progress?.history || []).length >= 2 ? [progress?.stage || "global"] : [];
  }

  function renderTaskProgressNote(task, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const formatNumber = helpers.formatNumber || fallbackText;
    const formatDurationSeconds = helpers.formatDurationSeconds || fallbackText;
    const progress = task?.progress;
    if (!progress) return "";
    const isRunning = task?.status === "running";
    const progressTitle = isRunning ? "当前阶段" : task?.status === "completed" ? "最后进度" : "失败前进度";
    const trendHtml = taskProgressStageEntries(task).map(stageName =>
      `<div class="chart-host" data-task-progress-chart="${escapeHtml(task?.id)}" data-task-progress-stage="${escapeHtml(stageName)}" style="height:180px;margin-top:8px"></div>`
    ).join("");
    return `
      <div class="hint-box task-progress-note ${task?.status === "completed" ? "status-ok" : task?.status === "failed" ? "status-fail" : ""}">
        ${escapeHtml(progressTitle)}：${escapeHtml(taskStageLabel(progress.stage || "global"))}
        ${progress.gen ? ` · 第 ${escapeHtml(progress.gen)}/${escapeHtml(progress.maxiter || "\u2014")} 步` : ""}
        · 率定纳什效率系数 ${escapeHtml(formatNumber(progress.nse_cal, 4))}
        · 验证纳什效率系数 ${escapeHtml(formatNumber(progress.nse_val, 4))}
        · 综合评分值 ${escapeHtml(formatNumber(progress.obj, 4))}
        · 已耗时 ${escapeHtml(formatDurationSeconds(progress.elapsed_sec))}
        ${isRunning && progress.eta_sec !== null && progress.eta_sec !== undefined ? ` · 预计剩余 ${escapeHtml(formatDurationSeconds(progress.eta_sec))}` : ""}
        ${trendHtml}
      </div>`;
  }

  function renderTaskCard(task, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const formatDateTime = helpers.formatDateTime || fallbackText;
    const isRunning = task?.status === "running";
    const contextSummary = taskContextSummary(task, helpers);
    const summaryLine = taskSummaryLine(task, helpers);
    const summaryClass = task?.status === "completed" ? "status-ok" : task?.status === "failed" ? "status-fail" : "";
    return `
    <div class="list-item task-card ${isRunning ? "task-running" : ""}">
      <div class="task-card-topline">
        <span class="task-kicker">${escapeHtml(taskTypeLabel(task?.task_type))}</span>
        <span class="task-updated">最近更新 ${escapeHtml(formatDateTime(task?.updated_at))}</span>
        <span class="status-badge ${taskStatusClass(task?.status)}">${escapeHtml(taskStatusLabel(task?.status))}${isRunning ? "..." : ""}</span>
      </div>
      <div class="task-card-hero">
        <div class="task-card-title">
          <strong>${escapeHtml(taskPrimaryTitle(task))}</strong>
          ${contextSummary ? `<small class="task-meta-line">${escapeHtml(contextSummary)}</small>` : ""}
        </div>
      </div>
      ${renderTaskMilestones(task, helpers)}
      <div class="hint-box task-summary-box ${summaryClass}">${escapeHtml(summaryLine)}</div>
      ${renderTaskProgressNote(task, helpers)}
      ${renderTaskActions(task, helpers)}
      ${taskDebugDetails(task, { lines: isRunning ? 120 : 80 }, helpers)}
    </div>`;
  }

  function renderTaskList(tasks, helpers = {}) {
    const items = Array.isArray(tasks) ? tasks : [];
    if (!items.length) return '<div class="hint-box">当前筛选下暂无任务。</div>';
    return items.map(task => renderTaskCard(task, helpers)).join("");
  }

  function taskListState(tasks, helpers = {}) {
    const html = renderTaskList(tasks, helpers);
    return {
      html,
      domUpdates: [{ selector: "#task-list", html }],
    };
  }

  window.HBVStudioTaskView = {
    cleanTaskLogMessage,
    filterTasks,
    hasRunningTasks,
    methodLabel,
    newlyCompletedTask,
    newlyFinishedTaskIds,
    optimizationMethodLabel,
    renderTaskCard,
    renderTaskActions,
    renderTaskFilterToolbar,
    renderTaskList,
    renderTaskMilestones,
    taskListState,
    taskContextSummary,
    taskDebugDetails,
    taskLastMeaningfulLog,
    taskById,
    taskListDataState,
    taskListQueryState,
    taskPrimaryTitle,
    taskProgressChartData,
    taskStageLabel,
    taskStatusClass,
    taskStatusLabel,
    taskSummaryLine,
    taskTypeLabel,
  };
})();
