const state = {
  token: localStorage.getItem("authToken"),
  user: null,
  orders: [],
  vendors: [],
  vendorUsers: [],
  activeSection: "dashboard-section",
};

const nextStatuses = {
  ASSIGNED: ["PICKED_UP"],
  PICKED_UP: ["CLEANING"],
  CLEANING: ["READY"],
  READY: ["OUT_FOR_DELIVERY"],
  OUT_FOR_DELIVERY: ["DELIVERED"],
};

const elements = {
  phoneInput: document.getElementById("phone-input"),
  otpInput: document.getElementById("otp-input"),
  nameInput: document.getElementById("name-input"),
  authMessage: document.getElementById("auth-message"),
  requestOtpBtn: document.getElementById("request-otp-btn"),
  verifyOtpBtn: document.getElementById("verify-otp-btn"),
  logoutBtn: document.getElementById("logout-btn"),
  breadcrumb: document.getElementById("breadcrumb-current"),
  topUserSummary: document.getElementById("top-user-summary"),
  vendorForm: document.getElementById("vendor-form"),
  vendorUserForm: document.getElementById("vendor-user-form"),
  vendorUserSelect: document.getElementById("vendor-user-select"),
  vendorsTableBody: document.getElementById("vendors-table-body"),
  vendorUsersTableBody: document.getElementById("vendor-users-table-body"),
  ordersTableBody: document.getElementById("orders-table-body"),
  orderDetailTitle: document.getElementById("orderDetailTitle"),
  orderDetailContent: document.getElementById("order-detail-content"),
  orderDetailActions: document.getElementById("order-detail-actions"),
  ordersSubtitle: document.getElementById("orders-subtitle"),
};

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = "Bir hata olustu";
    try {
      const data = await response.json();
      detail = data.detail || data.message || detail;
    } catch (_) {}
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function setAuthMessage(message, variant = "info") {
  elements.authMessage.className = `alert alert-${variant} mt-3 mb-0`;
  elements.authMessage.textContent = message;
}

function setActiveSection(sectionId) {
  state.activeSection = sectionId;
  document.querySelectorAll(".app-section").forEach((section) => {
    section.classList.toggle("d-none", section.id !== sectionId);
  });
  document.querySelectorAll(".app-nav-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.target === sectionId);
  });
  const activeLink = document.querySelector(`.app-nav-link[data-target="${sectionId}"] .nav-link-text`);
  elements.breadcrumb.textContent = activeLink ? activeLink.textContent : "Panel";
}

function applyRoleVisibility() {
  const role = state.user?.role || null;
  document.querySelectorAll(".admin-only").forEach((node) => {
    node.classList.toggle("hidden-by-role", role !== "admin");
  });
  document.querySelectorAll(".vendor-only").forEach((node) => {
    node.classList.toggle("hidden-by-role", role !== "vendor");
  });
}

function updateTopbar() {
  if (!state.user) {
    elements.topUserSummary.textContent = "Oturum yok";
    return;
  }
  elements.topUserSummary.textContent = `${state.user.full_name} | ${state.user.role.toUpperCase()} | ${state.user.phone_number}`;
}

function updateMetric(id, text) {
  const node = document.getElementById(id);
  if (node) {
    node.textContent = text;
  }
}

function statusBadge(status) {
  const palette = {
    ASSIGNED: "warning",
    PICKED_UP: "info",
    CLEANING: "primary",
    READY: "secondary",
    OUT_FOR_DELIVERY: "dark",
    DELIVERED: "success",
    REJECTED: "danger",
  };
  return `<span class="badge badge-${palette[status] || "light"} status-badge">${status}</span>`;
}

