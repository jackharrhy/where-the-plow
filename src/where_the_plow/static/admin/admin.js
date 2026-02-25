/* admin.js — vanilla JS admin panel for where-the-plow agent management */

// ── DOM refs ────────────────────────────────────────

const loginView = document.getElementById("login-view");
const adminView = document.getElementById("admin-view");
const statusBar = document.getElementById("status-bar");
const statusText = document.getElementById("status-text");

const loginForm = document.getElementById("login-form");
const loginPassword = document.getElementById("login-password");
const loginError = document.getElementById("login-error");

const agentsTbody = document.getElementById("agents-tbody");
const agentsEmpty = document.getElementById("agents-empty");
const refreshBtn = document.getElementById("refresh-btn");

const createForm = document.getElementById("create-form");
const createName = document.getElementById("create-name");

const keyOverlay = document.getElementById("key-overlay");
const keyTextarea = document.getElementById("key-textarea");
const keyAgentName = document.getElementById("key-agent-name");
const keyCopyBtn = document.getElementById("key-copy-btn");
const keyCloseBtn = document.getElementById("key-close-btn");

let refreshTimer = null;

// ── Helpers ─────────────────────────────────────────

function timeAgo(isoString) {
  if (!isoString) return "never";
  const seconds = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
  if (seconds < 0) return "just now";
  if (seconds < 60) return seconds + "s ago";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + "m ago";
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + "h ago";
  const days = Math.floor(hours / 24);
  return days + "d ago";
}

function truncateId(id) {
  if (!id) return "";
  return id.length > 12 ? id.slice(0, 12) + "..." : id;
}

function show(el) {
  el.classList.remove("hidden");
}

function hide(el) {
  el.classList.add("hidden");
}

// ── API calls ───────────────────────────────────────

async function login(password) {
  loginError && hide(loginError);

  const resp = await fetch("/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });

  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.error || "Login failed");
  }

  hide(loginView);
  show(adminView);
  show(statusBar);
  loadAgents();
  loadStatus();
  startAutoRefresh();
}

async function loadAgents() {
  const resp = await fetch("/admin/agents");
  if (resp.status === 401) {
    // Session expired — go back to login
    stopAutoRefresh();
    hide(adminView);
    hide(statusBar);
    show(loginView);
    return;
  }
  if (!resp.ok) return;

  const agents = await resp.json();
  renderAgents(agents);
}

async function createAgent(name) {
  const resp = await fetch("/admin/agents/create", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });

  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.error || "Failed to create agent");
  }

  const data = await resp.json();
  showKeyModal(data.name, data.private_key);
  loadAgents();
  loadStatus();
}

async function approveAgent(id) {
  const resp = await fetch("/admin/agents/" + encodeURIComponent(id) + "/approve", {
    method: "POST",
  });
  if (resp.ok) {
    loadAgents();
    loadStatus();
  }
}

async function revokeAgent(id) {
  const resp = await fetch("/admin/agents/" + encodeURIComponent(id) + "/revoke", {
    method: "POST",
  });
  if (resp.ok) {
    loadAgents();
    loadStatus();
  }
}

async function loadStatus() {
  const resp = await fetch("/admin/status");
  if (!resp.ok) return;
  const data = await resp.json();
  statusText.textContent =
    data.active_agents + " active / " + data.total_agents + " total agents";
}

// ── Rendering ───────────────────────────────────────

function renderAgents(agents) {
  agentsTbody.innerHTML = "";

  if (agents.length === 0) {
    show(agentsEmpty);
    return;
  }
  hide(agentsEmpty);

  for (const a of agents) {
    const tr = document.createElement("tr");

    // Name
    const tdName = document.createElement("td");
    tdName.textContent = a.name;
    tr.appendChild(tdName);

    // ID (truncated)
    const tdId = document.createElement("td");
    tdId.className = "cell-mono";
    tdId.textContent = truncateId(a.agent_id);
    tdId.title = a.agent_id;
    tr.appendChild(tdId);

    // Status
    const tdStatus = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "badge badge-" + a.status;
    badge.textContent = a.status;
    tdStatus.appendChild(badge);
    tr.appendChild(tdStatus);

    // IP
    const tdIp = document.createElement("td");
    tdIp.className = "cell-mono";
    tdIp.textContent = a.ip || "-";
    tr.appendChild(tdIp);

    // Last Seen
    const tdSeen = document.createElement("td");
    tdSeen.textContent = timeAgo(a.last_seen_at);
    tr.appendChild(tdSeen);

    // Reports
    const tdReports = document.createElement("td");
    const failed = a.failed_reports || 0;
    const total = a.total_reports || 0;
    const success = total - failed;
    tdReports.textContent = success + " / " + failed;
    tdReports.title = success + " success, " + failed + " failed";
    tr.appendChild(tdReports);

    // Actions
    const tdActions = document.createElement("td");
    tdActions.className = "cell-actions";

    if (a.status === "pending" || a.status === "revoked") {
      const approveBtn = document.createElement("button");
      approveBtn.className = "btn-small btn-approve";
      approveBtn.textContent = "Approve";
      approveBtn.addEventListener("click", () => approveAgent(a.agent_id));
      tdActions.appendChild(approveBtn);
    }

    if (a.status === "pending" || a.status === "approved") {
      const revokeBtn = document.createElement("button");
      revokeBtn.className = "btn-small btn-revoke";
      revokeBtn.textContent = "Revoke";
      revokeBtn.addEventListener("click", () => revokeAgent(a.agent_id));
      tdActions.appendChild(revokeBtn);
    }

    tr.appendChild(tdActions);
    agentsTbody.appendChild(tr);
  }
}

// ── Key modal ───────────────────────────────────────

function showKeyModal(name, privateKey) {
  keyAgentName.textContent = name;
  keyTextarea.value = privateKey;
  keyCopyBtn.textContent = "Copy";
  show(keyOverlay);
}

function hideKeyModal() {
  hide(keyOverlay);
  keyTextarea.value = "";
}

// ── Auto-refresh ────────────────────────────────────

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(() => {
    loadAgents();
    loadStatus();
  }, 10000);
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

// ── Event wiring ────────────────────────────────────

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pw = loginPassword.value;
  if (!pw) return;

  const btn = document.getElementById("login-btn");
  btn.disabled = true;
  btn.textContent = "Logging in...";

  try {
    await login(pw);
  } catch (err) {
    loginError.textContent = err.message;
    show(loginError);
  } finally {
    btn.disabled = false;
    btn.textContent = "Log in";
  }
});

createForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = createName.value.trim();
  if (!name) return;

  const btn = document.getElementById("create-btn");
  btn.disabled = true;

  try {
    await createAgent(name);
    createName.value = "";
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
  }
});

refreshBtn.addEventListener("click", () => {
  loadAgents();
  loadStatus();
});

keyCopyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(keyTextarea.value);
    keyCopyBtn.textContent = "Copied!";
    setTimeout(() => {
      keyCopyBtn.textContent = "Copy";
    }, 2000);
  } catch {
    keyTextarea.select();
  }
});

keyCloseBtn.addEventListener("click", hideKeyModal);
keyOverlay.addEventListener("click", (e) => {
  if (e.target === keyOverlay) hideKeyModal();
});

// ── Init: try loading agents in case we already have a cookie ──

(async function init() {
  const resp = await fetch("/admin/agents");
  if (resp.ok) {
    hide(loginView);
    show(adminView);
    show(statusBar);
    const agents = await resp.json();
    renderAgents(agents);
    loadStatus();
    startAutoRefresh();
  }
})();
