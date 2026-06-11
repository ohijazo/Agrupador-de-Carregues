// Funcions de format reutilitzables (carregat abans de app.js, també importable des de tests Node).
(function (global) {
    "use strict";

    function fmtData(v) {
        if (v == null || v === "") return "";
        if (v instanceof Date) {
            const dd = String(v.getDate()).padStart(2, "0");
            const mm = String(v.getMonth() + 1).padStart(2, "0");
            return `${dd}-${mm}-${v.getFullYear()}`;
        }
        const s = String(v).trim();
        const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
        if (m) return `${m[3]}-${m[2]}-${m[1]}`;
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

    global.fmtData = fmtData;
    global.fmtDataHora = fmtDataHora;

    // Compatibilitat amb mòduls CommonJS (per tests Node sense canvis a HTML)
    if (typeof module !== "undefined" && module.exports) {
        module.exports = { fmtData, fmtDataHora };
    }
})(typeof window !== "undefined" ? window : globalThis);
