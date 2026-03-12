/* Robot Simulator – Web UI logic */
"use strict";

const chatLog   = document.getElementById("chat-log");
const cmdInput  = document.getElementById("cmd-input");
const cmdForm   = document.getElementById("cmd-form");
const btnSend   = document.getElementById("btn-send");
const cameraImg = document.getElementById("camera-img");
const overlay   = document.getElementById("camera-overlay");
const chkAuto   = document.getElementById("chk-auto-refresh");
const btnRefresh = document.getElementById("btn-refresh-camera");
const sceneData = document.getElementById("scene-data");
const execLogContent = document.getElementById("exec-log-content");
const modelSelect = document.getElementById("model-select");
const modelStatus = document.getElementById("model-status");
const modelDownload = document.getElementById("model-download");
const downloadLabel = document.getElementById("download-label");
const downloadBarFill = document.getElementById("download-bar-fill");

let ws = null;
let cameraTimer = null;
let modelList = [];
let _pipelineRunning = false;  // true while agent pipeline is in progress
const AGENT_ORDER = ["PlannerAgent", "SafetyAgent", "ExecutorAgent", "NarratorAgent"];

/* ── Camera ─────────────────────────────────────────────────────── */

let _cameraLoading = false;

function refreshCamera() {
  if (_cameraLoading) return;  // skip if previous frame still loading
  _cameraLoading = true;
  const img = new Image();
  img.onload = () => {
    cameraImg.src = img.src;
    overlay.classList.add("hidden");
    _cameraLoading = false;
  };
  img.onerror = () => {
    overlay.classList.remove("hidden");
    overlay.textContent = "Camera unavailable";
    _cameraLoading = false;
  };
  img.src = "/api/camera?t=" + Date.now();
}

function startAutoRefresh() {
  stopAutoRefresh();
  refreshCamera();
  cameraTimer = setInterval(refreshCamera, 250);  // ~4 fps
}

function stopAutoRefresh() {
  if (cameraTimer) { clearInterval(cameraTimer); cameraTimer = null; }
}

chkAuto.addEventListener("change", () => {
  if (chkAuto.checked) startAutoRefresh();
  else stopAutoRefresh();
});

btnRefresh.addEventListener("click", refreshCamera);

/* ── Scene info ─────────────────────────────────────────────────── */

async function fetchScene() {
  try {
    const resp = await fetch("/api/scene");
    if (!resp.ok) { sceneData.textContent = "Unavailable"; return; }
    const data = await resp.json();
    const lines = [];
    for (const obj of (data.objects || [])) {
      lines.push(`${obj.name}: pos=${JSON.stringify(obj.position)}`);
    }
    if (data.ee_position) {
      lines.push(`EE: ${JSON.stringify(data.ee_position)}`);
    }
    sceneData.textContent = lines.join("\n") || "Empty scene";
  } catch {
    sceneData.textContent = "Error fetching scene";
  }
}

/* ── Chat ───────────────────────────────────────────────────────── */

function addMessage(text, cls) {
  const div = document.createElement("div");
  div.className = "chat-msg " + cls;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function addBotMessage(text, detail) {
  const div = document.createElement("div");
  div.className = "chat-msg bot";
  div.textContent = text;
  if (detail) {
    const sub = document.createElement("div");
    sub.className = "plan-summary";
    sub.textContent = detail;
    div.appendChild(sub);
  }
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function sendCommand(text) {
  if (!text.trim()) return;
  addMessage(text, "user");

  // If pipeline is already running, queue the command visually but
  // still send it — the backend handles concurrent requests.
  _pipelineRunning = true;
  btnSend.disabled = true;
  cmdInput.disabled = true;

  resetAgentCards();

  try {
    const resp = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: text }),
    });
    const data = await resp.json();

    if (data.error) {
      addMessage(data.error, "error");
      _pipelineRunning = false;
      btnSend.disabled = false;
      cmdInput.disabled = false;
      cmdInput.focus();
    }
    // 202 accepted — results arrive via WebSocket command_done.
    // Keep input disabled until pipeline finishes.
  } catch (err) {
    addMessage("Network error: " + err.message, "error");
    _pipelineRunning = false;
    btnSend.disabled = false;
    cmdInput.disabled = false;
    cmdInput.focus();
  }
}

cmdForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = cmdInput.value.trim();
  if (!text) return;
  cmdInput.value = "";
  sendCommand(text);
});

/* ── Agent status cards ─────────────────────────────────────────── */

function resetAgentCards() {
  document.querySelectorAll(".agent-card").forEach((card) => {
    card.classList.remove("active", "done", "error");
    card.querySelector(".agent-detail").textContent = "";
  });
  document.querySelectorAll(".agent-arrow").forEach((a) => a.classList.remove("passed"));
  execLogContent.innerHTML = "";
}

function setAgentState(agentName, state, detail) {
  const card = document.querySelector(`.agent-card[data-agent="${agentName}"]`);
  if (!card) return;
  card.classList.remove("active", "done", "error");
  card.classList.add(state);
  if (detail) card.querySelector(".agent-detail").textContent = detail;

  // Mark arrows between completed agents as passed
  if (state === "done" || state === "error") {
    const idx = AGENT_ORDER.indexOf(agentName);
    if (idx >= 0) {
      const arrows = document.querySelectorAll(".agent-arrow");
      if (idx < arrows.length) arrows[idx].classList.add("passed");
    }
  }
}

function addExecLog(icon, text, cls) {
  const step = document.createElement("div");
  step.className = "exec-step " + (cls || "");
  step.innerHTML = `<span class="step-icon">${icon}</span><span class="step-text">${text}</span>`;
  execLogContent.appendChild(step);
  execLogContent.scrollTop = execLogContent.scrollHeight;
}

function markAllAgentsDone(data) {
  if (data.plan) {
    setAgentState("PlannerAgent", "done", `${data.plan.length} action(s)`);
  } else {
    setAgentState("PlannerAgent", "error", "no plan");
  }

  const v = data.validation;
  if (v && v.valid) {
    setAgentState("SafetyAgent", "done", "passed");
  } else if (v) {
    setAgentState("SafetyAgent", "error", "rejected");
  }

  if (data.results) {
    const ok = data.results.filter((r) => r.status === "ok").length;
    setAgentState("ExecutorAgent", "done", `${ok}/${data.results.length}`);
  }

  if (data.narration) {
    setAgentState("NarratorAgent", "done", "ready");
  }
}

/* ── Model selector ─────────────────────────────────────────────── */

function formatSize(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(1) + " GB";
  return mb + " MB";
}

function setModelStatusBadge(status, text) {
  modelStatus.className = "status-" + status;
  modelStatus.textContent = text || status;
  modelStatus.classList.remove("hidden");
}

function showDownloadBar(label, indeterminate) {
  downloadLabel.textContent = label;
  modelDownload.classList.remove("hidden", "determinate");
  if (!indeterminate) modelDownload.classList.add("determinate");
  downloadBarFill.style.width = indeterminate ? "100%" : "0%";
}

function hideDownloadBar() {
  modelDownload.classList.add("hidden");
}

