const $ = (id) => document.getElementById(id);
let state = null;
let settingsHydrated = false;
let participantSelectionInitialized = false;
let knownProfileIds = new Set();
let selectedSpeakerIds = new Set();

async function call(name, ...args) {
  const api = window.pywebview?.api;
  if (!api || typeof api[name] !== "function") {
    toast("桌面 API 尚未就绪", true);
    return null;
  }
  const result = await api[name](...args);
  if (!result.ok) toast(result.error || "操作失败", true);
  else if (result.message) toast(result.message);
  if (result.data) render(result.data);
  return result;
}

function toast(message, error = false) {
  const element = $("toast");
  element.textContent = message;
  element.className = error ? "visible error" : "visible";
  clearTimeout(element.timer);
  element.timer = setTimeout(() => { element.className = ""; }, 3200);
}

function render(next) {
  state = next;
  const active = next.activeSession;
  $("statusText").textContent = active?.stage_message || "等待开始";
  $("stageBadge").textContent = active?.status || "待机";
  $("duration").textContent = formatDuration(next.recordedSeconds || 0);
  const enrollmentRunning = Boolean(next.voiceprintEnrollment?.running);
  const sessionLocked = next.recording || next.paused || next.processing;
  $("analysisStyle").disabled = sessionLocked;
  renderParticipants(next.profiles || [], sessionLocked || enrollmentRunning);
  const hasParticipants = selectedSpeakerIds.size > 0;
  $("startButton").disabled = next.recording || next.paused || next.processing ||
    enrollmentRunning || !hasParticipants;
  $("pauseButton").disabled = !next.recording;
  $("resumeButton").disabled = !next.paused;
  $("stopButton").disabled = !(next.recording || next.paused);
  $("importButton").disabled = next.recording || next.paused || next.processing ||
    enrollmentRunning || !hasParticipants;
  const voiceprintRecording = Boolean(next.voiceprintRecording);
  $("recordSampleButton").textContent = voiceprintRecording ? "停止样本" : "录制样本";
  $("recordSampleButton").disabled = next.recording || next.paused || next.processing ||
    enrollmentRunning;
  $("finishEnrollmentButton").textContent = enrollmentRunning ? "正在注册…" : "完成注册";
  $("finishEnrollmentButton").disabled = enrollmentRunning || voiceprintRecording ||
    (next.voiceprintDraft?.sampleCount || 0) < 3;
  $("clearSamplesButton").disabled = enrollmentRunning || voiceprintRecording ||
    (next.voiceprintDraft?.sampleCount || 0) === 0;
  $("enrollButton").disabled = enrollmentRunning || voiceprintRecording ||
    next.recording || next.paused || next.processing;
  renderVoiceprintDraft(next);
  renderDevices(next.inputDevices || []);
  renderProfiles(next.profiles || []);
  renderDialogue(active?.resolved_utterances || []);
  renderAnalysis(active?.analysis || {}, active?.analysis_style || "chat");
  renderHistory(next.recentSessions || []);
  const model = next.modelAvailability || {};
  const modelText = model.campPlus ? "CAM++ 可用" : "依赖未完成";
  $("modelStatus").textContent = `${modelText} · ${next.apiConfigured ? "API 已配置" : "API 未配置"}`;
  if (!settingsHydrated) {
    hydrateSettings(next.settings || {});
    settingsHydrated = true;
  }
}

function renderVoiceprintDraft(next) {
  const element = $("voiceprintDraft");
  const draft = next.voiceprintDraft || {};
  const enrollment = next.voiceprintEnrollment || {};
  if (enrollment.running) {
    element.className = "voiceprint-draft recording";
    const progress = enrollment.total
      ? ` ${enrollment.current}/${enrollment.total}`
      : "";
    element.textContent = `${enrollment.stage || "正在注册声纹"}${progress}`;
    return;
  }
  if (enrollment.error) {
    element.className = "voiceprint-draft error";
    element.textContent = `注册失败：${enrollment.error}`;
    return;
  }
  if (enrollment.completedName && !draft.sampleCount) {
    element.className = "voiceprint-draft success";
    element.textContent = `已完成声纹注册：${enrollment.completedName}`;
    return;
  }
  if (next.voiceprintRecording) {
    element.className = "voiceprint-draft recording";
    element.textContent = `正在录制 ${draft.name || ""} · ${formatDuration(next.voiceprintRecordedSeconds || 0)}`;
    return;
  }
  if (draft.error) {
    element.className = "voiceprint-draft error";
    element.textContent = draft.error;
    return;
  }
  element.className = "voiceprint-draft";
  element.textContent = draft.sampleCount
    ? `${draft.name}：已录制 ${draft.sampleCount} 段，建议 3～5 段`
    : "尚未录制样本";
}

function hydrateSettings(value) {
  $("asrModel").value = value.asr_model || "paraformer-v2";
  $("asrVocabularyId").value = value.asr_vocabulary_id || "";
  $("asrLanguageHints").value = value.asr_language_hints || "zh,en";
  $("qwenModel").value = value.qwen_model || "qwen-plus";
  $("voiceThreshold").value = value.voiceprint_threshold ?? 0.33;
  $("voiceMargin").value = value.voiceprint_margin ?? 0.06;
  $("sclThreshold").value = value.scl_trigger_threshold ?? 0.24;
  $("enableScl").checked = value.enable_scl !== false;
  $("speakerMode").value = value.speaker_mode || "two";
}

