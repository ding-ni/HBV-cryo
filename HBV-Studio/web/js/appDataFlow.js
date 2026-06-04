(function () {
  function taskCompletionState(tasks = [], previousTasks = null, options = {}) {
    const taskView = options.taskView || window.HBVStudioTaskView || {};
    const newlyFinishedTaskIds = taskView.newlyFinishedTaskIds || (() => []);
    const newlyCompletedTask = taskView.newlyCompletedTask || (() => null);
    const latestEditableRunPath = options.latestEditableRunPath || (() => "");

    const finishedTaskIds = newlyFinishedTaskIds(tasks, previousTasks);
    const manualStartTask = newlyCompletedTask(tasks, previousTasks, "manual_start");
    const calibrationTask = newlyCompletedTask(tasks, previousTasks, "calibration");
    const forecastTask = newlyCompletedTask(tasks, previousTasks, "forecast_restart");

    const manualStartRunPath = String(
      manualStartTask?.result?.run_path || manualStartTask?.run_path || ""
    ).trim();
    const calibrationRunPath = String(
      calibrationTask?.result?.run_path ||
      calibrationTask?.run_path ||
      calibrationTask?.detected_runs?.[0] ||
      latestEditableRunPath() ||
      ""
    ).trim();

    return {
      finishedTaskIds,
      hasFinishedTasks: finishedTaskIds.length > 0,
      manualStartTask,
      calibrationTask,
      forecastTask,
      manualStartRunPath,
      calibrationRunPath,
      manualStartWorkspacePath: String(manualStartTask?.config_path || "").trim(),
      calibrationWorkspacePath: String(
        calibrationTask?.result?.workspace_config || calibrationTask?.config_path || ""
      ).trim(),
    };
  }

  window.HBVStudioAppDataFlow = {
    taskCompletionState,
  };
})();