async function fetchModels(retries = 5) {
  // Show active loading UI
  setModelStatusBadge("switching", "Fetching\u2026");
  showDownloadBar("Fetching model catalog\u2026", true);
  modelSelect.classList.add("loading");

  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const ctrl = new AbortController();
      const tid = setTimeout(() => ctrl.abort(), 20000);
      const resp = await fetch("/api/models", { signal: ctrl.signal });
      clearTimeout(tid);

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = await resp.json();

      // Server may return 200 but with empty models while still starting
      if ((!data.models || data.models.length === 0) && !data.ready) {
        if (attempt < retries) {
          setModelStatusBadge("switching", "Waiting for server\u2026");
          await new Promise((r) => setTimeout(r, 2000 * attempt));
          continue;
        }
      }

      modelList = data.models || [];

      // Split whisper (audio) models from chat models
      const chatModels = modelList.filter((m) => !m.alias.startsWith("whisper"));

      modelSelect.innerHTML = "";
      if (chatModels.length === 0) {
        modelSelect.innerHTML = "<option value=''>No models found</option>";
        setModelStatusBadge("error", "No models");
        hideDownloadBar();
        modelSelect.disabled = false;
        modelSelect.classList.remove("loading");
        // Schedule auto-retry in 5s
        setTimeout(() => fetchModels(3), 5000);
        return;
      }

      for (const m of chatModels) {
        const opt = document.createElement("option");
        opt.value = m.alias;
        const statusTag = m.current
          ? " \u2713"
          : m.status === "cached"
            ? " \u25CF"
            : "";
        opt.textContent = `${m.alias} (${formatSize(m.size_mb)})${statusTag}`;
        if (m.status === "available") opt.style.color = "#8b8fa8";
        if (m.current) opt.selected = true;
        modelSelect.appendChild(opt);
      }
      modelSelect.disabled = false;
      modelSelect.classList.remove("loading");
      hideDownloadBar();

      // Show status for current model
      const cur = chatModels.find((m) => m.current);
      if (cur) setModelStatusBadge("loaded", "Loaded");
      updateMicVisibility();
      return;
    } catch {
      if (attempt < retries) {
        setModelStatusBadge("switching", `Retry ${attempt}/${retries}\u2026`);
        await new Promise((r) => setTimeout(r, 2000 * attempt));
        continue;
      }
      modelSelect.innerHTML = "<option value=''>Click to retry</option>";
      modelSelect.disabled = false;
      modelSelect.classList.remove("loading");
      setModelStatusBadge("error", "Fetch failed");
      hideDownloadBar();
    }
  }
}

modelSelect.addEventListener("change", async () => {
  const alias = modelSelect.value;
  if (!alias) return;

  // Click-to-retry when showing error state
  if (!modelList.length || modelSelect.options[0]?.textContent.includes("retry")) {
    fetchModels();
    return;
  }

  const model = modelList.find((m) => m.alias === alias);
  if (!model) return;

  // Confirm if model needs downloading (large file)
  if (model.status === "available") {
    const ok = confirm(
      `Model "${alias}" (${formatSize(model.size_mb)}) is not downloaded yet.\n` +
      `Download and switch to it?`
    );
    if (!ok) {
      // Reset select to current model
      const cur = modelList.find((m) => m.current);
      if (cur) modelSelect.value = cur.alias;
      return;
    }
  }

  modelSelect.disabled = true;
  setModelStatusBadge("switching", "Switching\u2026");

  try {
    const resp = await fetch("/api/model/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ alias }),
    });
    const data = await resp.json();
    if (data.error) {
      setModelStatusBadge("error", data.error);
      modelSelect.disabled = false;
    }
    // Progress updates come via WebSocket
  } catch (err) {
    setModelStatusBadge("error", "Switch failed");
    modelSelect.disabled = false;
  }
});

/* ── Voice input (microphone) ────────────────────────────────────── */

const btnMic = document.getElementById("btn-mic");
let _mediaRecorder = null;
let _audioChunks = [];
let _micStream = null;

/** Show mic button only when a Whisper model is cached or loaded. */
function updateMicVisibility() {
  const hasWhisper = modelList.some(
    (m) => m.alias.startsWith("whisper") && (m.status === "cached" || m.status === "loaded")
  );
  btnMic.classList.toggle("hidden", !hasWhisper);
}

btnMic.addEventListener("mousedown", startRecording);
btnMic.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
btnMic.addEventListener("mouseup", stopRecording);
btnMic.addEventListener("touchend", stopRecording);
btnMic.addEventListener("mouseleave", stopRecording);

