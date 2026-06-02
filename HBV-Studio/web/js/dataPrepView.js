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

  function formatPrepDisplayTitle(index, title) {
    const clean = String(title || "").replace(/^\d+\.\s*/, "").trim();
    return `${index}. ${clean}`;
  }

  function dependencyLabel(depId, visibleSteps, allSteps, helpers = {}) {
    const isGisStepId = helpers.isGisStepId || (() => false);
    if (isGisStepId(depId)) return "第 5 步地理数据";
    const step = (visibleSteps || []).find(item => item.id === depId)
      || (allSteps || []).find(item => item.id === depId);
    return String(step?.displayTitle || step?.title || depId).replace(/^\d+\.\s*/, "").trim();
  }

  function formatPrepBlockedMessage(status, visibleSteps, allSteps = [], helpers = {}) {
    const blockedBy = Array.isArray(status?.blocked_by) ? status.blocked_by : [];
    if (!blockedBy.length) return String(status?.message || "尚未检测。");
    const labels = blockedBy.map(depId => dependencyLabel(depId, visibleSteps, allSteps, helpers));
    return `依赖未满足：请先完成 ${labels.join("、")}。`;
  }

  function renderPrepStep(step, prepStatus, visibleSteps, allSteps, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const status = prepStatus?.[step.id] || {};
    const running = Boolean(status.running);
    const blocked = (status.blocked_by || []).length > 0;
    const text = running ? "执行中" : status.done ? "已完成" : blocked ? "依赖未满足" : status.manual ? "需补充资料" : "待执行";
    const statusClass = status.done ? "status-ok" : blocked ? "status-fail" : "status-warn";
    const canOverwrite = Boolean(step.supports_overwrite && status.done && !blocked && !step.manual && !running);
    const message = running
      ? String(status.message || "正在执行，请看下方日志。")
      : blocked
        ? formatPrepBlockedMessage(status, visibleSteps, allSteps, helpers)
        : String(status.message || "尚未检测。");
    const runButton = !step.manual
      ? `<button class="ghost-button" data-run-step="${escapeHtml(step.id)}" ${(blocked || running) ? "disabled" : ""}>${running ? "执行中..." : status.done ? "重新运行" : "运行此步"}</button>`
      : "";
    const overwriteButton = canOverwrite
      ? `<button class="ghost-button" data-run-step-overwrite="${escapeHtml(step.id)}">覆盖重跑</button>`
      : "";
    return `
      <div class="prep-step">
        <div class="prep-step-head">
          <div>
            <strong>${escapeHtml(step.displayTitle || step.title)}</strong>
            <div class="panel-note">${escapeHtml(step.displayDescription || step.description || "")}</div>
          </div>
          <span class="status-badge ${statusClass}">${escapeHtml(text)}</span>
        </div>
        <div class="hint-box">${escapeHtml(message)}</div>
        <div class="prep-step-actions">
          ${runButton}
          ${overwriteButton}
        </div>
      </div>`;
  }

  function renderPrepStepList(model = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    if (!model.workspaceSelected) {
      return `<div class="hint-box">${escapeHtml(model.emptyText || "先选择或创建工作区。")}</div>`;
    }
    const steps = Array.isArray(model.steps) ? model.steps : [];
    if (!steps.length) {
      return `<div class="hint-box">${escapeHtml(model.noStepsText || "当前工作区无需额外气象准备步骤。")}</div>`;
    }
    const allSteps = Array.isArray(model.allSteps) ? model.allSteps : [];
    const prepStatus = model.prepStatus || {};
    return steps.map(step => renderPrepStep(step, prepStatus, steps, allSteps, helpers)).join("");
  }

  function idSet(values = []) {
    if (values instanceof Set) return values;
    return new Set(Array.isArray(values) ? values : []);
  }

  function visiblePrepSteps(model = {}) {
    const allSteps = Array.isArray(model.steps) ? model.steps : [];
    const excluded = new Set([
      ...idSet(model.gisStepIds),
      ...idSet(model.checkStepIds),
      ...idSet(model.excludedStepIds),
    ]);
    const rawSteps = allSteps.filter(step => !excluded.has(step.id));
    const byId = Object.fromEntries(rawSteps.map(step => [step.id, step]));
    const sources = model.sources || {};
    const precipMode = String(model.precipMode || "grid_only");
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

    if (model.hourly) {
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
        add("download_hourly_era5", hourlyDownloadTitle, hourlyDownloadDesc);
        add("process_hourly_era5", hourlyProcessTitle, hourlyProcessDesc);
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
        add("download_era5", dailyDownloadTitle, dailyDownloadDesc);
        if (needsEra5Temp || needsEra5Pet) {
          add("process_era5", dailyProcessTitle, dailyProcessDesc);
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

  function renderBootstrapStatus(items = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    if (!Array.isArray(items) || !items.length) {
      return '<div class="hint-box">暂无 GIS 步骤状态信息。</div>';
    }
    return items.map(item => {
      const isDisabledOptional = item.optional && String(item.message || "").includes("未启用");
      const badge = isDisabledOptional ? "未启用" : item.done ? "已完成" : "待执行";
      const badgeClass = isDisabledOptional ? "" : item.done ? "status-ok" : "status-warn";
      return `
      <div class="bootstrap-item ${item.done ? "done" : ""}">
        <span class="status-badge ${badgeClass}">${escapeHtml(badge)}</span>
        <span>${escapeHtml(item.title || item.id)}</span>
        <small style="margin-left:auto;color:var(--muted)">${escapeHtml(item.message || "")}</small>
      </div>`;
    }).join("");
  }

  function gisImportStartingUiState() {
    return {
      hint: {
        text: "正在导入...",
      },
    };
  }

  function gisImportSuccessUiState(result = {}) {
    return {
      hint: {
        text: result?.message || "导入完成！",
        className: "hint-box status-ok",
      },
    };
  }

  function gisImportErrorUiState(error = {}) {
    return {
      hint: {
        text: String(error?.message || error || "GIS 文件导入失败"),
        className: "hint-box status-fail",
      },
    };
  }

  function describeEra5Need(sources = {}) {
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

  function meteoSourceLabels(sources = {}, mode = "local") {
    const labels = [];
    const wantLocal = mode === "local";
    if ((sources.prec === "custom_tif") === wantLocal) labels.push("降水");
    if ((sources.temp === "custom_tif") === wantLocal) labels.push("气温");
    if ((sources.pet === "custom_tif") === wantLocal) labels.push("蒸散发");
    return labels;
  }

  function meteoModeHintState(model = {}) {
    const sources = model.sources || {};
    const copiedLabels = Array.isArray(model.copiedLabels) ? model.copiedLabels : [];
    const localLabels = meteoSourceLabels(sources, "local");
    if (!localLabels.length) {
      return {
        shouldApply: !model.currentText || !String(model.currentClassName || "").includes("status-fail"),
        hint: {
          text: "",
          className: "hint-box",
        },
      };
    }
    const copiedText = copiedLabels.length
      ? `已自动带入第 4 步登记的本地栅格目录（${copiedLabels.join("、")}）。`
      : "";
    if (localLabels.length === 3) {
      return {
        shouldApply: true,
        hint: {
          text: `${copiedText}当前三类气象都来自本地栅格，第 6 步默认使用“直接导入本地栅格”。`,
          className: "hint-box status-ok",
        },
      };
    }
    const pipelineLabels = meteoSourceLabels(sources, "pipeline");
    const pipelineText = pipelineLabels.length
      ? `仍需按步骤处理 ${pipelineLabels.join("、")}。`
      : "请按当前配置继续。";
    return {
      shouldApply: true,
      hint: {
        text: `${copiedText}当前为混合来源方案，本地目录会在对齐步骤自动读取；${pipelineText}`,
        className: "hint-box status-ok",
      },
    };
  }

  function meteoModePanelState(model = {}) {
    const sources = model.sources || {};
    const forceImport = meteoSourceLabels(sources, "local").length === 3;
    const mode = forceImport ? "import" : String(model.mode || "");
    return {
      mode,
      forceImport,
      pipelineRadio: {
        disabled: forceImport,
      },
      importRadio: {
        checked: forceImport,
      },
      pipelineCard: {
        disabled: forceImport,
        title: forceImport ? "当降水、气温、蒸散发三项都来自本地栅格时，请在本步直接导入本地目录。" : "",
        opacity: forceImport ? "0.55" : "",
        pointerEvents: forceImport ? "none" : "",
      },
      panels: {
        pipelineVisible: mode === "pipeline",
        importVisible: mode === "import",
      },
    };
  }

  function prepPanelSummary(sources = {}) {
    const precText = sources.prec === "custom_tif"
      ? "本地栅格"
      : sources.prec === "era5"
        ? "ERA5 自动下载"
        : sources.prec === "cmfd"
          ? "CMFD 本地原始文件"
          : "MSWEP 本地原始文件";
    return {
      text: `当前流程：降水用${precText}，`
        + `气温用${sources.temp === "custom_tif" ? "本地栅格" : "ERA5"}，`
        + `潜在蒸散发用${sources.pet === "custom_tif" ? "本地栅格" : "ERA5+FAO56"}。`
        + describeEra5Need(sources),
      className: "hint-box status-ok",
    };
  }

  function era5ApiPanelState(model = {}) {
    const mode = String(model.mode || "");
    const needsDownload = Boolean(model.needsDownload);
    if (mode !== "pipeline" || !needsDownload) {
      return {
        hint: { visible: false, text: "", className: "hint-box" },
        actions: { visible: false },
      };
    }
    const sources = model.sources || {};
    const status = model.status || null;
    const petOnly = sources.pet !== "custom_tif" && sources.temp === "custom_tif";
    const precipOnly = sources.prec === "era5" && sources.temp === "custom_tif" && sources.pet === "custom_tif";
    if (!status || status.loading) {
      return {
        hint: {
          visible: true,
          text: "正在检查当前电脑的 ERA5 / CDS API 配置...",
          className: "hint-box status-warn",
        },
        actions: { visible: true },
      };
    }
    if (status.error) {
      return {
        hint: {
          visible: true,
          text: `ERA5 API 配置检查失败：${status.error}`,
          className: "hint-box status-fail",
        },
        actions: { visible: true },
      };
    }
    const basis = precipOnly
      ? "这一步会下载 ERA5 降水。"
      : petOnly
        ? "这一步会下载计算潜在蒸散发要用的 ERA5 变量。"
        : "这一步会下载当前方案要用的 ERA5 变量。";
    if (status.exists && status.looks_valid !== false) {
      return {
        hint: {
          visible: true,
          text: `${basis} 已检测到 CDS API 配置，可以直接下载。`,
          className: "hint-box status-ok",
        },
        actions: { visible: true },
      };
    }
    if (status.exists) {
      return {
        hint: {
          visible: true,
          text: `${basis} 已找到 .cdsapirc，但内容看起来不完整，建议检查里面是否包含 url 和 key。`,
          className: "hint-box status-warn",
        },
        actions: { visible: true },
      };
    }
    return {
      hint: {
        visible: true,
        text: `${basis} 这台电脑还没检测到 .cdsapirc，请先配置 CDS API。`,
        className: "hint-box status-warn",
      },
      actions: { visible: true },
    };
  }

  function meteoImportUiState(task = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const shortPath = helpers.shortPath || (value => String(value || ""));
    const progress = task?.ui_progress || {};
    const logs = Array.isArray(task?.output) ? task.output : [];
    const baseState = {
      log: {
        visible: logs.length > 0,
        lines: logs.slice(-80),
        key: "wizard:import-log",
      },
      button: {
        disabled: false,
        text: "验证并导入",
      },
      hint: {
        html: "",
        text: "",
        className: "hint-box",
      },
    };

    if (task?.status === "running") {
      const total = Number(progress.total || 0);
      const current = Number(progress.current || 0);
      const label = progress.label || "导入";
      const itemCurrent = Number(progress.item_current || 0);
      const itemTotal = Number(progress.item_total || 0);
      const ts = progress.timestamp ? ` · 当前时间 ${progress.timestamp}` : "";
      return {
        ...baseState,
        button: { disabled: true, text: "正在导入..." },
        hint: {
          html: "",
          text: total > 0
            ? `${progress.stage || "正在导入"}：总进度 ${current}/${total}；${label} ${itemCurrent}/${itemTotal}${ts}`
            : (progress.stage || "正在准备导入，请稍候..."),
          className: "hint-box status-warn",
        },
      };
    }

    const result = task?.result || {};
    if (task?.status === "completed") {
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
      return {
        ...baseState,
        hint: {
          html: `${escapeHtml(modeLabel)}完成：降水 ${escapeHtml(String(result.prec_count || 0))} 文件、气温 ${escapeHtml(String(result.temp_count || 0))} 文件、蒸散 ${escapeHtml(String(result.evap_count || 0))} 文件；按时间顺序导入。${escapeHtml(result.aligned ? "网格已一致。" : "已自动裁剪对齐到 DEM 网格。")}${result.validation_ok ? "" : ` 当前仍有问题：${escapeHtml(issues.slice(0, 2).join("；") || "请到第 7 步继续检查。")}`}${pathLines.length ? `<div style="margin-top:8px">${pathLines.join("<br>")}</div>` : ""}`,
          text: "",
          className: `hint-box ${result.validation_ok ? "status-ok" : "status-warn"}`,
        },
      };
    }

    const lastLine = logs.length ? logs[logs.length - 1] : "导入失败，请检查目录与文件名格式。";
    return {
      ...baseState,
      hint: {
        html: "",
        text: lastLine,
        className: "hint-box status-fail",
      },
    };
  }

  function meteoImportCreatingUiState() {
    return {
      log: {
        visible: true,
        lines: [],
        key: "wizard:import-log",
      },
      hint: {
        html: "",
        text: "正在创建导入任务...",
        className: "hint-box status-warn",
      },
    };
  }

  function meteoImportErrorUiState(error = {}, { hideLog = false } = {}) {
    const message = String(error?.message || error || "气象驱动导入失败");
    return {
      log: hideLog
        ? {
          visible: false,
          lines: [],
          key: "wizard:import-log",
        }
        : null,
      button: {
        disabled: false,
        text: "验证并导入",
      },
      hint: {
        html: "",
        text: message,
        className: "hint-box status-fail",
      },
    };
  }

  function prepTaskUiState(task = {}) {
    const progress = task?.ui_progress || {};
    const logs = Array.isArray(task?.output) ? task.output : [];
    const label = progress.label || task?.step_title || task?.label || "数据处理";
    const stage = progress.stage || (
      task?.status === "running" ? "正在执行" : task?.status === "completed" ? "已完成" : "执行失败"
    );
    const current = Number(progress.current || 0);
    const total = Number(progress.total || 0);
    return {
      hint: {
        visible: Boolean(task),
        text: total > 0 ? `${stage}：${label}（${current}/${total}）` : `${stage}：${label}`,
        className: `hint-box ${task?.status === "completed" ? "status-ok" : task?.status === "failed" ? "status-fail" : "status-warn"}`,
      },
      log: {
        visible: logs.length > 0,
        lines: logs.slice(-120),
        key: "wizard:pipeline-log",
      },
    };
  }

  function prepTaskErrorUiState(error = {}) {
    const message = String(error?.message || error || "按步骤处理执行失败");
    return {
      hint: {
        visible: true,
        text: message,
        className: "hint-box status-fail",
      },
      log: null,
    };
  }

  function prepStepRunningStatus(existing = {}) {
    return {
      ...(existing || {}),
      running: true,
      message: "正在执行，请看下方日志。",
    };
  }

  function inputCheckCompletionState(model = {}) {
    const validation = model.validation || {};
    const previousWorkflow = model.previousWorkflow || {};
    const detail = Boolean(model.detail);
    const advice = model.advice || null;
    const stage = String(model.stage || "calibration");
    const missing = Array.isArray(validation.missing) ? validation.missing : [];
    const warnings = Array.isArray(validation.warnings) ? validation.warnings : [];
    const comp = {
      ready: Boolean(validation.valid),
      ready_for_calibration: Boolean(validation.valid),
      missing,
      warnings,
    };
    const statePatch = {};
    if (stage === "calibration") {
      const totalSteps = Number(previousWorkflow.total_steps || 0);
      const fallbackCompleted = totalSteps
        ? Math.max(0, Math.min(Number(previousWorkflow.completed_count || 0), totalSteps - 1))
        : Number(previousWorkflow.completed_count || 0);
      const pendingSteps = comp.ready_for_calibration
        ? []
        : Array.from(new Set([...(Array.isArray(previousWorkflow.steps_remaining) ? previousWorkflow.steps_remaining : []), 7]))
            .sort((left, right) => Number(left) - Number(right));
      statePatch.currentWorkspaceWorkflow = {
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
      if (detail && advice) statePatch.currentWorkspaceAdvice = advice;
    }
    return {
      comp,
      statePatch,
      shouldUpdateCalibrationUi: stage === "calibration",
    };
  }

  function emptyInputCheckCache() {
    return {
      configPath: "",
      precipSource: "",
      stage: "calibration",
      checkedAt: 0,
      result: null,
      html: "",
    };
  }

  function inputCheckCacheEntry(model = {}) {
    return {
      configPath: String(model.configPath || ""),
      precipSource: String(model.precipSource || ""),
      stage: String(model.stage || "calibration"),
      checkedAt: Number(model.checkedAt || 0),
      result: model.result || null,
      html: String(model.html || ""),
    };
  }

  function hasRecentInputCheckCache(cache = {}, model = {}, helpers = {}) {
    const samePath = helpers.samePath || ((left, right) => String(left || "") === String(right || ""));
    const maxAgeMs = Number(model.maxAgeMs || 45000);
    const nowMs = Number(model.nowMs || Date.now());
    if (!model.workspacePath || !cache.configPath) return false;
    if (!samePath(cache.configPath, model.workspacePath)) return false;
    if (String(cache.precipSource || "").trim().toLowerCase() !== String(model.precipSource || "").trim().toLowerCase()) return false;
    if (String(cache.stage || "calibration").trim().toLowerCase() !== String(model.stage || "calibration").trim().toLowerCase()) return false;
    if (!cache.result) return false;
    if ((nowMs - Number(cache.checkedAt || 0)) > maxAgeMs) return false;
    if (model.hasRunningImport) return false;
    return model.requireReady ? Boolean(cache.result.ready) : true;
  }

  function inputCheckReadyHeadline(stage = "calibration") {
    if (stage === "calibration") return "所有率定所需数据已就位，可以进入率定！";
    if (stage === "quick_test") return "输入预核算所需数据已就位，可以进行限定时段前向计算。";
    return "所有手调/重算所需运行时数据已就位，可以继续前向重算。";
  }

  function renderInputCheckImportBlock(task = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const progress = task?.ui_progress || {};
    const stage = progress.stage || "气象驱动导入";
    const current = Number(progress.current || 0);
    const total = Number(progress.total || 0);
    const label = progress.label || "";
    const itemCurrent = Number(progress.item_current || 0);
    const itemTotal = Number(progress.item_total || 0);
    const ts = progress.timestamp ? ` 当前时间：${escapeHtml(progress.timestamp)}。` : "";
    const logs = (Array.isArray(task?.output) ? task.output : []).slice(-20).join("\n");
    return `
      <div class="hint-box status-warn" style="margin-bottom:12px">
        <strong>当前正在导入气象驱动，暂不执行输入检查。</strong><br>
        ${escapeHtml(stage)}${total > 0 ? `：总进度 ${current}/${total}` : ""}${label ? `；${escapeHtml(label)} ${itemCurrent}/${itemTotal}` : ""}。${ts}
        导入完成后会自动重新检查。
      </div>
      ${logs ? `<div class="task-output-box">${escapeHtml(logs)}</div>` : ""}
    `;
  }

  function renderInputCheckProgress(model = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const stage = String(model.stage || "基础配置检查");
    const elapsed = Math.max(0, Math.floor(Number(model.elapsed || 0)));
    const longDetail = stage === "详细输入检查" && elapsed >= 30;
    return `
      <div class="hint-box input-check-progress ${longDetail ? "status-warn" : ""}">
        <div class="input-check-stage"><strong>${escapeHtml(stage)}</strong><span>已用时 ${elapsed} 秒</span></div>
        <div>${longDetail ? "正在执行详细输入检查，系统正在读取气象栅格、流域边界和可选冰川数据。数据量较大时可能需要数分钟，请勿关闭页面。" : "正在检查当前工作区输入，请稍候。"}</div>
      </div>
    `;
  }

  function renderInputCheckError(model = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const message = String(model.message || "");
    const stage = String(model.stage || "输入检查");
    const elapsed = Math.max(0, Math.floor(Number(model.elapsed || 0)));
    return `<div class="hint-box status-fail">检查失败：${escapeHtml(message)}<br>失败阶段：${escapeHtml(stage)}；已用时 ${elapsed} 秒。</div>`;
  }

  function renderInputCheckItems(items = [], helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const renderIssueJumpButton = helpers.renderIssueJumpButton || (() => "");
    return (Array.isArray(items) ? items : []).map(item => (
      `<li>${escapeHtml(item)}${renderIssueJumpButton(item, 7)}</li>`
    )).join("");
  }

  function renderInputCheckRecommendations(advice = {}, ready = false, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const inferIssueTarget = helpers.inferIssueTarget || (() => null);
    const recommendations = Array.isArray(advice?.recommendations) ? advice.recommendations : [];
    if (!recommendations.length) return "";
    const items = recommendations.slice(0, 4).map(item => {
      const target = inferIssueTarget(item.detail, item.target_step || 7);
      const stepBtn = target
        ? ` <button class="ghost-button" data-go-step="${escapeHtml(target.step)}" data-go-selector="${escapeHtml(target.selector || "")}" style="padding:4px 10px;font-size:12px">定位</button>`
        : "";
      return `<li><strong>${escapeHtml(item.title)}</strong>：${escapeHtml(item.detail)}${stepBtn}</li>`;
    }).join("");
    return `<div class="hint-box ${ready ? "status-ok" : "status-warn"}" style="margin-bottom:12px"><strong>智能建议：</strong><ul>${items}</ul></div>`;
  }

  function renderInputCheckDetailTable(detailData = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const groups = {};
    for (const item of (Array.isArray(detailData?.summary) ? detailData.summary : [])) {
      const groupName = item.group || "其他";
      if (!groups[groupName]) groups[groupName] = [];
      groups[groupName].push(item);
    }
    let html = '<div class="check-detail-table">';
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
    html += "</div>";
    return html;
  }

  function renderInputCheckResults(model = {}, helpers = {}) {
    const renderValidationEventSections = helpers.renderValidationEventSections || (() => "");
    const renderEngineeringFocusChecks = helpers.renderEngineeringFocusChecks || (() => "");
    const validation = model.validation || {};
    const comp = model.comp || {
      ready: Boolean(validation.valid),
      missing: validation.missing || [],
      warnings: validation.warnings || [],
    };
    const stage = String(model.stage || "calibration");
    const detail = Boolean(model.detail);
    const detailData = model.detailData || null;
    const advice = model.advice || null;

    let html = "";
    html += renderValidationEventSections(validation);

    if (comp.ready) {
      html += `<div class="hint-box status-ok" style="margin-bottom:12px"><strong>${inputCheckReadyHeadline(stage)}</strong></div>`;
    } else {
      const missingItems = renderInputCheckItems(comp.missing || [], helpers);
      html += `<div class="hint-box status-fail" style="margin-bottom:12px"><strong>以下数据缺失或配置不完整：</strong><ul>${missingItems || "<li>请完成前序步骤</li>"}</ul></div>`;
    }

    if (Array.isArray(comp.warnings) && comp.warnings.length > 0) {
      const warnItems = renderInputCheckItems(comp.warnings, helpers);
      html += `<div class="hint-box status-warn" style="margin-bottom:12px"><strong>注意事项：</strong><ul>${warnItems}</ul></div>`;
    }

    if (Array.isArray(validation.focus_checks) && validation.focus_checks.length) {
      html += `<div style="margin-bottom:12px"><strong style="display:block;margin-bottom:8px">专项工程检查</strong>${renderEngineeringFocusChecks(validation.focus_checks, { title: "专项工程检查" })}</div>`;
    }

    if (detail && stage === "calibration" && Array.isArray(detailData?.reasonableness_checks) && detailData.reasonableness_checks.length) {
      html += `<div style="margin-bottom:12px"><strong style="display:block;margin-bottom:8px">数值合理性检查</strong>${renderEngineeringFocusChecks(detailData.reasonableness_checks, { title: "数值合理性检查", emptyText: "暂无数值合理性检查。" })}</div>`;
    }

    if (detail && stage === "calibration") {
      html += renderInputCheckRecommendations(advice, comp.ready, helpers);
    }

    if (detail && detailData) {
      html += renderInputCheckDetailTable(detailData, helpers);
    } else {
      html += '<div class="hint-box">当前显示的是输入检查概览。需要逐项明细时，再点击“运行检查”。</div>';
    }

    return html;
  }

  window.HBVStudioDataPrepView = {
    era5ApiPanelState,
    formatPrepDisplayTitle,
    formatPrepBlockedMessage,
    gisImportErrorUiState,
    gisImportStartingUiState,
    gisImportSuccessUiState,
    emptyInputCheckCache,
    hasRecentInputCheckCache,
    inputCheckCompletionState,
    meteoModePanelState,
    inputCheckCacheEntry,
    meteoModeHintState,
    meteoImportCreatingUiState,
    meteoImportErrorUiState,
    meteoImportUiState,
    meteoSourceLabels,
    prepPanelSummary,
    prepStepRunningStatus,
    prepTaskErrorUiState,
    prepTaskUiState,
    renderBootstrapStatus,
    renderInputCheckError,
    renderInputCheckImportBlock,
    renderInputCheckProgress,
    renderInputCheckResults,
    renderPrepStepList,
    visiblePrepSteps,
  };
})();