function renderDevices(devices) {
  const select = $("inputDevice");
  if (select.dataset.loaded === "1") return;
  select.innerHTML = '<option value="">系统默认麦克风</option>' +
    devices.map(item => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
  select.dataset.loaded = "1";
}

function renderProfiles(profiles) {
  $("profiles").innerHTML = profiles.length ? profiles.map(profile => `
    <div class="profile">
      <div><strong>${escapeHtml(profile.name)}</strong><small>${profile.sample_paths.length} 个样本</small></div>
      <button title="删除声纹" aria-label="删除声纹" onclick="deleteProfile('${profile.id}')">×</button>
    </div>`).join("") : '<div class="empty">尚未注册声纹</div>';
}

function renderParticipants(profiles, locked) {
  const availableIds = new Set(profiles.map(profile => profile.id));
  if (!participantSelectionInitialized) {
    selectedSpeakerIds = new Set(availableIds);
    participantSelectionInitialized = true;
  } else {
    for (const id of availableIds) {
      if (!knownProfileIds.has(id)) selectedSpeakerIds.add(id);
    }
    for (const id of selectedSpeakerIds) {
      if (!availableIds.has(id)) selectedSpeakerIds.delete(id);
    }
  }
  knownProfileIds = availableIds;

  const element = $("participantOptions");
  element.innerHTML = profiles.length ? profiles.map(profile => `
    <label class="participant-option">
      <input type="checkbox" value="${escapeHtml(profile.id)}"
        ${selectedSpeakerIds.has(profile.id) ? "checked" : ""}
        ${locked ? "disabled" : ""} />
      <span>${escapeHtml(profile.name)}</span>
    </label>`).join("") : '<div class="participant-empty">请先注册声纹档案</div>';
  const allSelected = availableIds.size > 0 &&
    [...availableIds].every(id => selectedSpeakerIds.has(id));
  $("selectAllParticipants").textContent = allSelected ? "清空" : "全选";
  $("selectAllParticipants").disabled = locked || !profiles.length;
}

function renderDialogue(items) {
  const element = $("dialogue");
  if (!items.length) {
    element.className = "dialogue empty";
    element.textContent = "完成逐句切片和声纹匹配后，对话会按时间逐行出现在这里。";
    return;
  }
  element.className = "dialogue";
  element.innerHTML = items.map(item => `
    <div class="turn ${item.canonical_speaker_id ? "" : "unknown"}">
      <div class="turn-head">
        <span class="speaker">${escapeHtml(item.display_name)}</span>
        <span class="time">${formatMs(item.start_ms)} - ${formatMs(item.end_ms)}</span>
        <span class="confidence">${renderMatchEvidence(item)}</span>
      </div>
      <p>${escapeHtml(item.text)}</p>
    </div>`).join("");
}

function renderAnalysis(value, style) {
  const element = $("analysis");
  const labels = {
    chat: "对话分析",
    meeting_notes: "会议纪要",
    formal_paragraph: "正式段落",
    summary_bullets: "摘要要点",
    todo_items: "待办事项",
    faithful_cleanup: "忠实清理"
  };
  $("analysisHeading").textContent = labels[style] || "对话整理";
  if (!Object.keys(value).length) {
    element.className = "analysis empty";
    element.textContent = "整理 Agent 尚未生成结果。";
    return;
  }
  element.className = "analysis";
  const list = (title, values) => values?.length
    ? `<h3>${title}</h3><ul>${values.map(item => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>` : "";
  const actions = value.actionItems?.length
    ? `<h3>后续行动</h3><ul>${value.actionItems.map(item =>
      `<li>${escapeHtml(item.task || "")}（${escapeHtml(item.owner || "未指定")} · ${escapeHtml(item.deadline || "未指定")}）</li>`
    ).join("")}</ul>` : "";
  const title = `<h2>${escapeHtml(value.title || labels[style] || "对话整理")}</h2>`;
  if (style === "formal_paragraph") {
    element.innerHTML = title + (value.paragraphs || [])
      .map(item => `<p>${escapeHtml(item)}</p>`).join("");
    return;
  }
  if (style === "summary_bullets") {
    element.innerHTML = title + list("摘要要点", value.bullets);
    return;
  }
  if (style === "todo_items") {
    element.innerHTML = title + actions;
    return;
  }
  if (style === "faithful_cleanup") {
    element.innerHTML = title + (value.turns || []).map(item => `
      <div class="clean-turn">
        <div><strong>${escapeHtml(item.speaker || "未识别发言人")}</strong>
          <span>${escapeHtml(item.time || "")}</span></div>
        <p>${escapeHtml(item.text || "")}</p>
      </div>`).join("");
    return;
  }
  element.innerHTML = `
    ${title}
    ${value.overview ? `<h3>概览</h3><p>${escapeHtml(value.overview)}</p>` : ""}
    ${list("核心观点", value.keyPoints)}
    ${style === "chat" ? list("共识", value.agreements) : ""}
    ${style === "chat" ? list("分歧", value.disagreements) : ""}
    ${list("决定事项", value.decisions)}
    ${list("未解决问题", value.openQuestions)}
    ${actions}`;
}

function renderHistory(items) {
  const activeId = state?.activeSession?.id;
  $("history").innerHTML = items.length ? items.map(item => `
    <button class="history-item ${item.id === activeId ? "selected" : ""}"
      type="button" data-session-id="${escapeHtml(item.id)}">
      <div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.created_at)}</small></div>
      <span>${escapeHtml(item.status)}</span>
    </button>`).join("") : '<div class="empty">暂无历史会话</div>';
}

function currentPayload() {
  return {
    title: $("sessionTitle").value,
    speakerMode: $("speakerMode").value,
    analysisStyle: $("analysisStyle").value,
    selectedSpeakerIds: [...selectedSpeakerIds],
    device: $("inputDevice").value
  };
}

async function refresh() {
  const result = await call("get_state");
  if (result?.data) render(result.data);
}

window.deleteProfile = async (id) => call("delete_profile", id);

$("startButton").onclick = () => call("start_recording", currentPayload());
$("pauseButton").onclick = () => call("pause_recording");
$("resumeButton").onclick = () => call("resume_recording");
$("stopButton").onclick = () => call("stop_recording");
$("importButton").onclick = () => call("import_audio", currentPayload());
$("participantOptions").onchange = event => {
  const input = event.target.closest('input[type="checkbox"]');
  if (!input) return;
  if (input.checked) selectedSpeakerIds.add(input.value);
  else selectedSpeakerIds.delete(input.value);
  render(state);
};
$("selectAllParticipants").onclick = () => {
  const allSelected = knownProfileIds.size > 0 &&
    [...knownProfileIds].every(id => selectedSpeakerIds.has(id));
  selectedSpeakerIds = allSelected ? new Set() : new Set(knownProfileIds);
  render(state);
};
$("enrollButton").onclick = () => {
  const name = $("profileName").value.trim();
  if (!name) return toast("请先填写姓名", true);
  call("enroll_profile", name);
};
$("recordSampleButton").onclick = () => {
  if (state?.voiceprintRecording) {
    call("stop_voiceprint_sample");
    return;
  }
  const name = $("profileName").value.trim();
  if (!name) return toast("请先填写姓名", true);
  call("start_voiceprint_sample", {
    name,
    device: $("inputDevice").value
  });
};
$("finishEnrollmentButton").onclick = () => call("finish_voiceprint_enrollment");
$("clearSamplesButton").onclick = () => call("clear_voiceprint_draft");
$("saveSettings").onclick = () => call("save_settings", {
  asr_model: $("asrModel").value.trim() || "paraformer-v2",
  asr_vocabulary_id: $("asrVocabularyId").value.trim(),
  asr_language_hints: $("asrLanguageHints").value.trim() || "zh,en",
  speaker_mode: $("speakerMode").value,
  qwen_model: $("qwenModel").value.trim() || "qwen-plus",
  voiceprint_threshold: Number($("voiceThreshold").value),
  voiceprint_margin: Number($("voiceMargin").value),
  scl_trigger_threshold: Number($("sclThreshold").value),
  enable_scl: $("enableScl").checked
});
$("copyDialogue").onclick = () => call("copy_result", "dialogue");
$("copyAnalysis").onclick = () => call("copy_result", "analysis");
$("openData").onclick = () => call("open_data_folder");
$("history").onclick = async (event) => {
  const item = event.target.closest("[data-session-id]");
  if (!item) return;
  const result = await call("load_session", item.dataset.sessionId);
  if (result?.ok) activateTab("dialogue");
};

document.querySelectorAll(".tab").forEach(button => {
  button.onclick = () => activateTab(button.dataset.tab);
});

function activateTab(name) {
  document.querySelectorAll(".tab").forEach(item =>
    item.classList.toggle("active", item.dataset.tab === name)
  );
  document.querySelectorAll(".panel").forEach(item => item.classList.remove("active"));
  $(`${name}Panel`).classList.add("active");
  $(`${name}Panel`).scrollTop = 0;
}

function formatDuration(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}
function formatMs(ms) {
  const value = Math.max(0, Math.floor(ms || 0));
  const seconds = Math.floor(value / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:` +
    `${String(seconds % 60).padStart(2, "0")}.` +
    `${String(value % 1000).padStart(3, "0")}`;
}
function formatScore(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "--";
}
function renderMatchEvidence(item) {
  if (!item.canonical_speaker_id || item.confidence === "unknown" || item.confidence === "low") {
    return "未识别";
  }
  return `${escapeHtml(item.confidence)} · 匹配 ${formatScore(item.score)} · ` +
    `领先 ${formatScore(item.margin)}`;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  })[char]);
}

window.addEventListener("pywebviewready", () => {
  refresh();
  setInterval(refresh, 1200);
});