function renderVendors() {
  if (!elements.vendorsTableBody) {
    return;
  }
  elements.vendorsTableBody.innerHTML = state.vendors.length
    ? state.vendors
        .map(
          (vendor) => `
            <tr>
              <td>${vendor.name}<div class="small text-muted">${vendor.tenant_id}</div></td>
              <td>${vendor.phone_number}</td>
              <td>${vendor.address_line}</td>
              <td>${vendor.is_active ? '<span class="badge badge-success">Aktif</span>' : '<span class="badge badge-secondary">Pasif</span>'}</td>
            </tr>
          `
        )
        .join("")
    : `<tr><td colspan="4" class="text-center text-muted py-4">Vendor bulunamadi.</td></tr>`;

  if (elements.vendorUserSelect) {
    elements.vendorUserSelect.innerHTML = state.vendors
      .map((vendor) => `<option value="${vendor.id}">${vendor.name}</option>`)
      .join("");
  }
}

function renderVendorUsers() {
  if (!elements.vendorUsersTableBody) {
    return;
  }
  elements.vendorUsersTableBody.innerHTML = state.vendorUsers.length
    ? state.vendorUsers
        .map(
          (user) => `
            <tr>
              <td>${user.full_name}</td>
              <td>${user.phone_number}</td>
              <td>${user.vendor_id ?? "-"}</td>
            </tr>
          `
        )
        .join("")
    : `<tr><td colspan="3" class="text-center text-muted py-4">Operator bulunamadi.</td></tr>`;
}

function renderOrders() {
  const isVendor = state.user?.role === "vendor";
  elements.ordersSubtitle.textContent = isVendor ? "Vendor siparisleri" : "Tum siparisler";
  elements.ordersTableBody.innerHTML = state.orders.length
    ? state.orders
        .map(
          (order) => `
            <tr>
              <td>#${order.id}</td>
              <td>${order.user.full_name}</td>
              <td>${order.vendor ? order.vendor.name : "-"}</td>
              <td>${order.address.district} / ${order.address.city}</td>
              <td>${statusBadge(order.status)}</td>
              <td>${order.total_price} TL</td>
              <td><button class="btn btn-sm btn-outline-primary" data-order-detail="${order.id}">Ac</button></td>
              <td>${orderActionButtons(order)}</td>
            </tr>
          `
        )
        .join("")
    : `<tr><td colspan="8" class="text-center text-muted py-4">Siparis bulunamadi.</td></tr>`;
}

function orderActionButtons(order) {
  if (state.user?.role !== "vendor") {
    return '<span class="text-muted small">Izleme</span>';
  }

  const actions = [];
  if (order.status === "ASSIGNED") {
    actions.push(`<button class="btn btn-sm btn-success mr-1" data-action="accept" data-order-id="${order.id}">Kabul</button>`);
    actions.push(`<button class="btn btn-sm btn-outline-danger mr-1" data-action="reject" data-order-id="${order.id}">Reddet</button>`);
  }

  (nextStatuses[order.status] || []).forEach((status) => {
    actions.push(
      `<button class="btn btn-sm btn-primary mr-1" data-action="status" data-order-id="${order.id}" data-status="${status}">${status.replaceAll("_", " ")}</button>`
    );
  });

  return actions.length ? actions.join("") : '<span class="text-success small">Tamamlandi</span>';
}

function renderOrderModal(order) {
  elements.orderDetailTitle.textContent = `Siparis #${order.id}`;
  elements.orderDetailContent.innerHTML = `
    <div class="row">
      <div class="col-md-6">
        <h6>Musteri</h6>
        <p>${order.user.full_name}<br>${order.user.phone_number}</p>
      </div>
      <div class="col-md-6">
        <h6>Vendor</h6>
        <p>${order.vendor ? `${order.vendor.name}<br>${order.vendor.phone_number}` : "-"}</p>
      </div>
    </div>
    <h6>Adres</h6>
    <p>${order.address.line_1}, ${order.address.district} / ${order.address.city}</p>
    <h6>Kalemler</h6>
    <ul class="order-detail-list">
      ${order.items.map((item) => `<li>${item.quantity}x ${item.item_type} - ${item.total_price} TL</li>`).join("")}
    </ul>
    <p class="mb-1"><strong>Durum:</strong> ${order.status}</p>
    <p class="mb-1"><strong>Toplam:</strong> ${order.total_price} TL</p>
    <p class="mb-0"><strong>Not:</strong> ${order.notes || "-"}</p>
  `;

  elements.orderDetailActions.innerHTML = "";
  if (state.user?.role === "vendor") {
    if (order.status === "ASSIGNED") {
      elements.orderDetailActions.innerHTML += `<button type="button" class="btn btn-success" data-action="accept" data-order-id="${order.id}">Kabul et</button>`;
      elements.orderDetailActions.innerHTML += `<button type="button" class="btn btn-outline-danger ml-2" data-action="reject" data-order-id="${order.id}">Reddet</button>`;
    }
    (nextStatuses[order.status] || []).forEach((status) => {
      elements.orderDetailActions.innerHTML += `<button type="button" class="btn btn-primary ml-2" data-action="status" data-order-id="${order.id}" data-status="${status}">${status.replaceAll("_", " ")}</button>`;
    });
  }
}

