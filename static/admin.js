const themeButton = document.getElementById("btn-theme");
const page = document.body && document.body.dataset ? document.body.dataset.page : null;

function setThemeDark(enabled) {
  document.documentElement.classList.toggle("dark", enabled);
  if (themeButton) {
    const icon = themeButton.querySelector(".material-icons-outlined");
    if (icon) {
      icon.textContent = enabled ? "light_mode" : "dark_mode";
    }
  }
  try {
    localStorage.setItem("themeDark", enabled ? "1" : "0");
  } catch (err) {
    // ignore
  }
}

if (themeButton) {
  themeButton.addEventListener("click", () => {
    setThemeDark(!document.documentElement.classList.contains("dark"));
  });
  try {
    const saved = localStorage.getItem("themeDark");
    if (saved === "1") {
      setThemeDark(true);
    }
  } catch (err) {
    // ignore
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setStatus(el, ok, text) {
  if (!el) return;
  el.className = "result";
  if (ok === true) {
    el.className += " ok";
  } else if (ok === false) {
    el.className += " err";
  }
  el.textContent = text || "";
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = data.detail
      || data.message
      || (data.errors ? JSON.stringify(data.errors) : null)
      || "Request failed";
    const error = new Error(message);
    error.status = res.status;
    error.data = data;
    throw error;
  }
  return data;
}

async function loadSummary() {
  const statusEl = document.getElementById("summary-status");
  setStatus(statusEl, null, "Loading...");
  try {
    const data = await fetchJson("/api/admin/summary");
    document.getElementById("summary-accounts-total").textContent = data.accounts.total ?? "--";
    document.getElementById("summary-accounts-active").textContent = data.accounts.active ?? "--";
    document.getElementById("summary-accounts-connected").textContent = data.accounts.connected ?? "--";
    document.getElementById("summary-accounts-authorized").textContent = data.accounts.authorized ?? "--";
    document.getElementById("summary-operators-total").textContent = data.operators.total ?? "--";
    document.getElementById("summary-outbox-queued").textContent = data.outbox.queued ?? "--";
    document.getElementById("summary-outbox-failed").textContent = data.outbox.failed ?? "--";
    document.getElementById("summary-outbox-dead").textContent = data.outbox.dead ?? "--";
    document.getElementById("summary-outbox-processing").textContent = data.outbox.processing ?? "--";
    document.getElementById("summary-outbox-sent").textContent = data.outbox.sent ?? "--";

    const lastEventEl = document.getElementById("summary-last-event");
    const lastEventTimeEl = document.getElementById("summary-last-event-time");
    if (data.last_event) {
      lastEventEl.textContent = data.last_event.message || "--";
      lastEventTimeEl.textContent = data.last_event.created_at || "--";
    } else {
      lastEventEl.textContent = "--";
      lastEventTimeEl.textContent = "--";
    }
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

function buildAccountRow(account, onSave) {
  const row = document.createElement("tr");
  row.className = "border-b border-border-light dark:border-border-dark";

  const accountCell = document.createElement("td");
  accountCell.className = "py-3 px-3";
  accountCell.innerHTML = `
    <div class="font-semibold">${escapeHtml(account.label || account.phone_number)}</div>
    <div class="text-xs text-gray-500">ID ${escapeHtml(account.account_id)}</div>
    <div class="text-xs text-gray-500">${escapeHtml(account.phone_number || "")}</div>
  `;
  row.appendChild(accountCell);

  const labelCell = document.createElement("td");
  labelCell.className = "py-3 px-3";
  const labelInput = document.createElement("input");
  labelInput.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
  labelInput.value = account.label || "";
  labelCell.appendChild(labelInput);
  row.appendChild(labelCell);

  const activeCell = document.createElement("td");
  activeCell.className = "py-3 px-3";
  const activeInput = document.createElement("input");
  activeInput.type = "checkbox";
  activeInput.className = "h-4 w-4";
  activeInput.checked = Boolean(account.is_active);
  activeCell.appendChild(activeInput);
  row.appendChild(activeCell);

  const statusCell = document.createElement("td");
  statusCell.className = "py-3 px-3 text-xs text-gray-500 dark:text-gray-400";
  statusCell.innerHTML = `
    <div>Connected: ${account.connected ? "yes" : "no"}</div>
    <div>Authorized: ${account.authorized ? "yes" : "no"}</div>
  `;
  row.appendChild(statusCell);

  const userCell = document.createElement("td");
  userCell.className = "py-3 px-3 text-xs text-gray-500 dark:text-gray-400";
  const user = account.user || {};
  userCell.textContent = user.username || user.phone || user.id || "--";
  row.appendChild(userCell);

  const sessionCell = document.createElement("td");
  sessionCell.className = "py-3 px-3 text-xs text-gray-500 dark:text-gray-400";
  const session = account.session || {};
  sessionCell.innerHTML = `
    <div>${escapeHtml(session.name || "")}</div>
    <div>${escapeHtml(session.path || "")}</div>
  `;
  row.appendChild(sessionCell);

  const actionCell = document.createElement("td");
  actionCell.className = "py-3 px-3";
  const saveButton = document.createElement("button");
  saveButton.className = "btn primary";
  saveButton.textContent = "Save";
  const rowStatus = document.createElement("div");
  rowStatus.className = "result";
  actionCell.appendChild(saveButton);
  actionCell.appendChild(rowStatus);
  row.appendChild(actionCell);

  saveButton.addEventListener("click", async () => {
    rowStatus.className = "result";
    rowStatus.textContent = "Saving...";
    try {
      await onSave({
        account_id: account.account_id,
        label: labelInput.value.trim(),
        is_active: activeInput.checked,
        rowStatus,
      });
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Save failed";
    }
  });

  return row;
}

async function loadAccounts() {
  const statusEl = document.getElementById("accounts-status");
  const tableBody = document.getElementById("accounts-table-body");
  const emptyState = document.getElementById("accounts-empty");
  setStatus(statusEl, null, "Loading...");
  try {
    const data = await fetchJson("/api/admin/accounts");
    const accounts = data.accounts || [];
    tableBody.innerHTML = "";
    if (accounts.length === 0) {
      emptyState.style.display = "block";
      setStatus(statusEl, true, "No accounts");
      return;
    }
    emptyState.style.display = "none";
    accounts.forEach(account => {
      const row = buildAccountRow(account, async ({ account_id, label, is_active, rowStatus }) => {
        const res = await fetchJson(`/api/admin/accounts/${account_id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ label, is_active })
        });
        rowStatus.className = "result ok";
        rowStatus.textContent = res.account && res.account.is_active ? "Saved" : "Saved (inactive)";
        loadAccounts();
      });
      tableBody.appendChild(row);
    });
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

function parseSettingValue(input, type) {
  if (type === "bool") {
    if (input.value === "") return null;
    return input.value === "true";
  }
  if (type === "int") {
    if (input.value === "") return null;
    const value = Number(input.value);
    if (!Number.isFinite(value)) throw new Error("Invalid number");
    return Math.floor(value);
  }
  const text = String(input.value || "").trim();
  return text === "" ? null : text;
}

function buildSettingRow(setting, onSave, onReset) {
  const row = document.createElement("tr");
  row.className = "border-b border-border-light dark:border-border-dark";

  const keyCell = document.createElement("td");
  keyCell.className = "py-3 px-3 font-semibold";
  keyCell.textContent = setting.key;
  row.appendChild(keyCell);

  const descCell = document.createElement("td");
  descCell.className = "py-3 px-3 text-xs text-gray-500 dark:text-gray-400";
  const restartNote = setting.requires_restart ? " (restart)" : "";
  descCell.textContent = `${setting.description}${restartNote}`;
  row.appendChild(descCell);

  const defaultCell = document.createElement("td");
  defaultCell.className = "py-3 px-3 text-xs text-gray-500 dark:text-gray-400";
  defaultCell.textContent = setting.default_value ?? "--";
  row.appendChild(defaultCell);

  const currentCell = document.createElement("td");
  currentCell.className = "py-3 px-3 text-xs text-gray-500 dark:text-gray-400";
  currentCell.textContent = setting.current_value ?? "--";
  row.appendChild(currentCell);

  const inputCell = document.createElement("td");
  inputCell.className = "py-3 px-3";
  let input;
  if (setting.type === "bool") {
    input = document.createElement("select");
    input.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
    const optionDefault = document.createElement("option");
    optionDefault.value = "";
    optionDefault.textContent = "default";
    input.appendChild(optionDefault);
    const optionTrue = document.createElement("option");
    optionTrue.value = "true";
    optionTrue.textContent = "true";
    input.appendChild(optionTrue);
    const optionFalse = document.createElement("option");
    optionFalse.value = "false";
    optionFalse.textContent = "false";
    input.appendChild(optionFalse);
    if (setting.override_value === true) {
      input.value = "true";
    } else if (setting.override_value === false) {
      input.value = "false";
    } else {
      input.value = "";
    }
  } else {
    input = document.createElement("input");
    input.type = setting.type === "int" ? "number" : "text";
    input.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
    if (setting.override_value !== null && setting.override_value !== undefined) {
      input.value = setting.override_value;
    } else {
      input.value = "";
      input.placeholder = setting.current_value ?? "";
    }
  }
  inputCell.appendChild(input);
  row.appendChild(inputCell);

  const actionCell = document.createElement("td");
  actionCell.className = "py-3 px-3";
  const saveButton = document.createElement("button");
  saveButton.className = "btn primary";
  saveButton.textContent = "Save";
  const resetButton = document.createElement("button");
  resetButton.className = "btn";
  resetButton.textContent = "Reset";
  const rowStatus = document.createElement("div");
  rowStatus.className = "result";
  actionCell.appendChild(saveButton);
  actionCell.appendChild(resetButton);
  actionCell.appendChild(rowStatus);
  row.appendChild(actionCell);

  saveButton.addEventListener("click", async () => {
    rowStatus.className = "result";
    rowStatus.textContent = "Saving...";
    try {
      const value = parseSettingValue(input, setting.type);
      await onSave(setting.key, value);
      rowStatus.className = "result ok";
      rowStatus.textContent = "Saved";
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Save failed";
    }
  });

  resetButton.addEventListener("click", async () => {
    rowStatus.className = "result";
    rowStatus.textContent = "Resetting...";
    try {
      await onReset(setting.key);
      rowStatus.className = "result ok";
      rowStatus.textContent = "Reset";
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Reset failed";
    }
  });

  return row;
}

async function loadLogs() {
  const statusEl = document.getElementById("logs-status");
  const levelInput = document.getElementById("logs-level");
  const searchInput = document.getElementById("logs-search");
  const limitInput = document.getElementById("logs-limit");
  const outputEl = document.getElementById("logs-output");

  setStatus(statusEl, null, "Loading...");
  try {
    const params = new URLSearchParams();
    if (levelInput && levelInput.value) {
      params.set("level", levelInput.value);
    }
    if (searchInput && searchInput.value.trim()) {
      params.set("search", searchInput.value.trim());
    }
    const limitValue = limitInput ? Number(limitInput.value) : 200;
    if (Number.isFinite(limitValue)) {
      params.set("limit", String(Math.min(Math.max(limitValue, 10), 1000)));
    }
    const url = `/api/admin/logs?${params.toString()}`;
    const data = await fetchJson(url);
    const lines = data.lines || [];
    outputEl.textContent = lines.join("\n") || "No log lines.";
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    outputEl.textContent = "Failed to load logs.";
    setStatus(statusEl, false, err.message || "Failed");
  }
}

async function loadAudit() {
  const statusEl = document.getElementById("audit-status");
  const actorInput = document.getElementById("audit-actor");
  const actionInput = document.getElementById("audit-action");
  const limitInput = document.getElementById("audit-limit");
  const tableBody = document.getElementById("audit-table-body");
  const emptyState = document.getElementById("audit-empty");

  setStatus(statusEl, null, "Loading...");
  try {
    const params = new URLSearchParams();
    const actorValue = actorInput ? actorInput.value.trim() : "";
    const actionValue = actionInput ? actionInput.value.trim() : "";
    if (actorValue) params.set("actor", actorValue);
    if (actionValue) params.set("action", actionValue);
    const limitValue = limitInput ? Number(limitInput.value) : 100;
    if (Number.isFinite(limitValue)) {
      params.set("limit", String(Math.min(Math.max(limitValue, 10), 200)));
    }
    const data = await fetchJson(`/api/admin/audit?${params.toString()}`);
    const items = data.audit || [];
    tableBody.innerHTML = "";
    if (items.length === 0) {
      emptyState.style.display = "block";
    } else {
      emptyState.style.display = "none";
      items.forEach(item => {
        const row = document.createElement("tr");
        row.className = "border-b border-border-light dark:border-border-dark";
        row.innerHTML = `
          <td class="py-2 px-3 text-xs">${escapeHtml(item.created_at || "--")}</td>
          <td class="py-2 px-3 text-xs">${escapeHtml(item.actor || "--")} (${escapeHtml(item.role || "--")})</td>
          <td class="py-2 px-3 text-xs">${escapeHtml(item.action || "--")}</td>
          <td class="py-2 px-3 text-xs">${escapeHtml(item.entity_type || "--")} ${escapeHtml(item.entity_id || "")}</td>
          <td class="py-2 px-3 text-[11px] text-gray-500 dark:text-gray-400">${escapeHtml(JSON.stringify(item.data || {}))}</td>
        `;
        tableBody.appendChild(row);
      });
    }
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

async function loadSettings() {
  const statusEl = document.getElementById("settings-status");
  const tableBody = document.getElementById("settings-table-body");
  const emptyState = document.getElementById("settings-empty");
  setStatus(statusEl, null, "Loading...");
  try {
    const data = await fetchJson("/api/admin/settings");
    const settingsList = data.settings || [];
    tableBody.innerHTML = "";
    if (settingsList.length === 0) {
      emptyState.style.display = "block";
      setStatus(statusEl, true, "No settings");
      return;
    }
    emptyState.style.display = "none";

    async function patchSettings(values) {
      const response = await fetchJson("/api/admin/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values })
      });
      if (response.requires_restart) {
        setStatus(
          statusEl,
          true,
          "Updated. Restart required: " + response.restart_keys.join(", ")
        );
      } else {
        setStatus(statusEl, true, "Updated");
      }
      await loadSettings();
    }

    settingsList.forEach(setting => {
      const row = buildSettingRow(
        setting,
        async (key, value) => patchSettings({ [key]: value }),
        async (key) => patchSettings({ [key]: null })
      );
      tableBody.appendChild(row);
    });
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

function buildTemplateRow(template, onSave, onDelete) {
  const row = document.createElement("div");
  row.className = "grid grid-cols-1 md:grid-cols-6 gap-3 p-3 border border-border-light dark:border-border-dark rounded-lg";

  const labelWrap = document.createElement("div");
  labelWrap.className = "md:col-span-2";
  const labelInput = document.createElement("input");
  labelInput.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
  labelInput.value = template.label || "";
  labelWrap.appendChild(labelInput);

  const bodyWrap = document.createElement("div");
  bodyWrap.className = "md:col-span-3";
  const bodyInput = document.createElement("textarea");
  bodyInput.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
  bodyInput.rows = 2;
  bodyInput.value = template.body || "";
  bodyWrap.appendChild(bodyInput);

  const actionWrap = document.createElement("div");
  actionWrap.className = "flex flex-col gap-2";
  const activeLabel = document.createElement("label");
  activeLabel.className = "flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400";
  const activeInput = document.createElement("input");
  activeInput.type = "checkbox";
  activeInput.checked = Boolean(template.is_active);
  activeLabel.appendChild(activeInput);
  activeLabel.appendChild(document.createTextNode("Active"));

  const buttonRow = document.createElement("div");
  buttonRow.className = "flex items-center gap-2";
  const saveButton = document.createElement("button");
  saveButton.className = "btn";
  saveButton.textContent = "Save";
  const deleteButton = document.createElement("button");
  deleteButton.className = "btn";
  deleteButton.textContent = "Delete";
  buttonRow.appendChild(saveButton);
  buttonRow.appendChild(deleteButton);

  const rowStatus = document.createElement("span");
  rowStatus.className = "result";

  actionWrap.appendChild(activeLabel);
  actionWrap.appendChild(buttonRow);
  actionWrap.appendChild(rowStatus);

  row.appendChild(labelWrap);
  row.appendChild(bodyWrap);
  row.appendChild(actionWrap);

  saveButton.addEventListener("click", async () => {
    rowStatus.className = "result";
    rowStatus.textContent = "Saving...";
    try {
      await onSave(template.id, {
        label: labelInput.value,
        body: bodyInput.value,
        is_active: activeInput.checked
      });
      rowStatus.className = "result ok";
      rowStatus.textContent = "Saved";
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Save failed";
    }
  });

  deleteButton.addEventListener("click", async () => {
    if (!confirm("Delete template?")) return;
    rowStatus.className = "result";
    rowStatus.textContent = "Deleting...";
    try {
      await onDelete(template.id);
      rowStatus.className = "result ok";
      rowStatus.textContent = "Deleted";
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Delete failed";
    }
  });

  return row;
}

async function loadTemplates() {
  const statusEl = document.getElementById("templates-status");
  const listEl = document.getElementById("templates-list");
  const emptyEl = document.getElementById("templates-empty");
  if (!listEl) return;

  setStatus(statusEl, null, "Loading...");
  try {
    const data = await fetchJson("/api/admin/templates");
    const templates = data.templates || [];
    listEl.innerHTML = "";
    if (!templates.length) {
      emptyEl.style.display = "block";
    } else {
      emptyEl.style.display = "none";
      templates.forEach(item => {
        const row = buildTemplateRow(
          item,
          async (id, payload) => {
            await fetchJson(`/api/admin/templates/${id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload)
            });
            await loadTemplates();
          },
          async (id) => {
            await fetchJson(`/api/admin/templates/${id}`, { method: "DELETE" });
            await loadTemplates();
          }
        );
        listEl.appendChild(row);
      });
    }
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

async function createTemplate() {
  const statusEl = document.getElementById("templates-status");
  const labelInput = document.getElementById("template-label");
  const bodyInput = document.getElementById("template-body");
  const activeInput = document.getElementById("template-active");
  if (!labelInput || !bodyInput || !activeInput) return;

  const label = labelInput.value.trim();
  const body = bodyInput.value.trim();
  if (!label || !body) {
    setStatus(statusEl, false, "Label and text required");
    return;
  }
  setStatus(statusEl, null, "Saving...");
  try {
    await fetchJson("/api/admin/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label,
        body,
        is_active: activeInput.checked
      })
    });
    labelInput.value = "";
    bodyInput.value = "";
    activeInput.checked = true;
    await loadTemplates();
    setStatus(statusEl, true, "Created");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

function buildTagRow(tag, onSave, onDelete) {
  const row = document.createElement("div");
  row.className = "grid grid-cols-1 md:grid-cols-6 gap-3 p-3 border border-border-light dark:border-border-dark rounded-lg";

  const nameWrap = document.createElement("div");
  nameWrap.className = "md:col-span-2";
  const nameInput = document.createElement("input");
  nameInput.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
  nameInput.value = tag.name || "";
  nameWrap.appendChild(nameInput);

  const descWrap = document.createElement("div");
  descWrap.className = "md:col-span-2";
  const descInput = document.createElement("input");
  descInput.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
  descInput.value = tag.description || "";
  descWrap.appendChild(descInput);

  const colorWrap = document.createElement("div");
  colorWrap.className = "md:col-span-1";
  const colorInput = document.createElement("input");
  colorInput.className = "w-full bg-gray-100 dark:bg-gray-700 border border-gray-200 dark:border-gray-600 rounded-lg px-2 py-1 text-xs";
  colorInput.value = tag.color || "";
  colorWrap.appendChild(colorInput);

  const actionWrap = document.createElement("div");
  actionWrap.className = "flex flex-col gap-2";
  const activeLabel = document.createElement("label");
  activeLabel.className = "flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400";
  const activeInput = document.createElement("input");
  activeInput.type = "checkbox";
  activeInput.checked = Boolean(tag.is_active);
  activeLabel.appendChild(activeInput);
  activeLabel.appendChild(document.createTextNode("Active"));

  const buttonRow = document.createElement("div");
  buttonRow.className = "flex items-center gap-2";
  const saveButton = document.createElement("button");
  saveButton.className = "btn";
  saveButton.textContent = "Save";
  const deleteButton = document.createElement("button");
  deleteButton.className = "btn";
  deleteButton.textContent = "Delete";
  buttonRow.appendChild(saveButton);
  buttonRow.appendChild(deleteButton);

  const rowStatus = document.createElement("span");
  rowStatus.className = "result";

  actionWrap.appendChild(activeLabel);
  actionWrap.appendChild(buttonRow);
  actionWrap.appendChild(rowStatus);

  row.appendChild(nameWrap);
  row.appendChild(descWrap);
  row.appendChild(colorWrap);
  row.appendChild(actionWrap);

  saveButton.addEventListener("click", async () => {
    rowStatus.className = "result";
    rowStatus.textContent = "Saving...";
    try {
      await onSave(tag.id, {
        name: nameInput.value,
        description: descInput.value,
        color: colorInput.value,
        is_active: activeInput.checked
      });
      rowStatus.className = "result ok";
      rowStatus.textContent = "Saved";
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Save failed";
    }
  });

  deleteButton.addEventListener("click", async () => {
    if (!confirm("Delete tag?")) return;
    rowStatus.className = "result";
    rowStatus.textContent = "Deleting...";
    try {
      await onDelete(tag.id);
      rowStatus.className = "result ok";
      rowStatus.textContent = "Deleted";
    } catch (err) {
      rowStatus.className = "result err";
      rowStatus.textContent = err.message || "Delete failed";
    }
  });

  return row;
}

async function loadTags() {
  const statusEl = document.getElementById("tags-status");
  const listEl = document.getElementById("tags-list");
  const emptyEl = document.getElementById("tags-empty");
  if (!listEl) return;

  setStatus(statusEl, null, "Loading...");
  try {
    const data = await fetchJson("/api/admin/tags");
    const tags = data.tags || [];
    listEl.innerHTML = "";
    if (!tags.length) {
      emptyEl.style.display = "block";
    } else {
      emptyEl.style.display = "none";
      tags.forEach(item => {
        const row = buildTagRow(
          item,
          async (id, payload) => {
            await fetchJson(`/api/admin/tags/${id}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload)
            });
            await loadTags();
          },
          async (id) => {
            await fetchJson(`/api/admin/tags/${id}`, { method: "DELETE" });
            await loadTags();
          }
        );
        listEl.appendChild(row);
      });
    }
    setStatus(statusEl, true, "Updated");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

async function createTag() {
  const statusEl = document.getElementById("tags-status");
  const nameInput = document.getElementById("tag-name");
  const descInput = document.getElementById("tag-description");
  const colorInput = document.getElementById("tag-color");
  const activeInput = document.getElementById("tag-active");
  if (!nameInput || !descInput || !colorInput || !activeInput) return;

  const name = nameInput.value.trim();
  if (!name) {
    setStatus(statusEl, false, "Name required");
    return;
  }
  setStatus(statusEl, null, "Saving...");
  try {
    await fetchJson("/api/admin/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        description: descInput.value.trim(),
        color: colorInput.value.trim(),
        is_active: activeInput.checked
      })
    });
    nameInput.value = "";
    descInput.value = "";
    colorInput.value = "";
    activeInput.checked = true;
    await loadTags();
    setStatus(statusEl, true, "Created");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

async function loadAmoCRMStatus() {
  const statusEl = document.getElementById("amocrm-status");
  const domainEl = document.getElementById("amocrm-domain");
  const redirectEl = document.getElementById("amocrm-redirect");
  const expiresEl = document.getElementById("amocrm-expires");
  const hintEl = document.getElementById("amocrm-config-hint");
  const connectBtn = document.getElementById("btn-amocrm-connect");

  if (!statusEl) return;

  setStatus(statusEl, null, "Loading...");
  try {
    const data = await fetchJson("/api/admin/amocrm/status");
    domainEl.textContent = data.domain || "--";
    redirectEl.textContent = data.redirect_uri || "--";
    expiresEl.textContent = data.token_expires_at || "--";
    if (!data.configured) {
      hintEl.textContent = "AmoCRM config missing. Проверьте AMOCRM_DOMAIN/CLIENT_ID/CLIENT_SECRET/REDIRECT_URI.";
      if (connectBtn) connectBtn.disabled = true;
      setStatus(statusEl, false, "Not configured");
    } else if (!data.has_tokens) {
      hintEl.textContent = "Нет токенов. Нажмите Connect AmoCRM.";
      if (connectBtn) connectBtn.disabled = false;
      setStatus(statusEl, false, "Not authorized");
    } else {
      hintEl.textContent = "Токены сохранены.";
      if (connectBtn) connectBtn.disabled = false;
      setStatus(statusEl, true, "Authorized");
    }
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

async function connectAmoCRM() {
  const statusEl = document.getElementById("amocrm-status");
  setStatus(statusEl, null, "Redirecting...");
  try {
    const data = await fetchJson("/api/admin/amocrm/oauth/url");
    if (data.url) {
      window.location.href = data.url;
      return;
    }
    setStatus(statusEl, false, "Missing OAuth URL");
  } catch (err) {
    setStatus(statusEl, false, err.message || "Failed");
  }
}

const refreshButton = document.getElementById("btn-refresh");
if (refreshButton) {
  refreshButton.addEventListener("click", () => {
    if (page === "dashboard") loadSummary();
    if (page === "accounts") loadAccounts();
    if (page === "settings") loadSettings();
    if (page === "logs") {
      loadLogs();
      loadAudit();
    }
  });
}

if (page === "dashboard") {
  loadSummary();
}
if (page === "accounts") {
  loadAccounts();
}
if (page === "settings") {
  loadSettings();
  loadAmoCRMStatus();
  loadTemplates();
  loadTags();
  const connectBtn = document.getElementById("btn-amocrm-connect");
  if (connectBtn) {
    connectBtn.addEventListener("click", connectAmoCRM);
  }
  const templateBtn = document.getElementById("btn-template-create");
  if (templateBtn) {
    templateBtn.addEventListener("click", createTemplate);
  }
  const tagBtn = document.getElementById("btn-tag-create");
  if (tagBtn) {
    tagBtn.addEventListener("click", createTag);
  }
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("amocrm") === "success") {
    setStatus(document.getElementById("amocrm-status"), true, "Authorized");
  } else if (urlParams.get("amocrm") === "error") {
    setStatus(document.getElementById("amocrm-status"), false, "OAuth failed");
  }
}
if (page === "logs") {
  const refreshLogs = document.getElementById("btn-refresh-logs");
  const refreshAudit = document.getElementById("btn-refresh-audit");
  if (refreshLogs) refreshLogs.addEventListener("click", loadLogs);
  if (refreshAudit) refreshAudit.addEventListener("click", loadAudit);
  loadLogs();
  loadAudit();
}
