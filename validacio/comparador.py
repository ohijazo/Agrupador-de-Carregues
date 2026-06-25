"""Comparador entre el PDF d'una ordre de càrrega i el que retorna l'app.

Donat un `OrdreCarregaPdf` extret del PDF i el `resum_carrega` del sistema,
retorna una llista de `Discrepancia` que descriuen què no coincideix. Pensat
per ser cridat per un worker en segon pla cada cop que arribi un nou correu
de KAIS amb un PDF adjunt.

Severitat:
  - "info"    → diferències menors esperades (palets ±1 kg, dades modificades
                a KAIS després d'imprimir el PDF en pocs kg).
  - "warning" → diferències moderades (kg total > 1% però < 10%, sacs ±5).
  - "error"   → diferències grans (kg total > 10%, pedido sense match, client
                discrepant, càrrega no trobada al sistema).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from .pdf_parser import OrdreCarregaPdf, ComandaPdf


# Umbrals.
TOLERANCIA_KG_INFO = 30.0       # ≤30 kg = info (palets, diferències d'arrodoniment)
TOLERANCIA_KG_PCT_WARN = 0.01   # 1%
TOLERANCIA_KG_PCT_ERR = 0.10    # 10%


@dataclass
class Discrepancia:
    severitat: str
    tipus: str
    detall: str
    pdf: Optional[str] = None
    sistema: Optional[str] = None
    pedido_pdf: Optional[str] = None       # 'EJE/SAL/ALB' del PDF
    pedido_sistema: Optional[str] = None   # 'SAL/ALB' del sistema (sal_real)


def _norm(s: str) -> str:
    """Normalitza un nom de client per comparar: majúscules, sense espais
    duplicats, sense puntuació superficial. Permissiu per cassos com
    'FORN DE LA TIETA, SL. (BONAPARTE)' vs 'FORN DE LA TIETA, SL.'."""
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"[\s.,\-/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _arrel_nom(s: str) -> str:
    """Talla el nom abans del primer separador d'anotacions (`,`, `(`, `;`)
    i normalitza. Convertir 'FARINA I SUCRE PRATS BRASÓ (MAG.)' o
    'FARINA I SUCRE PRATS BRASÓ, S.L.' tots dos en 'FARINA I SUCRE PRATS BRASO'."""
    if not s:
        return ""
    s = s.upper()
    s = re.split(r"[(,;]", s, maxsplit=1)[0]
    return _norm(s)


def _clients_coincideixen(a: str, b: str) -> bool:
    """True si dos noms de client són raonablement el mateix.

    Permet variants com `S.L.` vs `SL`, `(MAG.)` afegit/treure, espais.
    Estratègia: comparar primer els noms sencers normalitzats; si no casen,
    comparar només l'arrel (abans de `,` o `(`).
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # Comparació per arrel (talla coma/parèntesi i la resta de sufix).
    ra, rb = _arrel_nom(a), _arrel_nom(b)
    if ra and rb and ra == rb:
        return True
    return False


def _pct(num: float, denom: float) -> float:
    return abs(num) / denom if denom else 0.0


