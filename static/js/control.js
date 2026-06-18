// Pantalla /control — seguiment d'agrupacions amb traçabilitat de preparació.
(function () {
    "use strict";

    const POLL_MS = 15_000;

    const $ = (sel) => document.querySelector(sel);

    let dades = [];
    let pollTimer = null;

    function escapeM(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[c]));
    }

    function fmtHoraCurta(iso) {
        if (!iso) return "—";
        const d = new Date(iso);
        if (isNaN(d)) return "—";
        return d.toLocaleTimeString("ca-ES", { hour: "2-digit", minute: "2-digit" });
    }

    function fmtDurada(s) {
        if (s == null) return "—";
        if (s < 60) return "<1 min";
        const m = Math.floor(s / 60);
        if (m < 60) return `${m} min`;
        const h = Math.floor(m / 60);
        const mr = m % 60;
        return mr ? `${h}h ${mr}min` : `${h}h`;
    }

    function badgeEstat(estat) {
        const map = {
            pendent: { txt: "Pendent", cls: "ctrl-badge-pendent" },
            en_curs: { txt: "En curs", cls: "ctrl-badge-en-curs" },
            acabada: { txt: "Acabada", cls: "ctrl-badge-acabada" },
        };
        const m = map[estat] || { txt: estat, cls: "" };
        return `<span class="ctrl-badge ${m.cls}">${escapeM(m.txt)}</span>`;
    }

    function avuiISO() {
        const d = new Date();
        const y = d.getFullYear();
        const mo = String(d.getMonth() + 1).padStart(2, "0");
        const dy = String(d.getDate()).padStart(2, "0");
        return `${y}-${mo}-${dy}`;
    }

    function filtrar(items) {
        const estat = $("#ctrl-estat").value;
        const nomesAvui = $("#ctrl-nomes-avui").checked;
        const today = avuiISO();
        return items.filter((it) => {
            if (estat && it.estat !== estat) return false;
            if (nomesAvui && !(it.ts || "").startsWith(today)) return false;
            return true;
        });
    }

    function pinta() {
        const tbody = $("#ctrl-tbody");
        const buit = $("#ctrl-buit");
        const count = $("#ctrl-count");
        const items = filtrar(dades);
        count.textContent = `${items.length} / ${dades.length}`;
        if (!items.length) {
            tbody.innerHTML = "";
            buit.hidden = false;
            return;
        }
        buit.hidden = true;
        tbody.innerHTML = items.map((it) => {
            const progres = `${it.n_preparats || 0} / ${it.n_productes || 0}`;
            return `<tr>
                <td><a href="/magatzem/${encodeURIComponent(it.id)}" class="ctrl-nom">${escapeM(it.nom)}</a></td>
                <td>${escapeM(fmtData(it.ts))}</td>
                <td>${escapeM(it.created_by_nom || "—")}</td>
                <td class="num">${escapeM(progres)}</td>
                <td>${badgeEstat(it.estat)}</td>
                <td>${escapeM(fmtHoraCurta(it.prep_iniciat))}</td>
                <td>${escapeM(fmtHoraCurta(it.prep_finalitzat))}</td>
                <td>${escapeM(fmtDurada(it.durada_s))}</td>
                <td>${escapeM(it.prep_per_nom || "—")}</td>
            </tr>`;
        }).join("");
    }

    async function carregar() {
        try {
            const r = await fetch("/api/control/agrupacions", { credentials: "same-origin" });
            if (!r.ok) {
                console.warn("control: HTTP", r.status);
                return;
            }
            dades = await r.json();
            pinta();
        } catch (e) {
            console.warn("control: fetch error", e);
        }
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(carregar, POLL_MS);
    }

    document.addEventListener("DOMContentLoaded", () => {
        $("#ctrl-estat").addEventListener("change", pinta);
        $("#ctrl-nomes-avui").addEventListener("change", pinta);
        carregar();
        startPolling();
    });

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") carregar();
    });
})();
