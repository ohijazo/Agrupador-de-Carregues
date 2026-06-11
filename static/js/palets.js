// Helpers compartits per al format de palets desglosats.
// Carregat per app.js i magatzem.js abans del seu propi codi.
(function (global) {
    "use strict";

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

    // Genera el text amb claudàtors per a una càrrega d'un producte.
    // Un sol tipus    → "[1×42][1×44] EU"   (tipus al final, no es repeteix)
    // Tipus barrejats → "[1×42 EU][1×22 PL]" (cada grup amb el seu tipus dins)
    // Un sol grup     → "[1×9 BASE]"
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
            const peces = llista.map(g => `[${g.n}×${g.sacs}]`).join("");
            return ab ? `${peces} ${ab}` : peces;
        }
        return llista.map(g => {
            const ab = abreviarTipusPalet(g.descrip);
            return ab ? `[${g.n}×${g.sacs} ${ab}]` : `[${g.n}×${g.sacs}]`;
        }).join("");
    }

    global.abreviarTipusPalet = abreviarTipusPalet;
    global.detallPaletsCarrega = detallPaletsCarrega;

    if (typeof module !== "undefined" && module.exports) {
        module.exports = { abreviarTipusPalet, detallPaletsCarrega };
    }
})(typeof window !== "undefined" ? window : globalThis);