async function requestOtp() {
  try {
    const response = await api("/api/v1/auth/otp/request", {
      method: "POST",
      body: JSON.stringify({ phone_number: elements.phoneInput.value.trim() }),
    });
    const otp = response.message.match(/(\d{6})/)?.[1] || "";
    elements.otpInput.value = otp;
    setAuthMessage(`OTP hazirlandi. Kod: ${otp}`, "info");
  } catch (error) {
    setAuthMessage(error.message, "danger");
  }
}

async function verifyOtp() {
  try {
    const response = await api("/api/v1/auth/otp/verify", {
      method: "POST",
      body: JSON.stringify({
        phone_number: elements.phoneInput.value.trim(),
        otp_code: elements.otpInput.value.trim(),
        full_name: elements.nameInput.value.trim() || null,
      }),
    });
    state.token = response.access_token;
    localStorage.setItem("authToken", state.token);
    await loadCurrentUser();
    setAuthMessage("Oturum acildi.", "success");
    setActiveSection("dashboard-section");
  } catch (error) {
    setAuthMessage(error.message, "danger");
  }
}

async function loadCurrentUser() {
  try {
    state.user = await api("/api/v1/users/me");
    updateTopbar();
    applyRoleVisibility();
    await loadPanelData();
  } catch (error) {
    localStorage.removeItem("authToken");
    state.token = null;
    state.user = null;
    updateTopbar();
    applyRoleVisibility();
    setActiveSection("login-section");
    setAuthMessage("Oturum acin.", "info");
  }
}

async function loadPanelData() {
  if (!state.user) {
    return;
  }

  if (state.user.role === "admin") {
    const [summary, vendorSummary, orders, vendors, vendorUsers] = await Promise.all([
      api("/api/v1/admin/summary"),
      api("/api/v1/admin/vendors/summary"),
      api("/api/v1/admin/orders"),
      api("/api/v1/admin/vendors"),
      api("/api/v1/admin/vendor-users"),
    ]);

    state.orders = orders;
    state.vendors = vendors;
    state.vendorUsers = vendorUsers;
    updateMetric("metric-total-orders", `${summary.total_orders} Toplam Siparis`);
    updateMetric("metric-assigned-orders", `${summary.assigned_orders} Atanmis Siparis`);
    updateMetric("metric-progress-orders", `${summary.in_progress_orders} Aktif Surec`);
    updateMetric("metric-delivered-orders", `${summary.delivered_orders} Teslim Edildi`);
    updateMetric("metric-total-vendors", vendorSummary.total_vendors);
    updateMetric("metric-active-vendors", vendorSummary.active_vendors);
    renderVendors();
    renderVendorUsers();
    renderOrders();
    return;
  }

  if (state.user.role === "vendor") {
    const orders = await api("/api/v1/vendor-panel/orders");
    state.orders = orders;
    state.vendors = [];
    state.vendorUsers = [];
    updateMetric("metric-total-orders", `${orders.length} Toplam Siparis`);
    updateMetric("metric-assigned-orders", `${orders.filter((item) => item.status === "ASSIGNED").length} Atanmis Siparis`);
    updateMetric("metric-progress-orders", `${orders.filter((item) => item.status !== "ASSIGNED" && item.status !== "DELIVERED").length} Aktif Surec`);
    updateMetric("metric-delivered-orders", `${orders.filter((item) => item.status === "DELIVERED").length} Teslim Edildi`);
    renderOrders();
  }
}

