/**
 * BizSuite API client
 */
const API = {
  base: (window.BIZSUITE_CONFIG?.API_BASE || "").replace(/\/+$/, ""),

  getToken() {
    return localStorage.getItem("bizsuite_token");
  },

  setToken(token) {
    if (token) localStorage.setItem("bizsuite_token", token);
    else localStorage.removeItem("bizsuite_token");
  },

  async request(method, path, body = null, isForm = false) {
    const headers = {};
    const token = this.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (body && !isForm) headers["Content-Type"] = "application/json";

    const opts = { method, headers };
    if (body) {
      opts.body = isForm ? body : JSON.stringify(body);
    }

    let res;
    try {
      res = await fetch(this.base + path, opts);
    } catch (error) {
      throw new Error(`Cannot reach BizSuite API at ${this.base || window.location.origin}. Check the Render service URL and network/CORS settings.`);
    }
    if (res.status === 401) {
      this.setToken(null);
      if (!window.location.pathname.includes("login")) {
        window.location.href = "/login";
      }
      throw new Error("Unauthorized");
    }

    let data = null;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      data = await res.json();
    } else if (res.ok) {
      return res;
    }

    if (!res.ok) {
      const detail = data?.detail || res.statusText || "Request failed";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  },

  get(path) { return this.request("GET", path); },
  post(path, body) { return this.request("POST", path, body); },
  patch(path, body) { return this.request("PATCH", path, body); },
  put(path, body) { return this.request("PUT", path, body); },
  del(path) { return this.request("DELETE", path); },

  async login(email, password) {
    const form = new URLSearchParams();
    form.append("username", email);
    form.append("password", password);
    let res;
    try {
      res = await fetch(this.base + "/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form,
      });
    } catch (error) {
      throw new Error(`Cannot reach BizSuite API at ${this.base || window.location.origin}. Check the Render service URL and network/CORS settings.`);
    }
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed");
    this.setToken(data.access_token);
    return data;
  },

  logout() {
    this.setToken(null);
    window.location.href = "/login";
  },

  me() { return this.get("/api/auth/me"); },
};

// Toast helper
function toast(message, type = "info") {
  let box = document.querySelector(".toast-container");
  if (!box) {
    box = document.createElement("div");
    box.className = "toast-container";
    document.body.appendChild(box);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function formatDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatDateTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function statusBadge(status) {
  const s = (status || "").toLowerCase().replace(/ /g, "_");
  return `<span class="badge badge-${s}">${(status || "").replace(/_/g, " ")}</span>`;
}

function priorityBadge(p) {
  const s = (p || "normal").toLowerCase();
  return `<span class="badge badge-${s}">${p}</span>`;
}

function roleBadge(role) {
  return `<span class="badge badge-${role}">${role}</span>`;
}

function requireAuth() {
  if (!API.getToken()) {
    window.location.href = "/login";
    return false;
  }
  return true;
}

async function loadCurrentUser() {
  try {
    const user = await API.me();
    window.currentUser = user;
    const chip = document.getElementById("userChip");
    if (chip) {
      const initials = (user.name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
      chip.innerHTML = `
        <div class="user-avatar">${initials}</div>
        <span>${user.name} · ${user.role}</span>
      `;
    }
    return user;
  } catch (e) {
    API.logout();
    return null;
  }
}

function toggleSidebar() {
  document.getElementById("sidebar")?.classList.toggle("open");
  document.getElementById("overlay")?.classList.toggle("open");
}