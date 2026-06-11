(() => {
"use strict";

// ============================================================
// Constants i utilitats
// ============================================================
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const fmt = new Intl.NumberFormat("ca-ES");
const fmtKg = new Intl.NumberFormat("ca-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Converteix qualsevol data (ISO YYYY-MM-DD, Date o string ja amb separadors) a "DD-MM-YYYY"
function fmtData(v) {
    if (v == null || v === "") return "";
    if (v instanceof Date) {
        const dd = String(v.getDate()).padStart(2, "0");
        const mm = String(v.getMonth() + 1).padStart(2, "0");
        return `${dd}-${mm}-${v.getFullYear()}`;
    }
    const s = String(v).trim();
    // Format ISO YYYY-MM-DD (possible amb hora darrere)
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return `${m[3]}-${m[2]}-${m[1]}`;
    // Format YYYY/MM/DD
    const m2 = s.match(/^(\d{4})\/(\d{2})\/(\d{2})/);
    if (m2) return `${m2[3]}-${m2[2]}-${m2[1]}`;
    return s;
}
function fmtDataHora(d) {
    if (!(d instanceof Date)) d = new Date(d);
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${fmtData(d)} ${hh}:${mi}`;
}

const STORAGE_KEY = "agrupacioCarregues.prefs.v1";

// Paleta de 16 colors maximalment diferenciats (estil Tableau 10 + Okabe-Ito + addicionals).
// Ordenats perquè els primers (els més comuns) siguin els més contrastats entre si.
const PALETA = [
    { color: "#1f77b4", bg: "#e8f0f7" },  // 1  blau
    { color: "#ff7f0e", bg: "#fff0db" },  // 2  taronja
    { color: "#2ca02c", bg: "#e8f5e6" },  // 3  verd
    { color: "#d62728", bg: "#fce6e6" },  // 4  vermell
    { color: "#9467bd", bg: "#f1ebf7" },  // 5  lila
    { color: "#17becf", bg: "#e0f5f7" },  // 6  cian
    { color: "#e377c2", bg: "#fbe6f3" },  // 7  rosa
    { color: "#8c564b", bg: "#efe1de" },  // 8  marró
    { color: "#bcbd22", bg: "#f6f6d8" },  // 9  oliva-lima
    { color: "#000000", bg: "#eeeeee" },  // 10 negre
    { color: "#7f7f7f", bg: "#f0f0f0" },  // 11 gris
    { color: "#ff1493", bg: "#ffe2ee" },  // 12 magenta intens
    { color: "#daa520", bg: "#fbf0d4" },  // 13 or
    { color: "#4b0082", bg: "#ece0f0" },  // 14 indigo
    { color: "#00875a", bg: "#d8f0e6" },  // 15 verd-blau bandera
    { color: "#a52a2a", bg: "#f4dada" },  // 16 borgonya
];

function colorPerCarrega(carregaId, idx) {
    return PALETA[idx % PALETA.length];
}

// ============================================================
// Estat
// ============================================================
const state = {
    carregues: [],
    seleccio: new Set(),
    lastClickedIndex: -1,
    filtreText: "",
    ordenacio: { col: "car_fecsalida", dir: "desc" },
    ordenacioProductes: { col: "total_sacs", dir: "desc" },
    resultat: null,
    colorsCarrega: new Map(),  // carrega_id -> {color, bg}
    abortCerca: null,
    abortAgrupar: null,
};

function carregarPrefs() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) return {};
        return JSON.parse(raw) || {};
    } catch { return {}; }
}
function guardarPrefs(patch) {
    try {
        const cur = carregarPrefs();
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cur, ...patch }));
    } catch {}
}

// ============================================================
// Utilitats genèriques
// ============================================================
function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}
function escapeId(s) {
    return String(s ?? "").replace(/[^a-zA-Z0-9_-]/g, "_");
}
function debounce(fn, ms) {
    let t;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), ms);
    };
}
async function fetchJson(url, options = {}) {
    const resp = await fetch(url, options);
    if (!resp.ok) {
        let err = `HTTP ${resp.status}`;
        try { const j = await resp.json(); if (j.error) err = j.error; } catch (_) {}
        throw new Error(err);
    }
    return resp.json();
}

// ============================================================
// Toasts
// ============================================================
const TOAST_ICONS = { success: "✓", error: "✕", warning: "⚠", info: "ℹ" };
const TOAST_TTL = { success: 4500, error: 9000, warning: 7000, info: 5000 };

function showToast(type, title, body) {
    const wrap = $("#toasts");
    if (!wrap) return;
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.innerHTML = `
        <span class="toast-icon">${TOAST_ICONS[type] || ""}</span>
        <div class="toast-body">${title ? `<strong>${escapeHtml(title)}</strong>` : ""}${body ? escapeHtml(body) : ""}</div>
        <button class="toast-close" aria-label="Tanca">×</button>
    `;
    wrap.appendChild(t);
    const dismiss = () => {
        t.classList.add("is-leaving");
        setTimeout(() => t.remove(), 220);
    };
    t.querySelector(".toast-close").addEventListener("click", dismiss);
    setTimeout(dismiss, TOAST_TTL[type] || 5000);
    return t;
}
function tancaTotsToasts() {
    $$(".toast").forEach(t => {
        t.classList.add("is-leaving");
        setTimeout(() => t.remove(), 220);
    });
}

// ============================================================
// Botó amb spinner
// ============================================================
function btnLoading(btn, loading, labelOnLoad) {
    const lbl = btn.querySelector(".btn-label");
    const sp = btn.querySelector(".btn-spinner");
    if (loading) {
        btn.classList.add("is-loading");
        btn.disabled = true;
        if (lbl && labelOnLoad) lbl.dataset.orig = lbl.textContent, lbl.textContent = labelOnLoad;
        if (sp) sp.hidden = false;
    } else {
        btn.classList.remove("is-loading");
        btn.disabled = false;
        if (lbl && lbl.dataset.orig) lbl.textContent = lbl.dataset.orig, delete lbl.dataset.orig;
        if (sp) sp.hidden = true;
    }
}

// ============================================================
// Filtres ràpids de dates
// ============================================================
function toISO(d) { return d.toISOString().slice(0, 10); }
function calcRang(tipus) {
    const avui = new Date();
    avui.setHours(0,0,0,0);
    const d = new Date(avui);
    let desde, fins;
    switch (tipus) {
        case "today":
            desde = fins = toISO(avui); break;
        case "yesterday":
            d.setDate(d.getDate() - 1);
            desde = fins = toISO(d); break;
        case "this-week": {
            const dia = (avui.getDay() + 6) % 7; // dilluns=0
            const dl = new Date(avui); dl.setDate(avui.getDate() - dia);
            desde = toISO(dl); fins = toISO(avui); break;
        }
        case "last-week": {
            const dia = (avui.getDay() + 6) % 7;
            const dlAct = new Date(avui); dlAct.setDate(avui.getDate() - dia);
            const dlAnt = new Date(dlAct); dlAnt.setDate(dlAct.getDate() - 7);
            const dgAnt = new Date(dlAct); dgAnt.setDate(dlAct.getDate() - 1);
            desde = toISO(dlAnt); fins = toISO(dgAnt); break;
        }
        case "this-month": {
            const inici = new Date(avui.getFullYear(), avui.getMonth(), 1);
            desde = toISO(inici); fins = toISO(avui); break;
        }
        case "last-30": {
            const a = new Date(avui); a.setDate(a.getDate() - 30);
            desde = toISO(a); fins = toISO(avui); break;
        }
        default: return null;
    }
    return { desde, fins };
}
function aplicaFiltreRapid(tipus) {
    const r = calcRang(tipus);
    if (!r) return;
    $("#desde").value = r.desde;
    $("#fins").value = r.fins;
    validarFormulari();
    marcaFiltreActiu(tipus);
    buscarCarregues();
}
function marcaFiltreActiu(tipus) {
    $$(".chip-btn").forEach(b => b.classList.toggle("active", b.dataset.range === tipus));
}

// ============================================================
// Validació formulari
// ============================================================
function validarFormulari() {
    const desde = $("#desde").value;
    const fins = $("#fins").value;
    const inpD = $("#desde"), inpF = $("#fins");
    const errD = $("#err-desde"), errF = $("#err-fins");
    inpD.classList.remove("is-invalid");
    inpF.classList.remove("is-invalid");
    errD.hidden = true; errF.hidden = true;
    let ok = true;
    if (!desde) {
        inpD.classList.add("is-invalid");
        errD.textContent = "Tria una data.";
        errD.hidden = false;
        ok = false;
    }
    if (!fins) {
        inpF.classList.add("is-invalid");
        errF.textContent = "Tria una data.";
        errF.hidden = false;
        ok = false;
    }
    if (ok && desde > fins) {
        inpD.classList.add("is-invalid");
        inpF.classList.add("is-invalid");
        errF.textContent = "Ha de ser igual o posterior a 'Des de'.";
        errF.hidden = false;
        ok = false;
    }
    $("#btn-buscar").disabled = !ok;
    return ok;
}

// ============================================================
// Transportistes
// ============================================================
async function carregarTransportistes() {
    try {
        const llista = await fetchJson("/api/transportistes");
        const sel = $("#tra_codi");
        for (const t of llista) {
            const opt = document.createElement("option");
            opt.value = t.tra_codi;
            opt.textContent = `${t.tra_codi} — ${t.tra_nom}`;
            sel.appendChild(opt);
        }
        const prefs = carregarPrefs();
        if (prefs.tra_codi) sel.value = prefs.tra_codi;
    } catch (e) {
        showToast("error", "No s'han pogut carregar transportistes", e.message);
    }
}

// ============================================================
// Skeleton durant la cerca
// ============================================================
function pintaSkeleton(n = 5) {
    const tbody = $("#taula-carregues tbody");
    tbody.innerHTML = "";
    for (let i = 0; i < n; i++) {
        const tr = document.createElement("tr");
        tr.className = "skeleton-row";
        tr.innerHTML = `<td colspan="10"><span class="skeleton-bar" style="width:${60 + Math.random()*30}%"></span></td>`;
        tbody.appendChild(tr);
    }
    $("#empty-inicial").hidden = true;
    $("#seccio-llista").hidden = false;
    $("#msg-llista-buida").hidden = true;
}

// ============================================================
// Cerca de càrregues
// ============================================================
async function buscarCarregues() {
    if (!validarFormulari()) return;
    const desde = $("#desde").value;
    const fins = $("#fins").value;
    const tra = $("#tra_codi").value;

    guardarPrefs({ desde, fins, tra_codi: tra });

    if (state.abortCerca) state.abortCerca.abort();
    state.abortCerca = new AbortController();

    const btn = $("#btn-buscar");
    btnLoading(btn, true, "Cercant…");
    pintaSkeleton();
    try {
        const params = new URLSearchParams({ desde, fins });
        if (tra) params.set("tra_codi", tra);
        const llista = await fetchJson(`/api/carregues?${params}`, {
            signal: state.abortCerca.signal,
        });
        state.carregues = llista;
        state.seleccio.clear();
        state.lastClickedIndex = -1;
        state.filtreText = "";
        $("#filtre-taula").value = "";
        renderLlistaCarregues();
    } catch (e) {
        if (e.name !== "AbortError") {
            showToast("error", "Error cercant càrregues", e.message);
            $("#taula-carregues tbody").innerHTML = "";
        }
    } finally {
        btnLoading(btn, false);
    }
}

// ============================================================
// Renderitzar llista de càrregues
// ============================================================
function llistaVisible() {
    let llista = state.carregues.slice();
    // Filtre text
    if (state.filtreText) {
        const q = state.filtreText.toLowerCase();
        llista = llista.filter(c =>
            (c.carrega_id || "").toLowerCase().includes(q) ||
            (c.car_descripcion || "").toLowerCase().includes(q) ||
            (c.transportista || "").toLowerCase().includes(q) ||
            (c.tra_codi || "").toLowerCase().includes(q) ||
            (c.car_matricula || "").toLowerCase().includes(q) ||
            (c.car_nomconductor || "").toLowerCase().includes(q) ||
            (c.car_observaciones || "").toLowerCase().includes(q)
        );
    }
    // Ordenació
    const { col, dir } = state.ordenacio;
    if (col) {
        const sign = dir === "asc" ? 1 : -1;
        llista.sort((a, b) => {
            const va = a[col] ?? "";
            const vb = b[col] ?? "";
            if (typeof va === "number" && typeof vb === "number") return (va - vb) * sign;
            return String(va).localeCompare(String(vb), "ca", { numeric: true }) * sign;
        });
    }
    return llista;
}

function renderLlistaCarregues() {
    const tbody = $("#taula-carregues tbody");
    tbody.innerHTML = "";
    $("#empty-inicial").hidden = true;
    $("#seccio-llista").hidden = false;

    const llista = llistaVisible();
    $("#count-carregues").textContent = `(${state.carregues.length})`;
    if (state.filtreText) {
        $("#count-filtre").hidden = false;
        $("#count-filtre").textContent = `mostrant ${llista.length} de ${state.carregues.length}`;
    } else {
        $("#count-filtre").hidden = true;
    }

    // Marca columna ordenada
    $$("#taula-carregues thead th[data-sort]").forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.sort === state.ordenacio.col) {
            th.classList.add(state.ordenacio.dir === "asc" ? "sort-asc" : "sort-desc");
        }
    });

    if (state.carregues.length === 0) {
        $("#msg-llista-buida").hidden = false;
        actualitzarBotoAgrupar();
        actualitzarCheckAll();
        return;
    }
    if (llista.length === 0) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td colspan="10" class="muted" style="text-align:center;padding:1.5rem;">Cap càrrega coincideix amb el filtre "${escapeHtml(state.filtreText)}".</td>`;
        tbody.appendChild(tr);
        $("#msg-llista-buida").hidden = true;
        actualitzarBotoAgrupar();
        actualitzarCheckAll();
        return;
    }
    $("#msg-llista-buida").hidden = true;

    llista.forEach((c, idx) => {
        const tr = document.createElement("tr");
        tr.dataset.carregaId = c.carrega_id;
        tr.dataset.idx = idx;
        tr.classList.add("row-clickable");
        if (state.seleccio.has(c.carrega_id)) tr.classList.add("row-selected");

        const tdCheck = document.createElement("td");
        tdCheck.className = "col-check";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = state.seleccio.has(c.carrega_id);
        cb.addEventListener("click", (ev) => {
            ev.stopPropagation();
            gestionaSeleccio(c.carrega_id, idx, ev.shiftKey, cb.checked);
        });
        tdCheck.appendChild(cb);
        tr.appendChild(tdCheck);

        const tdExpand = document.createElement("td");
        tdExpand.className = "col-expand";
        const btnExpand = document.createElement("button");
        btnExpand.type = "button";
        btnExpand.className = "toggle-btn";
        btnExpand.textContent = "▶";
        btnExpand.title = "Veure contingut";
        btnExpand.setAttribute("aria-expanded", "false");
        btnExpand.addEventListener("click", (ev) => {
            ev.stopPropagation();
            toggleDetallCarrega(c, tr, btnExpand);
        });
        tdExpand.appendChild(btnExpand);
        tr.appendChild(tdExpand);

        tr.insertAdjacentHTML("beforeend", `
            <td><code>${escapeHtml(c.carrega_id)}</code></td>
            <td class="cell-truncate" title="${escapeHtml(c.car_descripcion)}">${escapeHtml(c.car_descripcion || "—")}</td>
            <td>${escapeHtml(fmtData(c.car_fecsalida || c.car_fecha) || "—")}</td>
            <td class="cell-truncate" title="${escapeHtml(c.transportista || c.tra_codi)}">${escapeHtml(c.transportista || c.tra_codi)}</td>
            <td class="cell-truncate" title="${escapeHtml(c.car_matricula)}">${escapeHtml(c.car_matricula)}</td>
            <td class="cell-truncate" title="${escapeHtml(c.car_nomconductor)}">${escapeHtml(c.car_nomconductor)}</td>
            <td class="num">${c.car_pesonetocarga ? fmt.format(c.car_pesonetocarga) : "—"}</td>
            <td class="cell-truncate" title="${escapeHtml(c.car_observaciones)}">${escapeHtml(c.car_observaciones)}</td>
        `);

        // Click a la fila (no checkbox, no toggle) commuta selecció
        tr.addEventListener("click", (ev) => {
            if (ev.target.closest("input,button,a,code")) return;
            gestionaSeleccio(c.carrega_id, idx, ev.shiftKey, !state.seleccio.has(c.carrega_id));
        });
        tbody.appendChild(tr);
    });
    actualitzarBotoAgrupar();
    actualitzarCheckAll();
}

// ============================================================
// Gestió de selecció (amb shift+click per rang)
// ============================================================
function gestionaSeleccio(carregaId, idx, shift, checked) {
    if (shift && state.lastClickedIndex >= 0) {
        const visibles = llistaVisible();
        const start = Math.min(state.lastClickedIndex, idx);
        const end = Math.max(state.lastClickedIndex, idx);
        for (let i = start; i <= end; i++) {
            const c = visibles[i];
            if (!c) continue;
            if (checked) state.seleccio.add(c.carrega_id);
            else state.seleccio.delete(c.carrega_id);
        }
    } else {
        if (checked) state.seleccio.add(carregaId);
        else state.seleccio.delete(carregaId);
    }
    state.lastClickedIndex = idx;
    renderLlistaCarregues();
}

function marcarTotes(valor) {
    if (valor) {
        for (const c of llistaVisible()) state.seleccio.add(c.carrega_id);
    } else {
        state.seleccio.clear();
        state.lastClickedIndex = -1;
    }
    renderLlistaCarregues();
}

function actualitzarCheckAll() {
    const cb = $("#check-all");
    if (!cb) return;
    const visibles = llistaVisible();
    const sel = visibles.filter(c => state.seleccio.has(c.carrega_id)).length;
    cb.checked = visibles.length > 0 && sel === visibles.length;
    cb.indeterminate = sel > 0 && sel < visibles.length;
}

function actualitzarBotoAgrupar() {
    const n = state.seleccio.size;
    const btn = $("#btn-agrupar");
    const bar = $("#action-bar");
    const cnt = $("#action-count");
    const meta = $("#action-meta");
    const btnDesel = $("#btn-desselecciona");
    if (cnt) cnt.textContent = n;
    if (btnDesel) btnDesel.hidden = n === 0;

    // Estimació ràpida de pes total seleccionat
    if (meta) {
        if (n > 0) {
            const pes = state.carregues
                .filter(c => state.seleccio.has(c.carrega_id))
                .reduce((acc, c) => acc + (Number(c.car_pesonetocarga) || 0), 0);
            meta.textContent = pes > 0 ? `· ~${fmt.format(pes)} kg` : "";
        } else {
            meta.textContent = "";
        }
    }

    if (n === 0) {
        btn.disabled = true;
        btn.title = "Selecciona almenys una càrrega";
    } else if (n > 50) {
        btn.disabled = true;
        btn.title = `Màxim 50 càrregues — actualment ${n} seleccionades`;
    } else {
        btn.disabled = false;
        btn.title = `Agrupar ${n} càrregues`;
    }

    // Mostra/amaga barra d'acció
    if (bar) {
        const visible = n > 0;
        bar.hidden = !visible;
        document.body.classList.toggle("has-action-bar", visible);
    }
}

// ============================================================
// Detall de càrrega
// ============================================================
const detallCache = new Map();

async function toggleDetallCarrega(c, tr, btn) {
    const existing = tr.nextElementSibling;
    if (existing && existing.classList.contains("row-detall-carrega")) {
        existing.remove();
        btn.textContent = "▶";
        btn.setAttribute("aria-expanded", "false");
        return;
    }
    btn.textContent = "▼";
    btn.setAttribute("aria-expanded", "true");

    const detall = document.createElement("tr");
    detall.className = "row-detall row-detall-carrega";
    const td = document.createElement("td");
    td.colSpan = 10;
    td.innerHTML = `<span class="loading-inline"><span class="spinner-inline"></span>Carregant contingut…</span>`;
    detall.appendChild(td);
    tr.parentNode.insertBefore(detall, tr.nextSibling);

    try {
        let data;
        if (detallCache.has(c.carrega_id)) {
            data = detallCache.get(c.carrega_id);
        } else {
            const params = new URLSearchParams({ eje: c.eje_ejercicio, sca: c.sca_serie, car: c.car_numero });
            data = await fetchJson(`/api/carrega-detall?${params}`);
            detallCache.set(c.carrega_id, data);
        }
        td.innerHTML = renderDetallCarrega(data);
    } catch (e) {
        td.innerHTML = `<span class="error-inline">Error: ${escapeHtml(e.message)}</span>`;
    }
}

function renderDetallCarrega(data) {
    if (!data.albarans || data.albarans.length === 0) {
        return `<span class="muted">Aquesta càrrega no té albarans associats a Detcargas.</span>`;
    }
    const blocks = data.albarans.map(a => {
        const linies = a.linies.map(l => `
            <tr>
                <td><code>${escapeHtml(l.art_codi)}</code></td>
                <td>${escapeHtml(l.art_descrip)}</td>
                <td>${escapeHtml(l.tunitat)}</td>
                <td class="num">${fmt.format(l.sacs)}</td>
                <td class="num">${fmtKg.format(l.kg)}</td>
            </tr>
        `).join("");
        const tipoBadge = a.det_tipo === "P"
            ? `<span class="badge badge-warn" title="Comanda pendent">P</span>`
            : `<span class="badge badge-ok" title="Albarà">A</span>`;
        return `
            <div class="albara-block">
                <h4>
                    <span><code>${escapeHtml(a.albara)}</code> ${tipoBadge} · ${escapeHtml(a.cli_codi)} ${escapeHtml(a.cli_nom)}</span>
                    <span class="muted">${fmt.format(a.total_sacs)} sacs · ${fmtKg.format(a.total_kg)} kg</span>
                </h4>
                <table class="data-table data-table-mini">
                    <thead><tr><th>Article</th><th>Descripció</th><th>TUnitat</th><th class="num">Sacs</th><th class="num">Kg</th></tr></thead>
                    <tbody>${linies || `<tr><td colspan="5" class="muted">Sense línies</td></tr>`}</tbody>
                </table>
            </div>
        `;
    }).join("");
    return `
        <div class="detall-resum muted">
            ${data.albarans.length} albarans · <strong>${fmt.format(data.total_sacs)}</strong> sacs · <strong>${fmtKg.format(data.total_kg)}</strong> kg
        </div>
        ${blocks}
    `;
}

// ============================================================
// Agrupar
// ============================================================
async function agrupar() {
    const sel = state.carregues.filter(c => state.seleccio.has(c.carrega_id));
    if (sel.length === 0) return;
    if (sel.length > 50) {
        showToast("warning", "Massa càrregues", `Selecciona com a màxim 50 (actualment ${sel.length}).`);
        return;
    }

    if (state.abortAgrupar) state.abortAgrupar.abort();
    state.abortAgrupar = new AbortController();

    const btn = $("#btn-agrupar");
    btnLoading(btn, true, "Agrupant…");
    try {
        const resultat = await fetchJson("/api/agrupar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ carregues: sel }),
            signal: state.abortAgrupar.signal,
        });
        state.resultat = resultat;
        renderResultat(resultat);
        obrirModalResultat();
        const palets = resultat.total_palets_fisics || 0;
        const resumPalets = (resultat.tipus_palets || []).slice(0, 3)
            .map(t => `${t.quantitat} ${t.tipus_palet_descrip}`).join(", ");
        showToast("success", "Agrupació completada",
            `${resultat.carregues.length} càrregues, ${resultat.productes.length} productes, ${palets} palets físics${resumPalets ? ` (${resumPalets})` : ""}.`);
    } catch (e) {
        if (e.name !== "AbortError") showToast("error", "Error agrupant", e.message);
    } finally {
        btnLoading(btn, false);
        actualitzarBotoAgrupar();
    }
}

// Genera el desglós inline de palets per cada càrrega, en format "N×M" amb color
function palletsInlinePerProducte(p) {
    // Ordre per índex de càrrega (mateix ordre de la llegenda)
    const ordreIdx = new Map();
    if (state.resultat) {
        state.resultat.carregues.forEach((c, i) => ordreIdx.set(c.carrega_id, i));
    }
    const pcOrdenats = (p.per_carrega || []).slice().sort((a, b) =>
        (ordreIdx.get(a.carrega_id) ?? 999) - (ordreIdx.get(b.carrega_id) ?? 999)
    );

    const trossos = [];
    for (const pc of pcOrdenats) {
        const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#000" };
        // Agrupa palets idèntics (mateix nombre de sacs)
        const agg = new Map();
        for (const pd of (pc.palets || [])) {
            const k = `${pd.sacs}`;
            agg.set(k, (agg.get(k) || 0) + 1);
        }
        const peces = [...agg.entries()]
            .sort((a, b) => Number(b[0]) - Number(a[0]))
            .map(([sacs, n]) => `${n}×${sacs}`)
            .join(" ");
        if (peces) {
            trossos.push(`<span class="print-palets-grp" style="color:${col.color}">${peces}</span>`);
        }
    }
    return trossos.join(" ");
}

function omplirCapçaleraPrint() {
    if (!state.resultat) return;
    const r = state.resultat;
    const ara = new Date();
    const data = fmtData(ara);
    const hora = ara.toLocaleTimeString("ca-ES");
    const dt = $("#print-datetime");
    if (dt) dt.innerHTML = `${data}<br>${hora}`;

    // Data: si totes les càrregues tenen la mateixa data de sortida la mostrem,
    // sino mostrem el rang del filtre actual.
    const dates = [...new Set(r.carregues.map(c => c.data_sortida).filter(Boolean))];
    const desde = $("#desde")?.value, fins = $("#fins")?.value;
    let textData;
    if (dates.length === 1) {
        textData = fmtData(dates[0]);
    } else if (desde && fins) {
        textData = `${fmtData(desde)} → ${fmtData(fins)}`;
    } else {
        textData = "—";
    }
    const elD = $("#print-data-sortida");
    if (elD) elD.textContent = textData;

    // Transportista: si totes tenen el mateix el mostrem, sino "Diversos"
    const trans = [...new Set(r.carregues.map(c => c.transportista || c.tra_codi).filter(Boolean))];
    const textTr = trans.length === 1 ? trans[0] : (trans.length === 0 ? "—" : "Diversos");
    const elT = $("#print-transportista");
    if (elT) elT.textContent = textTr;

    // Llegenda de càrregues: nom_curt (color)
    const leg = $("#print-leg");
    if (leg) {
        leg.innerHTML = r.carregues.map((c, i) => {
            const col = state.colorsCarrega.get(c.carrega_id) || { color: "#000" };
            const nom = (c.descripcio || c.carrega_id).trim() || c.carrega_id;
            return `<span class="print-leg-item" style="color:${col.color}"><strong>${escapeHtml(nom)}</strong></span>`;
        }).join("");
    }
}

function imprimirInforme() {
    if (!state.resultat) return;
    omplirCapçaleraPrint();

    // Injecta els palets inline per cada fila de producte (al td descripció)
    const tbody = $("#taula-productes tbody");
    const injectats = [];
    if (tbody) {
        const productes = productesOrdenats();
        const files = tbody.querySelectorAll("tr:not(.row-detall)");
        files.forEach((tr, idx) => {
            const p = productes[idx];
            if (!p) return;
            const tdDescrip = tr.children[3]; // 0:toggle, 1:art_codi, 2:descrip oops, watch
            // L'ordre real és: 0 toggle, 1 art_codi, 2 art_descrip, 3 tunitat, 4 total_sacs, 5 total_kg
            const tdArt = tr.children[2];
            if (!tdArt) return;
            const span = document.createElement("span");
            span.className = "print-palets-inline";
            span.innerHTML = " " + palletsInlinePerProducte(p);
            tdArt.appendChild(span);
            injectats.push(span);
        });
    }

    window.print();

    // Neteja: treu els spans injectats
    setTimeout(() => {
        for (const sp of injectats) sp.remove();
    }, 300);
}

function obrirModalResultat() {
    const dlg = $("#resultat-dialog");
    if (!dlg) return;
    if (typeof dlg.showModal === "function" && !dlg.open) dlg.showModal();
    else dlg.setAttribute("open", "");
    // Mantenir scroll del modal a dalt
    const body = $(".resultat-body");
    if (body) body.scrollTop = 0;
}
function tancarModalResultat() {
    const dlg = $("#resultat-dialog");
    if (!dlg) return;
    if (typeof dlg.close === "function" && dlg.open) dlg.close();
    else dlg.removeAttribute("open");
}

// ============================================================
// Render resultat (KPIs + Palets tipus + chips colorides + productes)
// ============================================================
function renderResultat(r) {
    // Assigna colors a cada càrrega
    state.colorsCarrega.clear();
    r.carregues.forEach((c, i) => {
        state.colorsCarrega.set(c.carrega_id, colorPerCarrega(c.carrega_id, i));
    });

    // Metadades de capçalera del resultat
    const desdeIso = $("#desde").value;
    const finsIso = $("#fins").value;
    const desdeFmt = desdeIso ? fmtData(desdeIso) : "—";
    const finsFmt = finsIso ? fmtData(finsIso) : "—";
    const sel = $("#tra_codi");
    const tra = sel && sel.value ? (sel.options[sel.selectedIndex]?.textContent || sel.value) : "Tots";
    const araStr = fmtDataHora(new Date());
    const metaEl = $("#resultat-meta");
    if (metaEl) {
        metaEl.textContent = `Rang ${desdeFmt} → ${finsFmt} · Transportista: ${tra} · Generat ${araStr}`;
    }
    const printMeta = $("#print-meta");
    if (printMeta) {
        printMeta.textContent = `Informe d'agrupació · Rang ${desdeFmt} → ${finsFmt} · Transportista: ${tra} · Generat ${araStr}`;
    }

    // KPIs
    $("#kpis").innerHTML = `
        <div class="kpi"><div class="label">Càrregues</div><div class="value">${r.carregues.length}</div></div>
        <div class="kpi"><div class="label">Productes</div><div class="value">${r.productes.length}</div></div>
        <div class="kpi"><div class="label">Total sacs</div><div class="value">${fmt.format(r.total_sacs)}</div></div>
        <div class="kpi"><div class="label">Total kg</div><div class="value">${fmtKg.format(r.total_kg)}</div></div>
        <div class="kpi"><div class="label">Palets físics</div><div class="value">${fmt.format(r.total_palets_fisics)}</div></div>
    `;

    // Palets per tipus (amb desglós per càrrega colorit)
    const ulTipus = $("#palets-per-tipus");
    ulTipus.innerHTML = "";
    if (r.tipus_palets && r.tipus_palets.length > 0) {
        ulTipus.hidden = false;
        for (const t of r.tipus_palets) {
            const li = document.createElement("li");
            li.className = "palet-tipus-card";
            const dots = (t.per_carrega || []).map(pc => {
                const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096" };
                return `<span class="qt-dot" title="${escapeHtml(pc.carrega_id)}: ${pc.quantitat} palets" style="--dot-color:${col.color}">` +
                       `<span class="dot"></span><span class="dot-n">${fmt.format(pc.quantitat)}</span>` +
                       `</span>`;
            }).join("");
            li.innerHTML = `
                <div class="palet-tipus-top">
                    <span class="qt">${fmt.format(t.quantitat)}</span>
                    <span class="desc"><strong>${escapeHtml(t.tipus_palet_descrip)}</strong><br><span class="muted">${escapeHtml(t.tipus_palet)}</span></span>
                </div>
                ${dots ? `<div class="palet-tipus-dots">${dots}</div>` : ""}
            `;
            ulTipus.appendChild(li);
        }
    } else {
        ulTipus.hidden = true;
    }

    // Chips de càrregues incloses (amb color)
    const chips = $("#carregues-incloses");
    chips.innerHTML = "";
    for (const c of r.carregues) {
        const col = state.colorsCarrega.get(c.carrega_id) || { color: "#718096", bg: "#fff" };
        const ch = document.createElement("span");
        ch.className = "chip";
        ch.style.setProperty("--chip-color", col.color);
        ch.style.setProperty("--chip-bg", col.bg);
        ch.innerHTML = `<span class="chip-dot"></span><strong>${escapeHtml(c.carrega_id)}</strong> · ${escapeHtml(c.transportista || c.tra_codi)}` +
            (c.matricula ? ` · ${escapeHtml(c.matricula)}` : "");
        chips.appendChild(ch);
    }

    // Productes
    renderTaulaProductes();

    // Incidències / badge
    const inc = $("#incidencies");
    const ul = $("#llista-incidencies");
    const badge = $("#badge-incidencies");
    ul.innerHTML = "";
    if (r.incidencies.length > 0) {
        inc.hidden = false;
        $("#count-incidencies").textContent = `(${r.incidencies.length})`;
        badge.hidden = false;
        badge.className = "badge-danger";
        badge.textContent = `${r.incidencies.length} incidència${r.incidencies.length > 1 ? "s" : ""}`;
        for (const i of r.incidencies) {
            const li = document.createElement("li");
            li.className = i.tipus;
            li.innerHTML = `<strong>${escapeHtml(i.carrega_id)}</strong> ${i.albara && i.albara !== "-" ? `· ${escapeHtml(i.albara)} ` : ""}— ${escapeHtml(i.missatge)}`;
            ul.appendChild(li);
        }
    } else {
        inc.hidden = true;
        badge.hidden = false;
        badge.className = "badge-success";
        badge.textContent = "Sense incidències";
    }
}

// Abreviació curta del tipus de palet a partir de la descripció ("BASE PALET" -> "BASE", etc.)
function abreviarTipusPalet(descrip) {
    if (!descrip) return "";
    const d = String(descrip).toUpperCase();
    if (d.startsWith("BASE")) return "BASE";
    if (d.includes("PLAST") && d.includes("EUROPEU")) return "EU·PL";
    if (d.includes("FUSTA") && d.includes("EUROPEU")) return "EU";
    if (d.includes("EUROPEU")) return "EU";
    if (d.includes("PLAST")) return "PL";
    if (d.includes("AMERICA")) return "AM";
    if (d.includes("CAIXA")) return "CX";
    if (d.includes("MIG"))   return "MIG";
    const paraules = d.split(/\s+/).filter(p => p && p !== "PALET" && !/^\d/.test(p));
    return paraules[0] ? paraules[0].slice(0, 4) : "";
}

// Genera el text "(1×42 1×44 EU)" per la cel·la de càrregues d'un producte
function detallPaletsCarrega(pc) {
    const grups = new Map();
    for (const pd of (pc.palets || [])) {
        const k = `${pd.sacs}||${pd.tipus_palet}`;
        const cur = grups.get(k) || {
            sacs: pd.sacs,
            tipus: pd.tipus_palet,
            descrip: pd.tipus_palet_descrip,
            n: 0,
        };
        cur.n += 1;
        grups.set(k, cur);
    }
    const llista = [...grups.values()].sort((a, b) => b.sacs - a.sacs);
    if (!llista.length) return "";
    const tipusUnics = [...new Set(llista.map(g => g.tipus))];
    if (tipusUnics.length === 1) {
        const ab = abreviarTipusPalet(llista[0].descrip);
        const peces = llista.map(g => `${g.n}×${g.sacs}`).join(" ");
        return ab ? `${peces} ${ab}` : peces;
    }
    return llista.map(g => {
        const ab = abreviarTipusPalet(g.descrip);
        return ab ? `${g.n}×${g.sacs} ${ab}` : `${g.n}×${g.sacs}`;
    }).join(" ");
}

function productesOrdenats() {
    if (!state.resultat) return [];
    const llista = state.resultat.productes.slice();
    const { col, dir } = state.ordenacioProductes;
    if (!col) return llista;
    const sign = dir === "asc" ? 1 : -1;
    const numeric = (col === "total_sacs" || col === "total_kg");
    llista.sort((a, b) => {
        const va = a[col] ?? (numeric ? 0 : "");
        const vb = b[col] ?? (numeric ? 0 : "");
        if (numeric) return (Number(va) - Number(vb)) * sign;
        return String(va).localeCompare(String(vb), "ca", { numeric: true }) * sign;
    });
    return llista;
}

function renderTaulaProductes() {
    const tbody = $("#taula-productes tbody");
    if (!tbody) return;
    // Recorda quines files estaven expandides
    const oberts = new Set();
    tbody.querySelectorAll(".row-detall:not([hidden])").forEach(tr => oberts.add(tr.id));

    tbody.innerHTML = "";
    const llista = productesOrdenats();

    // Ordre de càrregues per índex (mateix ordre de la llegenda i KPIs)
    const ordreIdx = new Map();
    if (state.resultat) {
        state.resultat.carregues.forEach((c, i) => ordreIdx.set(c.carrega_id, i));
    }

    for (const p of llista) {
        const idRow = `prod-${escapeId(p.art_codi)}`;
        const pcOrdenats = (p.per_carrega || []).slice().sort((a, b) =>
            (ordreIdx.get(a.carrega_id) ?? 999) - (ordreIdx.get(b.carrega_id) ?? 999)
        );
        const dotsProd = pcOrdenats.map(pc => {
            const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096" };
            const detall = detallPaletsCarrega(pc);
            const tooltip = `${pc.carrega_id}${pc.transportista ? " · " + pc.transportista : ""}`;
            return `<div class="qt-dot-row" title="${escapeHtml(tooltip)}"
                          style="--dot-color:${col.color}">
                        <span class="dot"></span>
                        <span class="dot-n">${fmt.format(pc.total_sacs)}</span>
                        ${detall ? `<span class="dot-detall">(${escapeHtml(detall)})</span>` : ""}
                    </div>`;
        }).join("");
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><button class="toggle-btn" data-target="${idRow}" aria-expanded="false">▶</button></td>
            <td><code>${escapeHtml(p.art_codi)}</code></td>
            <td>${escapeHtml(p.art_descrip)}</td>
            <td>${escapeHtml(p.tunitat)}</td>
            <td class="col-carregues-dots">${dotsProd}</td>
            <td class="num"><strong>${fmt.format(p.total_sacs)}</strong></td>
            <td class="num">${fmtKg.format(p.total_kg)}</td>
        `;
        tbody.appendChild(tr);

        const detall = document.createElement("tr");
        detall.id = idRow;
        detall.className = "row-detall";
        detall.hidden = !oberts.has(idRow);
        detall.innerHTML = `<td></td><td colspan="6">${renderPerCarrega(p)}</td>`;
        tbody.appendChild(detall);

        if (oberts.has(idRow)) {
            const btn = tr.querySelector(".toggle-btn");
            btn.textContent = "▼";
            btn.setAttribute("aria-expanded", "true");
        }
    }
    tbody.querySelectorAll(".toggle-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const tgt = document.getElementById(btn.dataset.target);
            const open = !tgt.hidden;
            tgt.hidden = open;
            btn.textContent = open ? "▶" : "▼";
            btn.setAttribute("aria-expanded", String(!open));
        });
    });

    // Marca columna ordenada
    $$("#taula-productes thead th[data-sort]").forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.sort === state.ordenacioProductes.col) {
            th.classList.add(state.ordenacioProductes.dir === "asc" ? "sort-asc" : "sort-desc");
        }
    });
}

function ordenarProductesPer(col) {
    if (state.ordenacioProductes.col === col) {
        state.ordenacioProductes.dir = state.ordenacioProductes.dir === "asc" ? "desc" : "asc";
    } else {
        state.ordenacioProductes.col = col;
        // Per columnes numèriques per defecte més gran a més petit
        state.ordenacioProductes.dir = (col === "total_sacs" || col === "total_kg") ? "desc" : "asc";
    }
    renderTaulaProductes();
}

function renderPerCarrega(p) {
    return p.per_carrega.map(pc => {
        const col = state.colorsCarrega.get(pc.carrega_id) || { color: "#718096", bg: "#fff" };
        // Agrupar palets per (tipus_palet, sacs_x_base, sacs, albara, det_tipo).
        // Palets idèntics del mateix albarà → "N × ...". Diferent albarà → línia separada.
        const agg = new Map();
        for (const pd of pc.palets) {
            const k = `${pd.tipus_palet}||${pd.sacs_x_base || 0}||${pd.sacs}||${pd.albara || ""}||${pd.det_tipo || ""}`;
            const cur = agg.get(k) || {
                tipus_palet: pd.tipus_palet,
                tipus_descrip: pd.tipus_palet_descrip,
                sacs: pd.sacs,
                sacs_x_base: pd.sacs_x_base || 0,
                max_sacs: pd.max_sacs || 0,
                albara: pd.albara || "",
                det_tipo: pd.det_tipo || "",
                n: 0,
            };
            cur.n += 1;
            agg.set(k, cur);
        }
        const palets = [...agg.values()]
            .sort((a, b) => (a.albara || "").localeCompare(b.albara || "") || b.sacs - a.sacs)
            .map(x => {
                const baseTxt = x.sacs_x_base > 0
                    ? ` <span class="palet-base">base ${x.sacs_x_base}</span>`
                    : "";
                const pisos = x.sacs_x_base > 0 ? Math.ceil(x.sacs / x.sacs_x_base) : 0;
                const pisosTxt = pisos > 0 ? ` · ${pisos} pis${pisos > 1 ? "os" : ""}` : "";
                const albLabel = x.det_tipo === "P" ? "Comanda" : "Albarà";
                const albTxt = x.albara
                    ? `<span class="palet-albara" title="${albLabel} d'origen">${albLabel} <code>${escapeHtml(x.albara)}</code></span>`
                    : "";
                return `<li class="palet-item" style="--palet-color:${col.color};--palet-bg:${col.bg};">
                    <span class="palet-main">${x.n} × ${escapeHtml(x.tipus_descrip || x.tipus_palet)}${baseTxt}${albTxt}</span>
                    <strong>${fmt.format(x.sacs)} sacs${pisosTxt}</strong>
                </li>`;
            })
            .join("");
        return `
            <div class="carrega-block" style="--cb-color:${col.color};--cb-bg:${col.bg};">
                <h4>
                    <span class="cb-title"><span class="cb-dot"></span><code>${escapeHtml(pc.carrega_id)}</code> · ${escapeHtml(pc.transportista || pc.tra_codi)}</span>
                    <span class="muted">${fmt.format(pc.total_sacs)} sacs · ${fmtKg.format(pc.total_kg)} kg</span>
                </h4>
                <ul class="palets-list">${palets}</ul>
            </div>
        `;
    }).join("");
}

// ============================================================
// Exportació CSV
// ============================================================
function exportarCsv() {
    if (!state.resultat) return;
    const r = state.resultat;
    const rows = [
        ["Article", "Descripció", "TUnitat", "Total sacs", "Total kg", "Càrrega", "Transportista", "Albarà/Comanda", "Tipus doc", "Tipus palet", "Sacs palet", "Sacs x base", "Max sacs"],
    ];
    for (const p of r.productes) {
        for (const pc of p.per_carrega) {
            for (const pd of pc.palets) {
                rows.push([
                    p.art_codi, p.art_descrip, p.tunitat,
                    p.total_sacs, p.total_kg.toFixed(2),
                    pc.carrega_id, pc.transportista,
                    pd.albara || "", pd.det_tipo === "P" ? "Comanda" : (pd.det_tipo === "A" ? "Albarà" : ""),
                    pd.tipus_palet_descrip || pd.tipus_palet, pd.sacs,
                    pd.sacs_x_base || "", pd.max_sacs || "",
                ]);
            }
        }
    }
    // Resum global de palets per tipus
    if (r.tipus_palets && r.tipus_palets.length) {
        rows.push([]);
        rows.push(["Resum palets físics per tipus"]);
        rows.push(["Tipus palet", "Descripció", "Quantitat"]);
        for (const t of r.tipus_palets) {
            rows.push([t.tipus_palet, t.tipus_palet_descrip, t.quantitat]);
        }
    }
    const csv = rows.map(r => r.map(csvCell).join(";")).join("\r\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `agrupacio_${fmtData(new Date())}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    showToast("info", "CSV descarregat", `${a.download}`);
}
function csvCell(v) {
    const s = String(v ?? "");
    if (/[;"\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
}

// ============================================================
// Ordenació de columnes
// ============================================================
function ordenarPer(col) {
    if (state.ordenacio.col === col) {
        state.ordenacio.dir = state.ordenacio.dir === "asc" ? "desc" : "asc";
    } else {
        state.ordenacio.col = col;
        state.ordenacio.dir = "asc";
    }
    renderLlistaCarregues();
}

// ============================================================
// Dreceres de teclat
// ============================================================
function setupKeyboard() {
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            tancaTotsToasts();
            if (state.abortCerca) state.abortCerca.abort();
            if (state.abortAgrupar) state.abortAgrupar.abort();
            const dlg = $("#help-dialog");
            if (dlg && dlg.open) dlg.close();
            const dlgRes = $("#resultat-dialog");
            if (dlgRes && dlgRes.open) dlgRes.close();
            return;
        }
        if (e.ctrlKey && (e.key === "a" || e.key === "A")) {
            const inField = e.target.closest("input,textarea,select");
            if (inField) return;
            if (!$("#seccio-llista").hidden && state.carregues.length > 0) {
                e.preventDefault();
                marcarTotes(true);
            }
        }
    });
}

// ============================================================
// Bootstrap
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
    const prefs = carregarPrefs();
    if (prefs.desde) $("#desde").value = prefs.desde;
    if (prefs.fins) $("#fins").value = prefs.fins;

    carregarTransportistes();

    // Filtres ràpids
    $$(".chip-btn").forEach(b => {
        b.addEventListener("click", () => aplicaFiltreRapid(b.dataset.range));
    });

    // Validació viva
    $("#desde").addEventListener("input", validarFormulari);
    $("#fins").addEventListener("input", validarFormulari);
    validarFormulari();

    // Formulari
    $("#form-filtres").addEventListener("submit", (e) => {
        e.preventDefault();
        buscarCarregues();
    });

    // Botons selecció / agrupar
    $("#check-all").addEventListener("change", (e) => marcarTotes(e.target.checked));
    $("#btn-agrupar").addEventListener("click", agrupar);
    $("#btn-desselecciona").addEventListener("click", () => marcarTotes(false));
    $("#btn-exportar-csv").addEventListener("click", exportarCsv);
    $("#btn-imprimir").addEventListener("click", imprimirInforme);
    $("#btn-tanca-resultat").addEventListener("click", tancarModalResultat);

    // Tancar modal en clicar fora
    const dlgRes = $("#resultat-dialog");
    if (dlgRes) {
        dlgRes.addEventListener("click", (e) => {
            const rect = dlgRes.querySelector("#seccio-resultat").getBoundingClientRect();
            if (e.clientX < rect.left || e.clientX > rect.right ||
                e.clientY < rect.top || e.clientY > rect.bottom) {
                tancarModalResultat();
            }
        });
    }

    // Filtre live taula
    const filtreInput = $("#filtre-taula");
    const aplicaFiltre = debounce(() => {
        state.filtreText = filtreInput.value.trim();
        renderLlistaCarregues();
    }, 150);
    filtreInput.addEventListener("input", aplicaFiltre);

    // Ordenació
    $$("#taula-carregues thead th[data-sort]").forEach(th => {
        th.addEventListener("click", () => ordenarPer(th.dataset.sort));
    });
    $$("#taula-productes thead th[data-sort]").forEach(th => {
        th.addEventListener("click", () => ordenarProductesPer(th.dataset.sort));
    });

    // Empty state - ampliar setmana
    const btnAmplia = $("#btn-amplia-setmana");
    if (btnAmplia) btnAmplia.addEventListener("click", () => aplicaFiltreRapid("last-week"));

    // Help dialog
    const dlg = $("#help-dialog");
    $("#btn-help").addEventListener("click", () => dlg.showModal());
    dlg.querySelector("[data-close]").addEventListener("click", () => dlg.close());
    dlg.addEventListener("click", (e) => {
        if (e.target === dlg) dlg.close();
    });

    setupKeyboard();

    // Auto-cerca si tenim dates vàlides i prefs guardades
    if (prefs.desde && prefs.fins && validarFormulari()) {
        // petit retard perquè es vegi la UI inicial
        setTimeout(() => buscarCarregues(), 100);
    }
});

})();