async function handleVendorCreate(event) {
  event.preventDefault();
  try {
    const formData = new FormData(elements.vendorForm);
    const payload = Object.fromEntries(formData.entries());
    payload.latitude = Number(payload.latitude);
    payload.longitude = Number(payload.longitude);
    await api("/api/v1/vendors", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    elements.vendorForm.reset();
    await loadPanelData();
  } catch (error) {
    alert(error.message);
  }
}

async function handleVendorUserCreate(event) {
  event.preventDefault();
  try {
    const formData = new FormData(elements.vendorUserForm);
    const payload = Object.fromEntries(formData.entries());
    payload.vendor_id = Number(payload.vendor_id);
    await api("/api/v1/admin/vendor-users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    elements.vendorUserForm.reset();
    await loadPanelData();
  } catch (error) {
    alert(error.message);
  }
}

async function handleOrderAction(action, orderId, status = null) {
  if (action === "accept") {
    await api(`/api/v1/vendor-panel/orders/${orderId}/accept`, { method: "POST" });
  } else if (action === "reject") {
    await api(`/api/v1/vendor-panel/orders/${orderId}/status`, {
      method: "POST",
      body: JSON.stringify({ status: "REJECTED" }),
    });
  } else if (action === "status" && status) {
    await api(`/api/v1/vendor-panel/orders/${orderId}/status`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  }
  await loadPanelData();
}

function logout(event) {
  if (event) {
    event.preventDefault();
  }
  localStorage.removeItem("authToken");
  state.token = null;
  state.user = null;
  state.orders = [];
  updateTopbar();
  applyRoleVisibility();
  renderOrders();
  setActiveSection("login-section");
  setAuthMessage("Oturum kapatildi.", "secondary");
}

document.querySelectorAll(".app-nav-link").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    const target = link.dataset.target;
    if ((target === "vendors-section" || target === "operators-section") && state.user?.role !== "admin") {
      return;
    }
    setActiveSection(target);
  });
});

document.getElementById("sidenavToggler").addEventListener("click", (event) => {
  event.preventDefault();
  document.body.classList.toggle("sidenav-toggled");
});

elements.requestOtpBtn.addEventListener("click", requestOtp);
elements.verifyOtpBtn.addEventListener("click", verifyOtp);
elements.logoutBtn.addEventListener("click", logout);
if (elements.vendorForm) {
  elements.vendorForm.addEventListener("submit", handleVendorCreate);
}
if (elements.vendorUserForm) {
  elements.vendorUserForm.addEventListener("submit", handleVendorUserCreate);
}

document.body.addEventListener("click", async (event) => {
  const detailButton = event.target.closest("[data-order-detail]");
  if (detailButton) {
    const order = state.orders.find((item) => item.id === Number(detailButton.dataset.orderDetail));
    if (order) {
      renderOrderModal(order);
      window.jQuery("#orderDetailModal").modal("show");
    }
    return;
  }

  const actionButton = event.target.closest("[data-action]");
  if (actionButton) {
    try {
      await handleOrderAction(
        actionButton.dataset.action,
        Number(actionButton.dataset.orderId),
        actionButton.dataset.status || null
      );
      const order = state.orders.find((item) => item.id === Number(actionButton.dataset.orderId));
      if (order && window.jQuery("#orderDetailModal").hasClass("show")) {
        renderOrderModal(order);
      }
    } catch (error) {
      alert(error.message);
    }
  }
});

document.addEventListener("scroll", () => {
  const scrollButton = document.querySelector(".scroll-to-top");
  if (window.scrollY > 100) {
    scrollButton.style.display = "block";
  } else {
    scrollButton.style.display = "none";
  }
});

if (state.token) {
  loadCurrentUser().then(() => setActiveSection("dashboard-section"));
} else {
  setActiveSection("login-section");
  applyRoleVisibility();
  updateTopbar();
}
