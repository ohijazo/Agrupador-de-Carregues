// Tests dels helpers de format (fmtData, fmtDataHora). Executar: `node --test tests/test_format.mjs`
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { fmtData, fmtDataHora } = require("../static/js/fmt.js");

test("fmtData ISO YYYY-MM-DD -> DD-MM-YYYY", () => {
    assert.equal(fmtData("2026-06-11"), "11-06-2026");
});

test("fmtData accepta ISO amb hora i només retorna data", () => {
    assert.equal(fmtData("2026-06-11T14:30:00"), "11-06-2026");
});

test("fmtData YYYY/MM/DD -> DD-MM-YYYY", () => {
    assert.equal(fmtData("2026/06/11"), "11-06-2026");
});

test("fmtData accepta Date", () => {
    const d = new Date(2026, 5, 11);  // Juny = mes 5 (0-based)
    assert.equal(fmtData(d), "11-06-2026");
});

test("fmtData retorna buit per null", () => {
    assert.equal(fmtData(null), "");
});

test("fmtData retorna buit per undefined", () => {
    assert.equal(fmtData(undefined), "");
});

test("fmtData retorna buit per string buit", () => {
    assert.equal(fmtData(""), "");
});

test("fmtData retorna l'entrada si no coincideix cap format", () => {
    assert.equal(fmtData("text-aleatori"), "text-aleatori");
});

test("fmtData fa padding del dia i mes < 10", () => {
    assert.equal(fmtData("2026-01-05"), "05-01-2026");
});

test("fmtData fa padding amb Date amb dia < 10", () => {
    const d = new Date(2026, 0, 5);
    assert.equal(fmtData(d), "05-01-2026");
});

test("fmtData espais al voltant es respecten", () => {
    assert.equal(fmtData("  2026-06-11  "), "11-06-2026");
});

test("fmtDataHora afegeix hora", () => {
    const d = new Date(2026, 5, 11, 14, 30);
    assert.equal(fmtDataHora(d), "11-06-2026 14:30");
});

test("fmtDataHora pad de minuts < 10", () => {
    const d = new Date(2026, 5, 11, 9, 5);
    assert.equal(fmtDataHora(d), "11-06-2026 09:05");
});

test("fmtDataHora accepta string ISO", () => {
    const r = fmtDataHora("2026-06-11T10:00:00");
    // El resultat pot variar lleugerament per fus horari local — comprova el patró
    assert.match(r, /^\d{2}-\d{2}-\d{4} \d{2}:\d{2}$/);
});