async function startRecording() {
  if (_mediaRecorder && _mediaRecorder.state === "recording") return;
  try {
    _micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    addMessage("Microphone access denied", "error");
    return;
  }
  _audioChunks = [];
  _mediaRecorder = new MediaRecorder(_micStream, { mimeType: "audio/webm;codecs=opus" });
  _mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) _audioChunks.push(e.data);
  };
  _mediaRecorder.onstop = handleRecordingComplete;
  _mediaRecorder.start(250);  // collect in 250ms chunks
  btnMic.classList.add("recording");
  btnMic.title = "Recording… release to send";
}

function stopRecording() {
  if (!_mediaRecorder || _mediaRecorder.state !== "recording") return;
  _mediaRecorder.stop();
  btnMic.classList.remove("recording");
  btnMic.title = "Hold to record voice command";
  // Stop mic access
  if (_micStream) {
    _micStream.getTracks().forEach((t) => t.stop());
    _micStream = null;
  }
}

async function handleRecordingComplete() {
  if (_audioChunks.length === 0) return;
  const blob = new Blob(_audioChunks, { type: "audio/webm" });
  _audioChunks = [];

  // Convert webm to WAV for Whisper (server expects WAV)
  const wavBlob = await convertToWav(blob);

  addMessage("[voice recording]", "user");
  btnSend.disabled = true;
  cmdInput.disabled = true;
  setModelStatusBadge("switching", "Transcribing\u2026");

  try {
    const form = new FormData();
    form.append("audio", wavBlob, "recording.wav");
    const resp = await fetch("/api/voice", { method: "POST", body: form });
    const data = await resp.json();
    if (data.text) {
      // Show transcribed text then send as command
      addMessage("Heard: " + data.text, "bot");
      setModelStatusBadge("loaded", "Loaded");
      sendCommand(data.text);
    } else {
      addMessage("Could not transcribe audio: " + (data.error || "unknown"), "error");
      setModelStatusBadge("error", "Transcription failed");
    }
  } catch (err) {
    addMessage("Voice error: " + err.message, "error");
    setModelStatusBadge("error", "Voice error");
  } finally {
    btnSend.disabled = false;
    cmdInput.disabled = false;
  }
}

async function convertToWav(blob) {
  const arrayBuf = await blob.arrayBuffer();
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  let audioBuf;
  try {
    audioBuf = await audioCtx.decodeAudioData(arrayBuf);
  } catch {
    // If decoding fails, send raw blob and let server handle it
    audioCtx.close();
    return blob;
  }

  // Resample to 16kHz mono
  const offCtx = new OfflineAudioContext(1, Math.ceil(audioBuf.duration * 16000), 16000);
  const src = offCtx.createBufferSource();
  src.buffer = audioBuf;
  src.connect(offCtx.destination);
  src.start();
  const rendered = await offCtx.startRendering();
  audioCtx.close();

  const samples = rendered.getChannelData(0);
  const int16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  // Build WAV
  const wavBuf = new ArrayBuffer(44 + int16.length * 2);
  const view = new DataView(wavBuf);
  const writeStr = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + int16.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);      // PCM
  view.setUint16(22, 1, true);      // mono
  view.setUint32(24, 16000, true);   // sample rate
  view.setUint32(28, 32000, true);   // byte rate
  view.setUint16(32, 2, true);      // block align
  view.setUint16(34, 16, true);     // bits per sample
  writeStr(36, "data");
  view.setUint32(40, int16.length * 2, true);
  const output = new Int16Array(wavBuf, 44);
  output.set(int16);

  return new Blob([wavBuf], { type: "audio/wav" });
}

