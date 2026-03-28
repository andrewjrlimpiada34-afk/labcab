const API_BASE = window.API_BASE || "http://127.0.0.1:5000/api";
let accessToken = null;
let currentUser = null;
let pollInterval = null;

const authSection = document.getElementById("authSection");
const appSection = document.getElementById("appSection");
const adminSection = document.getElementById("adminSection");
const borrowerSection = document.getElementById("borrowerSection");
const userInfo = document.getElementById("userInfo");
const logoutBtn = document.getElementById("logoutBtn");
const toast = document.getElementById("toast");

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2800);
}

function setAuth(user, token) {
  currentUser = user;
  accessToken = token;
  if (user) {
    authSection.classList.add("hidden");
    appSection.classList.remove("hidden");
    logoutBtn.hidden = false;
    userInfo.textContent = `${user.name} (${user.role})`;
    adminSection.classList.toggle("hidden", user.role !== "admin");
    borrowerSection.classList.toggle("hidden", user.role !== "borrower");
    startPolling();
  } else {
    authSection.classList.remove("hidden");
    appSection.classList.add("hidden");
    logoutBtn.hidden = true;
    userInfo.textContent = "";
    stopPolling();
  }
}

function apiHeaders() {
  const headers = { "Content-Type": "application/json" };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  return headers;
}

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function apiSend(path, method, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: apiHeaders(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.tab;
      document.getElementById("loginTab").classList.toggle("hidden", target !== "login");
      document.getElementById("registerTab").classList.toggle("hidden", target !== "register");
    });
  });
}

async function handleLogin(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  const payload = Object.fromEntries(formData.entries());
  try {
    const data = await apiSend("/auth/login", "POST", payload);
    setAuth(data.user, data.access_token);
    showToast("Logged in successfully");
    await loadAll();
  } catch (err) {
    showToast("Login failed");
  }
}

async function handleRegister(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  const payload = Object.fromEntries(formData.entries());
  try {
    await apiSend("/auth/register", "POST", payload);
    showToast("Registration complete. Please login.");
  } catch (err) {
    showToast("Registration failed");
  }
}

async function loadApparatus() {
  const apparatus = await apiGet("/apparatus");
  const grid = document.getElementById("apparatusGrid");
  const select = document.getElementById("apparatusSelect");
  grid.innerHTML = "";
  select.innerHTML = "";
  apparatus.forEach((item) => {
    const card = document.createElement("div");
    card.className = "apparatus-card";
    card.innerHTML = `
      <div>
        <strong>${item.name}</strong>
        <div class="muted">Available: ${item.available_quantity} / ${item.total_quantity}</div>
      </div>
      <span class="badge ${item.status}">${badgeLabel(item.status)}</span>
    `;
    grid.appendChild(card);

    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = `${item.name} (Available ${item.available_quantity})`;
    select.appendChild(option);
  });
}

function badgeLabel(status) {
  if (status === "low_stock") return "Low Stock";
  if (status === "in_use") return "In Use";
  return "Available";
}

function statusBadge(status) {
  let cls = "available";
  if (status === "Overdue") cls = "in_use";
  if (status === "Borrowed") cls = "low_stock";
  if (status === "Pending") cls = "low_stock";
  if (status === "Rejected") cls = "in_use";
  return `<span class=\"badge ${cls}\">${status}</span>`;
}

async function handleBorrow(event) {
  event.preventDefault();
  const apparatusId = document.getElementById("apparatusSelect").value;
  const quantity = document.getElementById("borrowQuantity").value;
  const dueDate = document.getElementById("borrowDueDate").value;
  if (!confirm("Submit this borrow request?")) {
    return;
  }
  try {
    await apiSend("/borrow-requests", "POST", {
      apparatus_id: apparatusId,
      quantity: Number(quantity),
      due_date: dueDate,
    });
    showToast("Borrow request submitted");
    await loadAll();
  } catch (err) {
    showToast("Borrow request failed");
  }
}

async function loadSummary() {
  const summary = await apiGet("/dashboard/summary");
  const container = document.getElementById("summaryCards");
  const items = [
    { label: "Total apparatus", value: summary.total_apparatus },
    { label: "Total borrowed", value: summary.total_borrowed },
    { label: "Overdue items", value: summary.overdue_items },
    { label: "Available inventory", value: summary.available_inventory },
  ];
  container.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `<h3>${item.label}</h3><div class="stat">${item.value}</div>`;
    container.appendChild(card);
  });
}

