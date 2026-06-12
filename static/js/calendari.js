// =====================================================================
// Calendari mensual de càrregues
// Grid de Dilluns a Divendres (les càrregues de DS/DG, si n'hi ha, surten
// a una secció separada sota el grid).
// Click sobre una càrrega → obre dialog modal amb el detall.
// =====================================================================
(function () {
    "use strict";

    const $ = (sel, root) => (root || document).querySelector(sel);

    const fmtKg0 = new Intl.NumberFormat("ca-ES", { maximumFractionDigits: 0 });
    const fmtKg2 = new Intl.NumberFormat("ca-ES", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    const fmtNum = new Intl.NumberFormat("ca-ES");
    const fmtMes = new Intl.DateTimeFormat("ca-ES", { month: "long", year: "numeric" });
    const fmtDiaLlarg = new Intl.DateTimeFormat("ca-ES", { weekday: "long", day: "numeric", month: "long" });

    function capitalitzar(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
    function escapeHtml(s) {
        return String(s == null ? "" : s).replace(/[&<>"']/g, ch => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[ch]));
    }
    function pad(n) { return String(n).padStart(2, "0"); }
    function isoLocal(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
    function ferDataLocal(any, mes, dia) { return new Date(any, mes - 1, dia, 0, 0, 0, 0); }
    function diaSetmana(d) {
        // 0 = dilluns, 6 = diumenge
        return (d.getDay() + 6) % 7;
    }
    function dilluns(d) {
        const x = new Date(d);
        x.setDate(x.getDate() - diaSetmana(x));
        x.setHours(0, 0, 0, 0);
        return x;
    }

    function rangMesVisible(any, mes) {
        // Sempre 6 setmanes (42 dies). El grid només renderitza Dl-Dv,
        // però fetch-egem dades de la setmana sencera per detectar càrregues
        // a DS/DG i mostrar-les a la secció de cap de setmana.
        const primer = ferDataLocal(any, mes, 1);
        const inici = new Date(primer);
        inici.setDate(primer.getDate() - diaSetmana(primer));
        const fi = new Date(inici);
        fi.setDate(inici.getDate() + 41);
        return { inici, fi };
    }

    function kgDeCarrega(c) {
        const k = Number(c.kg_total) || 0;
        if (k > 0) return k;
        const t = Number(c.car_pesoteorico) || 0;
        if (t > 0) return t;
        return Number(c.car_pesonetocarga) || 0;
    }

    // ---------------------------------------------------------------
    // Estat
    // ---------------------------------------------------------------
    const state = {
        any_: 0,
        mes: 0,
        diaInici: null,        // primer dilluns visible
        diaFi: null,           // últim diumenge visible
        carreguesPerDia: new Map(),   // isoDate -> Carrega[]   (només Dl-Dv)
        capSetmana: [],        // càrregues DS/DG dins el mes actual
        totalsCount: 0,
        totalsKg: 0,
        abortCtrl: null,
        modalAbort: null,
        scrollPendent: true,   // primer render: scrolla a la setmana actual
    };

    // ---------------------------------------------------------------
    // Fetch llista de càrregues
    // ---------------------------------------------------------------
    async function carregaMes() {
        if (state.abortCtrl) state.abortCtrl.abort();
        const ctrl = new AbortController();
        state.abortCtrl = ctrl;

        $("#cal-loading").hidden = false;
        $("#cal-error").hidden = true;

        const desde = isoLocal(state.diaInici);
        const fins  = isoLocal(state.diaFi);
        const url = `/api/carregues?desde=${desde}&fins=${fins}&limit=1000`;

        try {
            const resp = await fetch(url, { signal: ctrl.signal, credentials: "same-origin" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            agruparPerDia(data.items || []);
            renderGrid();
            renderCapSetmana();
            renderStats();
        } catch (e) {
            if (e.name === "AbortError") return;
            console.error(e);
            const err = $("#cal-error");
            err.textContent = `No s'ha pogut carregar el calendari: ${e.message}`;
            err.hidden = false;
            state.carreguesPerDia.clear();
            state.capSetmana = [];
            renderGrid();
            renderCapSetmana();
        } finally {
            if (state.abortCtrl === ctrl) state.abortCtrl = null;
            $("#cal-loading").hidden = true;
        }
    }

    function agruparPerDia(items) {
        const perDia = new Map();
        const capSetmana = [];
        let nMes = 0, kgMes = 0;
        for (const c of items) {
            if (!c.car_fecsalida) continue;
            const key = String(c.car_fecsalida).slice(0, 10);
            const [yy, mm, dd] = key.split("-").map(Number);
            const data = new Date(yy, mm - 1, dd);
            const ws = diaSetmana(data);
            const enMesActual = (yy === state.any_ && mm === state.mes);
            if (ws >= 5) {
                if (enMesActual) capSetmana.push({ data: key, ws, c });
            } else {
                if (!perDia.has(key)) perDia.set(key, []);
                perDia.get(key).push(c);
            }
            if (enMesActual) {
                nMes++;
                kgMes += kgDeCarrega(c);
            }
        }
        for (const arr of perDia.values()) {
            arr.sort((a, b) => (a.car_descripcion || "").localeCompare(b.car_descripcion || "", "ca"));
        }
        capSetmana.sort((a, b) => a.data.localeCompare(b.data));
        state.carreguesPerDia = perDia;
        state.capSetmana = capSetmana;
        state.totalsCount = nMes;
        state.totalsKg = kgMes;
    }

    // ---------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------
    function actualitzaTitol() {
        const d = ferDataLocal(state.any_, state.mes, 1);
        $("#cal-titol").textContent = capitalitzar(fmtMes.format(d));
    }

    function renderStats() {
        const txt = state.totalsCount === 0
            ? "Cap càrrega aquest mes"
            : `${state.totalsCount} càrregues · ${fmtKg0.format(state.totalsKg)} kg`;
        $("#cal-stats-text").textContent = txt;
    }

    function renderGrid() {
        const grid = $("#cal-grid");
        const avuiIso = isoLocal(new Date());
        const avuiSetmanaIso = isoLocal(dilluns(new Date()));
        const frag = document.createDocumentFragment();
        let primeraCelaSetmanaActual = null;

        // 6 setmanes × 5 dies = 30 cel·les (només Dl-Dv).
        let d = new Date(state.diaInici);
        for (let i = 0; i < 42; i++) {
            const ws = diaSetmana(d);
            if (ws < 5) {  // dilluns(0) a divendres(4) — saltem DS/DG
                const iso = isoLocal(d);
                const mesActual = (d.getMonth() + 1 === state.mes && d.getFullYear() === state.any_);
                const isToday = iso === avuiIso;
                const isCurrentWeek = isoLocal(dilluns(d)) === avuiSetmanaIso;
                const llista = state.carreguesPerDia.get(iso) || [];

                const cell = document.createElement("div");
                cell.className = "cal-cell"
                    + (mesActual ? "" : " is-other-month")
                    + (isToday ? " is-today" : "")
                    + (isCurrentWeek ? " is-current-week" : "");
                cell.setAttribute("role", "gridcell");
                cell.dataset.date = iso;
                if (isCurrentWeek && !primeraCelaSetmanaActual) primeraCelaSetmanaActual = cell;

                const head = document.createElement("div");
                head.className = "cal-cell-head";
                const num = document.createElement("span");
                num.className = "cal-cell-num";
                num.textContent = String(d.getDate());
                head.appendChild(num);

                if (llista.length > 0) {
                    const badge = document.createElement("span");
                    badge.className = "cal-cell-badge";
                    badge.textContent = String(llista.length);
                    badge.title = `${llista.length} càrregues`;
                    head.appendChild(badge);

                    const sumKg = llista.reduce((acc, c) => acc + kgDeCarrega(c), 0);
                    if (sumKg > 0) {
                        const kgSpan = document.createElement("span");
                        kgSpan.className = "cal-cell-kg";
                        kgSpan.textContent = `${fmtKg0.format(sumKg)} kg`;
                        kgSpan.title = `Total: ${fmtKg2.format(sumKg)} kg`;
                        head.appendChild(kgSpan);
                    }
                }
                cell.appendChild(head);

                if (llista.length > 0) {
                    const ul = document.createElement("ul");
                    ul.className = "cal-cell-list";
                    for (const c of llista) ul.appendChild(renderEvent(c, iso));
                    cell.appendChild(ul);
                }
                frag.appendChild(cell);
            }
            d.setDate(d.getDate() + 1);
        }
        grid.innerHTML = "";
        grid.appendChild(frag);

        if (state.scrollPendent && primeraCelaSetmanaActual) {
            // Primer render o "Avui": porta la fila de la setmana actual a la vista.
            // `behavior: 'auto'` (instant) per no fer scroll animat molest al carregar.
            primeraCelaSetmanaActual.scrollIntoView({ behavior: "auto", block: "center" });
            state.scrollPendent = false;
        }
    }

    function renderEvent(c, isoData) {
        const li = document.createElement("li");
        li.className = "cal-evt";
        li.tabIndex = 0;
        li.dataset.id = c.carrega_id || "";
        li.dataset.data = isoData;
        if (c.palletitzable === false) li.classList.add("is-no-palletitzable");

        const nom = (c.car_descripcion || "").trim() || c.carrega_id || "—";
        const kg = kgDeCarrega(c);
        const transp = (c.transportista || c.tra_codi || "").trim();
        const bits = [nom];
        if (transp) bits.push(transp);
        if (kg > 0) bits.push(`${fmtKg2.format(kg)} kg`);
        bits.push(`Càrrega ${c.carrega_id}`);
        li.title = bits.join(" · ");

        const sNom = document.createElement("span");
        sNom.className = "cal-evt-nom";
        sNom.textContent = nom;
        li.appendChild(sNom);

        if (kg > 0) {
            const sKg = document.createElement("span");
            sKg.className = "cal-evt-kg";
            sKg.textContent = `${fmtKg0.format(kg)} kg`;
            li.appendChild(sKg);
        }
        return li;
    }

    function renderCapSetmana() {
        const sec = $("#cal-capsetmana");
        const ul  = $("#cal-capsetmana-llista");
        if (state.capSetmana.length === 0) {
            sec.hidden = true;
            ul.innerHTML = "";
            return;
        }
        sec.hidden = false;
        $("#cal-capsetmana-comptador").textContent = String(state.capSetmana.length);

        const html = state.capSetmana.map(({ data, ws, c }) => {
            const nom = (c.car_descripcion || "").trim() || c.carrega_id || "—";
            const kg = kgDeCarrega(c);
            const [yy, mm, dd] = data.split("-").map(Number);
            const dataObj = new Date(yy, mm - 1, dd);
            const dataTxt = capitalitzar(fmtDiaLlarg.format(dataObj));
            const transp = (c.transportista || c.tra_codi || "").trim();
            const kgHtml = kg > 0 ? `<span class="cal-cs-kg">${escapeHtml(fmtKg0.format(kg))} kg</span>` : "";
            const transpHtml = transp ? `<span class="cal-cs-tra muted">${escapeHtml(transp)}</span>` : "";
            const npClass = c.palletitzable === false ? " is-no-palletitzable" : "";
            return `<li class="cal-cs-item${npClass}" data-id="${escapeHtml(c.carrega_id)}" data-data="${escapeHtml(data)}" tabindex="0" title="Càrrega ${escapeHtml(c.carrega_id)}">
                <span class="cal-cs-data">${escapeHtml(dataTxt)}</span>
                <span class="cal-cs-nom">${escapeHtml(nom)}</span>
                ${transpHtml}
                ${kgHtml}
            </li>`;
        }).join("");
        ul.innerHTML = html;
    }

    // ---------------------------------------------------------------
    // Modal: detall d'una càrrega
    // ---------------------------------------------------------------
    async function obrirModal(carregaId) {
        if (!carregaId) return;
        const [eje, sca, car] = carregaId.split("/");
        if (!eje || !sca || !car) return;

        if (state.modalAbort) state.modalAbort.abort();
        const ctrl = new AbortController();
        state.modalAbort = ctrl;

        const dlg = $("#cal-modal");
        $("#cal-modal-titol").textContent = `Càrrega ${carregaId}`;
        $("#cal-modal-meta").innerHTML = "";
        $("#cal-modal-body").innerHTML = `<div class="muted cal-modal-loading"><span class="cal-spinner"></span> Carregant detall…</div>`;
        if (typeof dlg.showModal === "function") dlg.showModal();
        else dlg.setAttribute("open", "");

        // Capçalera: troba la càrrega al state per omplir meta sense esperar fetch
        const localItem = trobaCarreguaLocal(carregaId);
        if (localItem) renderModalMeta(localItem);

        try {
            const params = new URLSearchParams({ eje, sca, car });
            const resp = await fetch(`/api/carrega-detall?${params}`, { signal: ctrl.signal, credentials: "same-origin" });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            $("#cal-modal-body").innerHTML = renderDetallCarrega(data);
        } catch (e) {
            if (e.name === "AbortError") return;
            $("#cal-modal-body").innerHTML = `<div class="cal-error">Error carregant detall: ${escapeHtml(e.message)}</div>`;
        } finally {
            if (state.modalAbort === ctrl) state.modalAbort = null;
        }
    }

    function trobaCarreguaLocal(carregaId) {
        for (const arr of state.carreguesPerDia.values()) {
            const found = arr.find(c => c.carrega_id === carregaId);
            if (found) return found;
        }
        const cs = state.capSetmana.find(x => x.c.carrega_id === carregaId);
        return cs ? cs.c : null;
    }

    function renderModalMeta(c) {
        const data = c.car_fecsalida || c.car_fecha || "";
        const [yy, mm, dd] = (data || "").split("-").map(Number);
        const dataTxt = (yy && mm && dd) ? capitalitzar(fmtDiaLlarg.format(new Date(yy, mm - 1, dd))) : "";
        const transp = (c.transportista || c.tra_codi || "").trim();
        const matricula = (c.car_matricula || "").trim();
        const conductor = (c.car_nomconductor || "").trim();
        const kg = kgDeCarrega(c);
        const descripcio = (c.car_descripcion || "").trim();
        const meta = [
            descripcio ? `<div class="cal-modal-meta-row"><strong>${escapeHtml(descripcio)}</strong></div>` : "",
            dataTxt ? `<div class="cal-modal-meta-row"><span class="muted">Sortida:</span> ${escapeHtml(dataTxt)}</div>` : "",
            transp ? `<div class="cal-modal-meta-row"><span class="muted">Transportista:</span> ${escapeHtml(transp)}</div>` : "",
            matricula ? `<div class="cal-modal-meta-row"><span class="muted">Matrícula:</span> ${escapeHtml(matricula)}</div>` : "",
            conductor ? `<div class="cal-modal-meta-row"><span class="muted">Conductor:</span> ${escapeHtml(conductor)}</div>` : "",
            kg > 0 ? `<div class="cal-modal-meta-row"><span class="muted">Pes total:</span> <strong>${escapeHtml(fmtKg2.format(kg))} kg</strong></div>` : "",
        ].filter(Boolean).join("");
        $("#cal-modal-meta").innerHTML = meta;
    }

    function renderDetallCarrega(data) {
        if (!data.albarans || data.albarans.length === 0) {
            return `<div class="muted">Aquesta càrrega no té albarans associats.</div>`;
        }
        const blocks = data.albarans.map(a => {
            const linies = a.linies.map(l => {
                const np = l.palletitzable === false;
                const cls = np ? ' class="not-palletitzable"' : '';
                const tip = np ? ' title="No palletitzable: el motor d&apos;embalatges ignora aquesta línia"' : '';
                return `<tr${cls}${tip}>
                    <td><code>${escapeHtml(l.art_codi)}</code></td>
                    <td>${escapeHtml(l.art_descrip)}</td>
                    <td>${escapeHtml(l.tunitat)}</td>
                    <td class="num">${fmtNum.format(l.sacs)}</td>
                    <td class="num">${fmtKg0.format(l.kg)}</td>
                </tr>`;
            }).join("");
            const tipoBadge = a.det_tipo === "P"
                ? `<span class="badge badge-warn" title="Comanda pendent">P</span>`
                : `<span class="badge badge-ok" title="Albarà">A</span>`;
            const poblaHtml = a.pobla
                ? `<span class="albara-pobla" title="Població d'enviament"><span aria-hidden="true">📍</span> ${escapeHtml(a.pobla)}</span>`
                : "";
            return `
                <div class="albara-block">
                    <h4>
                        <span><code>${escapeHtml(a.albara)}</code> ${tipoBadge} · ${escapeHtml(a.cli_codi)} ${escapeHtml(a.cli_nom)}${poblaHtml ? " · " + poblaHtml : ""}</span>
                        <span class="muted">${fmtNum.format(a.total_sacs)} sacs · ${fmtKg0.format(a.total_kg)} kg</span>
                    </h4>
                    <table class="data-table data-table-mini">
                        <thead><tr><th>Article</th><th>Descripció</th><th>TUnitat</th><th class="num">Sacs</th><th class="num">Kg</th></tr></thead>
                        <tbody>${linies || `<tr><td colspan="5" class="muted">Sense línies</td></tr>`}</tbody>
                    </table>
                </div>`;
        }).join("");
        return `<div class="detall-resum muted">${data.albarans.length} albarans · <strong>${fmtNum.format(data.total_sacs)}</strong> sacs · <strong>${fmtKg0.format(data.total_kg)}</strong> kg</div>${blocks}`;
    }

    function tancarModal() {
        const dlg = $("#cal-modal");
        if (typeof dlg.close === "function") dlg.close();
        else dlg.removeAttribute("open");
        if (state.modalAbort) { state.modalAbort.abort(); state.modalAbort = null; }
    }

    // ---------------------------------------------------------------
    // Navegació
    // ---------------------------------------------------------------
    function anarA(any, mes) {
        state.any_ = any;
        state.mes = mes;
        const { inici, fi } = rangMesVisible(any, mes);
        state.diaInici = inici;
        state.diaFi = fi;
        actualitzaTitol();
        carregaMes();
    }
    function anarMes(delta) {
        let m = state.mes + delta, y = state.any_;
        while (m < 1) { m += 12; y--; }
        while (m > 12) { m -= 12; y++; }
        anarA(y, m);
    }
    function anarAvui() {
        state.scrollPendent = true;
        const t = new Date();
        anarA(t.getFullYear(), t.getMonth() + 1);
    }

    // ---------------------------------------------------------------
    // Bootstrap
    // ---------------------------------------------------------------
    function init() {
        const t = new Date();
        anarA(t.getFullYear(), t.getMonth() + 1);

        $("#cal-prev").addEventListener("click", () => anarMes(-1));
        $("#cal-next").addEventListener("click", () => anarMes(1));
        $("#cal-avui").addEventListener("click", anarAvui);

        document.addEventListener("keydown", (e) => {
            if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
            const dlg = $("#cal-modal");
            if (dlg && dlg.hasAttribute("open")) return;  // tecles dins el modal: deixa que <dialog> gestioni Esc
            if (e.key === "ArrowLeft") { e.preventDefault(); anarMes(-1); }
            else if (e.key === "ArrowRight") { e.preventDefault(); anarMes(1); }
            else if (e.key === "Home") { e.preventDefault(); anarAvui(); }
        });

        const grid = $("#cal-grid");
        const onClickEvt = (e) => {
            const evt = e.target.closest(".cal-evt, .cal-cs-item");
            if (!evt) return;
            obrirModal(evt.dataset.id);
        };
        grid.addEventListener("click", onClickEvt);
        $("#cal-capsetmana-llista").addEventListener("click", onClickEvt);

        const onKeyEvt = (e) => {
            if (e.key !== "Enter" && e.key !== " ") return;
            const evt = e.target.closest(".cal-evt, .cal-cs-item");
            if (!evt) return;
            e.preventDefault();
            obrirModal(evt.dataset.id);
        };
        grid.addEventListener("keydown", onKeyEvt);
        $("#cal-capsetmana-llista").addEventListener("keydown", onKeyEvt);

        // Modal: tanca amb X o clic fora
        const dlg = $("#cal-modal");
        $("#cal-modal-close").addEventListener("click", tancarModal);
        dlg.addEventListener("click", (e) => {
            // Click sobre el backdrop (fora del <article>) tanca
            if (e.target === dlg) tancarModal();
        });
        dlg.addEventListener("close", () => {
            if (state.modalAbort) { state.modalAbort.abort(); state.modalAbort = null; }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