def comparar(pdf: OrdreCarregaPdf, sistema: dict) -> list[Discrepancia]:
    """Compara un PDF parsejat amb el resultat de `resum_carrega(eje, sca, car)`.

    Retorna una llista de discrepàncies (buida si tot quadra).
    """
    out: list[Discrepancia] = []

    # --- 0. Càrrega trobada? ---
    if not sistema or "comandes" not in sistema:
        out.append(Discrepancia(
            severitat="error",
            tipus="carrega_no_trobada",
            detall="L'app no té dades per a aquesta càrrega.",
        ))
        return out

    # --- 1. Total kg ---
    pdf_kg = float(pdf.total_quan or 0)
    sis_kg = float(sistema.get("total_kg") or 0)
    diff_kg = sis_kg - pdf_kg
    if abs(diff_kg) > TOLERANCIA_KG_INFO:
        pct = _pct(diff_kg, pdf_kg) if pdf_kg else 1.0
        if pct >= TOLERANCIA_KG_PCT_ERR:
            sev = "error"
        elif pct >= TOLERANCIA_KG_PCT_WARN:
            sev = "warning"
        else:
            sev = "info"
        out.append(Discrepancia(
            severitat=sev,
            tipus="kg_total",
            detall=f"Diferència de {diff_kg:+.0f} kg ({pct*100:.1f}%)",
            pdf=f"{pdf_kg:.0f}",
            sistema=f"{sis_kg:.0f}",
        ))

    # --- 2. Total sacs ---
    pdf_sacs = float(pdf.total_sacs or 0)
    sis_sacs = float(sistema.get("total_sacs") or 0)
    diff_sacs = sis_sacs - pdf_sacs
    if abs(diff_sacs) >= 1:
        out.append(Discrepancia(
            severitat="warning" if abs(diff_sacs) <= 5 else "error",
            tipus="sacs_total",
            detall=f"Diferència de {diff_sacs:+.0f} sacs",
            pdf=f"{pdf_sacs:.0f}",
            sistema=f"{sis_sacs:.0f}",
        ))

    # --- 3. Matching de pedidos (per client + cpa_albara) ---
    sistema_pedidos = sistema.get("comandes", [])

    # Tag pedidos del sistema com a "no vistos" inicialment.
    sistema_unmatched = list(range(len(sistema_pedidos)))

    for cmd_pdf in pdf.comandes:
        # 3a. Provem match per cpa_albara visible al PDF vs el comanda al sistema.
        # Els numeros sovint NO coincideixen (PDF mostra pedi_num KAIS, sistema
        # mostra cpa_albara intern), però intentem-ho primer per si coincideixen.
        eje_pdf, sal_pdf, alb_pdf = (cmd_pdf.pedido or "0000/00/0000000").split("/")

        match_idx = None
        for i in sistema_unmatched:
            sis = sistema_pedidos[i]
            sis_pedido = sis.get("comanda", "")
            sis_sal, sis_alb = (sis_pedido.split("/") + ["", ""])[:2]
            # Match estricte per cpa_albara (poc freqüent però possible).
            if sis_alb == alb_pdf:
                match_idx = i
                break

        if match_idx is None:
            # 3b. Fallback: match per cli_nom normalitzat.
            for i in sistema_unmatched:
                sis = sistema_pedidos[i]
                if _clients_coincideixen(cmd_pdf.cli_nom, sis.get("cli_nom", "")):
                    match_idx = i
                    break

        if match_idx is None:
            out.append(Discrepancia(
                severitat="error",
                tipus="pedido_no_trobat_sistema",
                detall=f"Pedido {cmd_pdf.pedido} ({cmd_pdf.cli_nom}) del PDF no apareix al sistema.",
                pedido_pdf=cmd_pdf.pedido,
            ))
            continue

        sistema_unmatched.remove(match_idx)
        sis = sistema_pedidos[match_idx]

        # 3c. Validar client (si tenim match per cpa_albara però el client difereix).
        if not _clients_coincideixen(cmd_pdf.cli_nom, sis.get("cli_nom", "")):
            out.append(Discrepancia(
                severitat="error",
                tipus="client_difereix",
                detall=f"Client diferent per al mateix pedido: PDF='{cmd_pdf.cli_nom}' vs sistema='{sis.get('cli_nom', '')}'",
                pdf=cmd_pdf.cli_nom,
                sistema=sis.get("cli_nom", ""),
                pedido_pdf=cmd_pdf.pedido,
                pedido_sistema=sis.get("comanda"),
            ))

        # 3d. Validar kg per pedido.
        sis_kg_p = float(sis.get("total_kg") or 0)
        diff_kg_p = sis_kg_p - cmd_pdf.sub_quan
        if abs(diff_kg_p) > TOLERANCIA_KG_INFO:
            pct_p = _pct(diff_kg_p, cmd_pdf.sub_quan) if cmd_pdf.sub_quan else 1.0
            if pct_p >= TOLERANCIA_KG_PCT_ERR:
                sev = "error"
            elif pct_p >= TOLERANCIA_KG_PCT_WARN:
                sev = "warning"
            else:
                sev = "info"
            out.append(Discrepancia(
                severitat=sev,
                tipus="kg_pedido",
                detall=f"Pedido {cmd_pdf.pedido} ({cmd_pdf.cli_nom}): {diff_kg_p:+.0f} kg ({pct_p*100:.1f}%)",
                pdf=f"{cmd_pdf.sub_quan:.0f}",
                sistema=f"{sis_kg_p:.0f}",
                pedido_pdf=cmd_pdf.pedido,
                pedido_sistema=sis.get("comanda"),
            ))

    # 3e. Pedidos al sistema que NO apareixen al PDF.
    for i in sistema_unmatched:
        sis = sistema_pedidos[i]
        out.append(Discrepancia(
            severitat="error",
            tipus="pedido_extra_sistema",
            detall=f"Pedido {sis.get('comanda', '?')} ({sis.get('cli_nom', '?')}) està al sistema però no al PDF.",
            pedido_sistema=sis.get("comanda"),
        ))

    return out


def resum_severitat(discrepancies: list[Discrepancia]) -> str:
    """Retorna la severitat més alta: 'ok' < 'info' < 'warning' < 'error'."""
    ordre = {"ok": 0, "info": 1, "warning": 2, "error": 3}
    if not discrepancies:
        return "ok"
    return max(discrepancies, key=lambda d: ordre.get(d.severitat, 0)).severitat


def serialitzar(discrepancies: list[Discrepancia]) -> list[dict]:
    return [asdict(d) for d in discrepancies]
