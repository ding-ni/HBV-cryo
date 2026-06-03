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

  function toWizardInputTimeValue(value, hourly = false) {
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

  function fromWizardInputTimeValue(value, hourly = false) {
    if (!value) return "";
    return hourly ? String(value).replace("T", " ") : String(value).slice(0, 10);
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

  function gisImportRequestState(model = {}) {
    const cleanPath = value => String(value || "").trim();
    const demPath = cleanPath(model.demPath);
    const flowaccPath = cleanPath(model.flowaccPath);
    const flowdirPath = cleanPath(model.flowdirPath);
    const glacierMaskPath = cleanPath(model.glacierMaskPath);
    const missing = [];
    if (!demPath) missing.push("dem_path");
    if (!flowaccPath) missing.push("flowacc_masked_path");
    const ready = missing.length === 0;
    return {
      ready,
      missing,
      message: ready ? "" : "请至少选择裁剪后 DEM 和流量累积掩膜文件。",
      request: {
        dem_path: demPath,
        flowacc_masked_path: flowaccPath,
        flowdir_path: flowdirPath,
        glacier_mask_path: glacierMaskPath,
      },
    };
  }

  function gisModePanelState(mode = "") {
    const normalized = String(mode || "");
    return {
      mode: normalized,
      panels: {
        autoVisible: normalized === "auto",
        importVisible: normalized === "import",
      },
    };
  }

  function wizardConditionalFieldState(model = {}) {
    const sources = model.sources || {};
    return {
      step3Skipped: Boolean(model.fullUpstream),
      stationFieldsVisible: String(model.precipMode || "grid_only") !== "grid_only",
      hourlyPrecipVisible: String(model.timescale || "daily") !== "daily",
      customPrecVisible: sources.prec === "custom_tif",
      customTempVisible: sources.temp === "custom_tif",
      customPetVisible: sources.pet === "custom_tif",
    };
  }

  function projectFocusHintState(model = {}) {
    const hourly = Boolean(model.hourly);
    const objectType = String(model.objectType || "full_upstream_basin");
    if (!hourly && objectType === "full_upstream_basin") {
      return {
        text: "当前是“日尺度 + 完整上游流域”组合，最适合作为正式项目接入前的主运行流程。优先把时间分段、观测时间步和气象驱动覆盖先跑顺。",
        className: "hint-box status-ok",
      };
    }
    if (!hourly && objectType === "interbasin_with_boundary") {
      return {
        text: "当前是“日尺度 + 区间流域”组合。最关键的是上游边界入流 CSV：时间步要和项目一致、覆盖预热到验证全时段、不能有重复时间戳。",
        className: "hint-box status-warn",
      };
    }
    if (hourly && objectType === "full_upstream_basin") {
      return {
        text: "当前是“小时尺度 + 完整上游流域”组合。洪水过程更细，但对气象驱动完整性更敏感，建议先在日尺度完成主流程核对，再扩大到小时尺度。",
        className: "hint-box status-warn",
      };
    }
    return {
      text: "当前是“小时尺度 + 区间流域”组合，负载和输入要求都最高。建议先确认边界入流、小时气象驱动和时间分段都完全正确，再启动正式率定。",
      className: "hint-box status-warn",
    };
  }

  function boundaryGuidanceState(model = {}) {
    const fullUpstream = Boolean(model.fullUpstream);
    if (fullUpstream) {
      return {
        text: "当前流域工程类型为「完整上游流域」，本步通常可以跳过，不需要提供上游边界入流。",
        className: "hint-box",
      };
    }
    const hourly = Boolean(model.hourly);
    return {
      text: hourly
        ? "区间流域小时项目对边界入流最敏感。建议先确认 CSV 时间步为 1 小时、覆盖预热至验证全时段、零值不是误填缺测。"
        : "区间流域日尺度项目建议先确认边界入流为 24 小时间隔，并覆盖预热、率定、验证全时段；重复时间戳和负值要先清掉。",
      className: "hint-box status-warn",
    };
  }

  function boundaryPreviewQueryState(model = {}) {
    const stepHours = model.hourly ? "1" : "24";
    const expectedStart = String(model.expectedStart || "").trim();
    const expectedEnd = String(model.expectedEnd || "").trim();
    const workspacePath = String(model.workspacePath || "").trim();
    if (expectedStart || expectedEnd) {
      const entries = [];
      if (expectedStart) entries.push(["expected_start", expectedStart]);
      if (expectedEnd) entries.push(["expected_end", expectedEnd]);
      entries.push(["expected_step_hours", stepHours]);
      return { entries, source: "expected_range", stepHours };
    }
    if (workspacePath) {
      return { entries: [["config_path", workspacePath]], source: "workspace", stepHours };
    }
    return { entries: [["expected_step_hours", stepHours]], source: "step_hours", stepHours };
  }

  function defaultFormatNumber(value, digits = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  function boundaryPreviewState(data = {}, helpers = {}) {
    const d = data || {};
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const formatNumber = helpers.formatNumber || defaultFormatNumber;
    const renderEngineeringFocusChecks = helpers.renderEngineeringFocusChecks || (() => "");
    const hasCoverage = d.coverage_ratio !== null && d.coverage_ratio !== undefined;
    const duplicateCount = Number(d.duplicate_count || 0);
    const negativeCount = Number(d.negative_count || 0);
    const validRows = Number(d.valid_rows || 0);
    const zeroCount = Number(d.zero_count || 0);
    const coverageLow = hasCoverage && Number(d.coverage_ratio) < 0.99;
    const failed = duplicateCount > 0 || negativeCount > 0;
    const status = failed ? "fail" : coverageLow ? "warn" : "ok";
    const className = `hint-box ${status === "fail" ? "status-fail" : status === "warn" ? "status-warn" : "status-ok"}`;
    const suggestedProfile = d.suggested_calibration_mode === "hourly" ? "小时尺度" : "日尺度";
    const detectedStep = d.time_step_hours !== null && d.time_step_hours !== undefined ? `${formatNumber(d.time_step_hours, 0)} 小时` : "未识别";
    const expectedStep = d.expected_time_step_hours !== null && d.expected_time_step_hours !== undefined ? `${formatNumber(d.expected_time_step_hours, 0)} 小时` : "未提供";
    const coverage = hasCoverage ? `${formatNumber(Number(d.coverage_ratio) * 100, 1)}%` : "未与当前项目时段对比";
    const zeroRatio = validRows ? `${formatNumber((zeroCount / Math.max(1, validRows)) * 100, 1)}%` : "—";
    const checks = [
      { label: "识别时间步长", value: detectedStep, status: d.time_step_hours && d.expected_time_step_hours && Number(d.time_step_hours) !== Number(d.expected_time_step_hours) ? "fail" : "ok" },
      { label: "当前项目时间步长", value: expectedStep, status: "ok" },
      { label: "覆盖率", value: coverage, status: coverageLow ? "fail" : "ok" },
      { label: "重复时间戳", value: String(duplicateCount), status: duplicateCount > 0 ? "fail" : "ok" },
      { label: "负流量记录", value: String(negativeCount), status: negativeCount > 0 ? "fail" : "ok" },
      { label: "零值比例", value: zeroRatio, status: validRows > 0 && zeroCount / Math.max(1, validRows) >= 0.8 ? "warn" : "ok" },
    ];
    const summary = coverageLow
      ? "当前边界入流和项目时段相比仍有缺口，建议先补齐覆盖范围后再做率定。"
      : failed
        ? "边界入流存在重复时间戳或负值，建议先清洗数据。"
        : "边界入流预览通过，可继续结合第 7 步输入检查核对覆盖范围。";
    const focusHtml = renderEngineeringFocusChecks([
      { title: "边界入流预览检查", summary, status, items: checks },
    ], { title: "边界入流预览检查" });
    return {
      html: `
      <div class="${className}">
        <strong>边界入流概览</strong><br>
        有效记录 ${escapeHtml(String(validRows))}/${escapeHtml(String(d.total_rows || 0))} 行；
        时间范围 ${escapeHtml(d.date_range?.start || "—")} → ${escapeHtml(d.date_range?.end || "—")}；
        流量范围 ${escapeHtml(formatNumber(d.flow_stats?.min, 2))} ~ ${escapeHtml(formatNumber(d.flow_stats?.max, 2))} m³/s；
        建议模式 ${escapeHtml(suggestedProfile)}。
      </div>
      ${focusHtml}
    `,
      className,
      status,
      summary,
      checks,
    };
  }

  function boundaryPreviewErrorState(error = {}, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const message = error?.message || String(error || "预览失败");
    return {
      html: `<div class="hint-box status-fail">边界入流预览失败：${escapeHtml(message)}</div>`,
      className: "hint-box status-fail",
      text: `边界入流预览失败：${message}`,
    };
  }

  function wizardValidationFailureState(validation = {}, step = 0, helpers = {}) {
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const data = validation || {};
    const stepNumber = Number(step) || step;
    const missing = Array.isArray(data.missing) ? data.missing : [];
    const warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const issueItems = missing.slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    const warningItems = warnings.slice(0, 2).map(item => `<li>${escapeHtml(item)}</li>`).join("");
    const bodyHtml = `<strong>第 ${escapeHtml(stepNumber)} 步未通过。</strong>${issueItems ? `<ul>${issueItems}</ul>` : ""}${warningItems ? `<div style="margin-top:6px">提示：</div><ul>${warningItems}</ul>` : ""}`;
    const preview = missing.slice(0, 3).join("；");
    const result = {
      eventSummary: null,
      hint: null,
      toastText: `第 ${stepNumber} 步未完成：${preview || "请补全必填项"}`,
    };

    if (Number(stepNumber) === 2) {
      result.eventSummary = {
        eventWindows: data.event_windows || null,
        observationCoverage: data.event_observation_coverage || null,
      };
      result.hint = {
        targetId: "wz-obs-hint",
        html: bodyHtml,
        className: "hint-box status-fail",
      };
    } else if (Number(stepNumber) === 3) {
      result.hint = {
        targetId: "wz-boundary-preview",
        html: `<div class="hint-box status-fail">${bodyHtml}</div>`,
      };
    }

    return result;
  }

  function parseObservationComparableTime(text) {
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

  function formatObservationComparableTime(date, hourly = false) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "—";
    const yyyy = String(date.getFullYear()).padStart(4, "0");
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    if (!hourly) return `${yyyy}-${mm}-${dd}`;
    const hh = String(date.getHours()).padStart(2, "0");
    const mi = String(date.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  }

  function observationHintState(model = {}, helpers = {}) {
    model = model || {};
    const escapeHtml = helpers.escapeHtml || defaultEscapeHtml;
    const info = model.info || null;
    if (!info) {
      return {
        html: "",
        text: "选择观测径流文件后将自动推断时间范围。",
        className: "hint-box",
      };
    }
    const selectedProfile = model.selectedProfile === "hourly" ? "hourly" : "daily";
    const hourly = selectedProfile === "hourly";
    const timeBasis = String(model.timeBasis || "continuous");
    const periods = Array.isArray(model.periods) ? model.periods : [];
    const obsStart = parseObservationComparableTime(info.start);
    const obsEnd = parseObservationComparableTime(info.end);
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
    if (timeBasis !== "event_windows") {
      periods.forEach(period => {
        const startTs = parseObservationComparableTime(period.start);
        const endTs = parseObservationComparableTime(period.end);
        if (!startTs || !endTs || !obsStart || !obsEnd) return;
        if (startTs < obsStart) {
          issues.push(`${period.label}开始早于观测起点（${formatObservationComparableTime(startTs, hourly)} < ${formatObservationComparableTime(obsStart, hourly)}）。`);
        }
        if (endTs > obsEnd) {
          issues.push(`${period.label}结束晚于观测终点（${formatObservationComparableTime(endTs, hourly)} > ${formatObservationComparableTime(obsEnd, hourly)}）。`);
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
      return {
        html: `<strong>观测时段检查未通过。</strong><br>${escapeHtml(summary)}<ul>${issues.slice(0, 4).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`,
        text: "",
        className: "hint-box status-fail",
      };
    }
    if (warnings.length) {
      return {
        html: `<strong>观测时段检查通过，但建议继续优化。</strong><br>${escapeHtml(summary)}<ul>${warnings.slice(0, 3).map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`,
        text: "",
        className: "hint-box status-warn",
      };
    }
    return {
      html: "",
      text: `${summary} 当前率定期和验证期都落在观测覆盖范围内。`,
      className: "hint-box status-ok",
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

  function meteoSourceState(sources = {}) {
    const localLabels = meteoSourceLabels(sources, "local");
    const pipelineLabels = meteoSourceLabels(sources, "pipeline");
    return {
      localLabels,
      pipelineLabels,
      needsEra5Download: sources.prec === "era5" || sources.temp !== "custom_tif" || sources.pet !== "custom_tif",
      needSignature: `${sources.prec || ""}|${sources.temp || ""}|${sources.pet || ""}`,
      hasLocalMeteoSourceConfigured: localLabels.length > 0,
      allMeteoSourcesUseLocalTif: localLabels.length === 3,
    };
  }

  function customMeteoImportCopyState(model = {}) {
    const sources = model.sources || {};
    const registeredDirs = model.registeredDirs || {};
    const importDirs = model.importDirs || {};
    const force = Boolean(model.force);
    const fields = [
      { key: "prec", label: "降水" },
      { key: "temp", label: "气温" },
      { key: "pet", label: "蒸散发" },
    ];
    const updates = fields.flatMap(field => {
      if (sources[field.key] !== "custom_tif") return [];
      const value = String(registeredDirs[field.key] || "").trim();
      const current = String(importDirs[field.key] || "").trim();
      if (!value || (!force && current)) return [];
      return [{ key: field.key, value, label: field.label }];
    });
    return {
      updates,
      copiedCount: updates.length,
      copiedLabels: updates.map(item => item.label),
    };
  }

  function customMeteoImportDirectoryState(model = {}) {
    const sources = model.sources || {};
    const registeredDirs = model.registeredDirs || {};
    const importDirs = model.importDirs || {};
    const fields = ["prec", "temp", "pet"];
    const dirs = Object.fromEntries(fields.map(key => {
      const current = String(importDirs[key] || "").trim();
      const fallback = sources[key] === "custom_tif" ? String(registeredDirs[key] || "").trim() : "";
      return [key, current || fallback];
    }));
    const missing = fields.filter(key => !dirs[key]);
    const writeBackUpdates = missing.length ? [] : fields.flatMap(key => {
      const current = String(importDirs[key] || "").trim();
      return current ? [] : [{ key, value: dirs[key] }];
    });
    return {
      dirs,
      ready: missing.length === 0,
      missing,
      writeBackUpdates,
    };
  }

  function meteoImportRequestState(model = {}) {
    const directoryState = customMeteoImportDirectoryState(model);
    const dirs = directoryState.dirs || {};
    const ready = Boolean(directoryState.ready);
    return {
      ready,
      message: ready ? "" : "请选择降水、气温和蒸散发三个目录。",
      missing: directoryState.missing,
      writeBackUpdates: directoryState.writeBackUpdates,
      request: {
        prec_source: String(model.runtimePrecipSource || "").trim(),
        prec_dir: String(dirs.prec || "").trim(),
        temp_dir: String(dirs.temp || "").trim(),
        evap_dir: String(dirs.pet || "").trim(),
      },
    };
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

  function prepTaskRequestState(model = {}) {
    const stepId = String(model.stepId || "").trim();
    const ready = Boolean(stepId);
    return {
      ready,
      message: ready ? "" : "请选择要执行的数据处理步骤。",
      request: {
        step_id: stepId,
        prec_source: String(model.runtimePrecipSource || "").trim(),
        overwrite: Boolean(model.overwrite),
      },
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
    boundaryGuidanceState,
    boundaryPreviewQueryState,
    boundaryPreviewErrorState,
    boundaryPreviewState,
    customMeteoImportCopyState,
    customMeteoImportDirectoryState,
    era5ApiPanelState,
    formatPrepDisplayTitle,
    formatPrepBlockedMessage,
    fromWizardInputTimeValue,
    gisImportErrorUiState,
    gisImportRequestState,
    gisModePanelState,
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
    meteoImportRequestState,
    meteoImportUiState,
    meteoSourceLabels,
    meteoSourceState,
    observationHintState,
    prepPanelSummary,
    prepStepRunningStatus,
    prepTaskRequestState,
    prepTaskErrorUiState,
    prepTaskUiState,
    projectFocusHintState,
    renderBootstrapStatus,
    renderInputCheckError,
    renderInputCheckImportBlock,
    renderInputCheckProgress,
    renderInputCheckResults,
    renderPrepStepList,
    toWizardInputTimeValue,
    visiblePrepSteps,
    wizardConditionalFieldState,
    wizardValidationFailureState,
  };
})();