/* ── WebSocket (for real-time agent updates) ────────────────────── */

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    // Server is up – refresh models if we don't have them yet
    if (!modelList.length) fetchModels();
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);

      /* ── Model progress messages ───────────────────────────────── */
      if (msg.type === "model_progress") {
        if (msg.status === "downloading") {
          setModelStatusBadge("switching", "Downloading\u2026");
          showDownloadBar(`Downloading ${msg.alias}\u2026`, true);
        } else if (msg.status === "loading") {
          setModelStatusBadge("switching", "Loading\u2026");
          showDownloadBar(`Loading ${msg.alias}\u2026`, true);
        } else if (msg.status === "checking") {
          setModelStatusBadge("switching", "Checking\u2026");
        } else if (msg.status === "ready") {
          setModelStatusBadge("loaded", "Loaded");
          hideDownloadBar();
          fetchModels();  // refresh list to update statuses
          modelSelect.disabled = false;
        } else if (msg.status === "error") {
          setModelStatusBadge("error", "Error");
          hideDownloadBar();
          modelSelect.disabled = false;
          // Reset select to current model
          fetchModels();
        }
        return;
      }

      if (msg.type === "model_switched") {
        setModelStatusBadge("loaded", "Loaded");
        hideDownloadBar();
        fetchModels();  // also updates mic visibility
        modelSelect.disabled = false;
        return;
      }

      /* ── Command pipeline done ─────────────────────────────────── */
      if (msg.type === "command_done") {
        _pipelineRunning = false;
        btnSend.disabled = false;
        cmdInput.disabled = false;
        cmdInput.focus();
        refreshCamera();
        fetchScene();

        if (msg.narration) {
          addBotMessage(msg.narration);
        }
        if (msg.plan) {
          const steps = msg.plan.map(
            (a, i) => `${i + 1}. ${a.tool}(${JSON.stringify(a.args)})`
          ).join("\n");
          addBotMessage("Plan executed:", steps);
        }
        const v = msg.validation;
        if (v && !v.valid && v.errors) {
          addMessage("Safety check failed: " + v.errors.join("; "), "error");
        }
        markAllAgentsDone(msg);
        return;
      }

      /* ── Agent step messages ───────────────────────────────────── */
      if (msg.type === "agent_step") {
        // Mark previous agents done if they were still active
        const idx = AGENT_ORDER.indexOf(msg.agent);

        setAgentState(msg.agent, "active", "running\u2026");
        addExecLog("\u25B6", `${msg.agent} started`, "");

        // Brief delay then mark done with details
        setTimeout(() => {
          let detail = "";
          let logIcon = "\u2714";
          let logCls = "ok";
          let logText = `${msg.agent} completed`;

          if (msg.agent === "PlannerAgent" && msg.plan) {
            detail = `${msg.plan.length} action(s)`;
            logText = `Planner: ${msg.plan.length} action(s) planned`;
            for (const a of msg.plan) {
              addExecLog("\u00B7", `${a.tool}(${JSON.stringify(a.args)})`, "ok");
            }
          } else if (msg.agent === "SafetyAgent" && msg.validation) {
            if (msg.validation.valid) {
              detail = "passed";
              logText = "Safety: all checks passed";
            } else {
              detail = "rejected";
              logIcon = "\u2718";
              logCls = "fail";
              logText = "Safety: " + (msg.validation.errors || []).join("; ");
            }
          } else if (msg.agent === "ExecutorAgent" && msg.results) {
            const ok = msg.results.filter((r) => r.status === "ok").length;
            detail = `${ok}/${msg.results.length}`;
            logText = `Executor: ${ok}/${msg.results.length} actions succeeded`;
            if (ok < msg.results.length) { logIcon = "\u26A0"; logCls = "fail"; }
          } else if (msg.agent === "NarratorAgent" && msg.narration) {
            detail = "ready";
            logText = "Narrator: summary ready";
          }

          const errState = msg.agent === "SafetyAgent" && msg.validation && !msg.validation.valid;
          setAgentState(msg.agent, errState ? "error" : "done", detail);
          addExecLog(logIcon, logText, logCls);

          // Also refresh camera after executor runs
          if (msg.agent === "ExecutorAgent") refreshCamera();
        }, 400);
      }
    } catch { /* ignore non-JSON */ }
  };

  ws.onclose = () => setTimeout(connectWebSocket, 2000);
  ws.onerror = () => ws.close();
}

/* ── Init ───────────────────────────────────────────────────────── */

startAutoRefresh();
fetchScene();
fetchModels();
connectWebSocket();
cmdInput.focus();
