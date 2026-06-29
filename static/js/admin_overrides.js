// CRUD d'overrides de data planificada de càrrega (admin only)
(() => {
"use strict";

const $ = (s, r = document) => r.querySelector(s);
const fmtDate = new Intl.DateTimeFormat("ca-ES", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function getCsrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
}

async function fetchJ(url, opts = {}) {
    const method = (opts.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
        const tok = getCsrf();
        if (tok) {
            const h = new Headers(opts.headers || {});
            if (!h.has("X-CSRF-Token")) h.set("X-CSRF-Token", tok);
            opts = { ...opts, headers: h };
        }
    }
    const r = await fetch(url, opts);
    if (!r.ok) {
        let err = `HTTP ${r.status}`;
        try { const j = await r.json(); if (j.error) err = j.error; } catch {}
        const e = new Error(err);
        e.status = r.status;
        throw e;
    }
    return r.json();
}

function toast(type, msg) {
    const wrap = $("#toasts");
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.innerHTML = `<span class="toast-body">${escapeHtml(msg)}</span><button class="toast-close" aria-label="Tanca">×</button>`;
    wrap.appendChild(t);
    const dismiss = () => { t.classList.add("is-leaving"); setTimeout(() => t.remove(), 220); };
    t.querySelector(".toast-close").addEventListener("click", dismiss);
    setTimeout(dismiss, type === "error" ? 8000 : 4000);
}

const state = { overrides: [] };

function fmtTs(iso) {
    if (!iso) return "—";
    try { return fmtDate.format(new Date(iso)); } catch { return iso; }
}

function rowHTML(o) {
    const creator = o.created_by_nom || o.created_by_username || "—";
    return `
        <tr data-carrega="${escapeHtml(o.carrega_id)}">
            <td><code>${escapeHtml(o.carrega_id)}</code></td>
            <td>${escapeHtml(o.car_fecsalida || "—")}</td>
            <td>${escapeHtml(o.motiu || "—")}</td>
            <td>${escapeHtml(creator)}</td>
            <td class="muted-small">${fmtTs(o.updated_at)}</td>
            <td class="col-acc">
                <button class="btn-mini" data-act="delete" title="Eliminar override">🗑️</button>
            </td>
        </tr>`;
}

async function carregar() {
    const tbody = $("#taula-overrides tbody");
    const errEl = $("#overrides-error");
    errEl.hidden = true;
    tbody.innerHTML = `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.5rem;">Carregant…</td></tr>`;
    try {
        state.overrides = await fetchJ("/api/admin/carrega-overrides");
        $("#overrides-count").textContent = state.overrides.length;
        if (state.overrides.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="muted" style="text-align:center;padding:1.5rem;">Cap override definit.</td></tr>`;
        } else {
            tbody.innerHTML = state.overrides.map(rowHTML).join("");
        }
    } catch (e) {
        tbody.innerHTML = "";
        errEl.textContent = `Error carregant overrides: ${e.message}`;
        errEl.hidden = false;
    }
}

function obreModalNou() {
    $("#dlg-override-titol").textContent = "Nou override";
    $("#form-override").reset();
    $("#f-carrega-id").disabled = false;
    $("#form-error").hidden = true;
    $("#dlg-override").showModal();
}

async function onSubmit(e) {
    e.preventDefault();
    const errEl = $("#form-error");
    errEl.hidden = true;
    const cid = $("#f-carrega-id").value.trim();
    const dtRaw = $("#f-fecsalida").value;
    if (!cid || !dtRaw) return;
    // datetime-local retorna "YYYY-MM-DDTHH:MM" — convertim a "YYYY-MM-DD HH:MM"
    const dt = dtRaw.replace("T", " ");
    const motiu = $("#f-motiu").value.trim();
    try {
        await fetchJ("/api/admin/carrega-overrides", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ carrega_id: cid, car_fecsalida: dt, motiu }),
        });
        $("#dlg-override").close();
        toast("success", `Override desat per ${cid}.`);
        carregar();
    } catch (err) {
        errEl.textContent = err.message;
        errEl.hidden = false;
    }
}

async function onEliminar(carregaId) {
    if (!confirm(`Eliminar l'override de ${carregaId}? El calendari tornarà a usar el valor de KAIS (o snapshot si n'hi ha).`)) return;
    try {
        await fetchJ(`/api/admin/carrega-overrides/${encodeURIComponent(carregaId)}`, { method: "DELETE" });
        toast("success", `Override de ${carregaId} eliminat.`);
        carregar();
    } catch (err) {
        toast("error", err.message);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    carregar();
    $("#btn-nou-override").addEventListener("click", obreModalNou);
    $("#form-override").addEventListener("submit", onSubmit);
    document.querySelectorAll("[data-close]").forEach(b => {
        b.addEventListener("click", () => b.closest("dialog").close());
    });
    $("#taula-overrides").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-act]");
        if (!btn) return;
        const tr = btn.closest("tr");
        const cid = tr?.dataset.carrega;
        if (!cid) return;
        if (btn.dataset.act === "delete") onEliminar(cid);
    });
});
})();