async function loadAdminRecords() {
  const borrowerFilter = document.getElementById("filterBorrower").value;
  const apparatusFilter = document.getElementById("filterApparatus").value;
  const params = new URLSearchParams();
  if (borrowerFilter) params.append("borrower", borrowerFilter);
  if (apparatusFilter) params.append("apparatus", apparatusFilter);

  const records = await apiGet(`/borrow-records?${params.toString()}`);
  const requestTable = document.getElementById("adminBorrowTable");
  const returnTable = document.getElementById("adminReturnTable");
  requestTable.innerHTML = "";
  returnTable.innerHTML = "";

  records.forEach((record) => {
    if (record.status === "Pending") {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${record.user_name}</td>
        <td>${record.apparatus_name}</td>
        <td>${record.quantity}</td>
        <td>${record.due_date}</td>
        <td>${statusBadge(record.status)}</td>
        <td>
          <button class="btn ghost" data-action="approve" data-id="${record.id}">Approve</button>
          <button class="btn ghost" data-action="reject" data-id="${record.id}">Reject</button>
        </td>
      `;
      requestTable.appendChild(row);
    }

    if (["Borrowed", "Overdue"].includes(record.status)) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${record.user_name}</td>
        <td>${record.apparatus_name}</td>
        <td>${record.quantity}</td>
        <td>${statusBadge(record.status)}</td>
        <td>
          <button class="btn ghost" data-action="return" data-id="${record.id}">Mark Returned</button>
        </td>
      `;
      returnTable.appendChild(row);
    }
  });

  requestTable.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => handleAdminAction(btn.dataset.id, btn.dataset.action));
  });

  returnTable.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => handleAdminReturn(btn.dataset.id));
  });
}

async function handleAdminAction(recordId, action) {
  const promptText = action === "approve" ? "Approve this request?" : "Reject this request?";
  if (!confirm(promptText)) {
    return;
  }
  try {
    await apiSend(`/borrow-requests/${recordId}`, "PATCH", { action });
    showToast(`Request ${action}d`);
    await loadAll();
  } catch (err) {
    showToast("Action failed");
  }
}

async function handleAdminReturn(recordId) {
  if (!confirm("Mark this item as returned?")) {
    return;
  }
  try {
    await apiSend(`/borrow-records/${recordId}/return`, "PATCH", {});
    showToast("Item marked returned");
    await loadAll();
  } catch (err) {
    showToast("Return failed");
  }
}

async function loadBorrowerHistory() {
  const records = await apiGet("/borrow-records/me");
  const table = document.getElementById("myHistoryTable");
  table.innerHTML = "";
  records.forEach((record) => {
    const row = document.createElement("tr");
    const receiptButton = ["Borrowed", "Returned", "Overdue"].includes(record.status)
      ? `<button class="btn ghost" data-receipt="${record.id}">Download</button>`
      : "-";
    row.innerHTML = `
      <td>${record.apparatus_name}</td>
      <td>${record.quantity}</td>
      <td>${record.borrow_date ? record.borrow_date.substring(0, 10) : "-"}</td>
      <td>${record.due_date}</td>
      <td>${statusBadge(record.status)}</td>
      <td>${receiptButton}</td>
    `;
    table.appendChild(row);
  });

  table.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => downloadReceipt(btn.dataset.receipt));
  });
}

async function downloadReceipt(recordId) {
  try {
    const res = await fetch(`${API_BASE}/borrow-records/${recordId}/receipt`, {
      headers: apiHeaders(),
    });
    if (!res.ok) throw new Error("Receipt error");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `receipt_${recordId}.pdf`;
    link.click();
    window.URL.revokeObjectURL(url);
  } catch (err) {
    showToast("Receipt unavailable");
  }
}

async function loadNotifications() {
  const notes = await apiGet("/notifications");
  const list = document.getElementById("notificationList");
  list.innerHTML = "";
  notes.forEach((note) => {
    const item = document.createElement("div");
    item.className = `notification ${note.status}`;
    item.innerHTML = `
      <div>${note.message}</div>
      <div class="muted">${note.date.substring(0, 10)}</div>
    `;
    item.addEventListener("click", async () => {
      if (note.status === "unread") {
        await apiSend(`/notifications/${note.id}/read`, "PATCH", {});
        await loadNotifications();
      }
    });
    list.appendChild(item);
  });
}

async function loadAll() {
  await loadApparatus();
  if (currentUser?.role === "admin") {
    await loadSummary();
    await loadAdminRecords();
  }
  if (currentUser?.role === "borrower") {
    await loadBorrowerHistory();
  }
  await loadNotifications();
}

function startPolling() {
  stopPolling();
  loadAll();
  pollInterval = setInterval(loadAll, 15000);
}

function stopPolling() {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = null;
}

logoutBtn.addEventListener("click", () => setAuth(null, null));

setupTabs();

const loginForm = document.getElementById("loginForm");
const registerForm = document.getElementById("registerForm");
const borrowForm = document.getElementById("borrowForm");

loginForm.addEventListener("submit", handleLogin);
registerForm.addEventListener("submit", handleRegister);
borrowForm.addEventListener("submit", handleBorrow);

const applyFilters = document.getElementById("applyFilters");
applyFilters.addEventListener("click", loadAdminRecords);

setAuth(null, null);
