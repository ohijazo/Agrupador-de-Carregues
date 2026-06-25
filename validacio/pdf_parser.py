"""Parser de l'ordre de càrrega PDF generada per KAIS.

KAIS envia automàticament un correu amb un PDF adjunt cada cop que es crea una
càrrega. Aquest mòdul extreu del PDF les dades estructurades (capçalera,
pedidos amb client/població/articles, totals) per poder comparar-les amb el
que retorna `consultes_carregues.resum_carrega` i detectar discrepàncies.

Format del PDF: capçalera amb número de càrrega, data, transportista, i
després un bloc per cada destí amb:
  Población: <CP> <CIUTAT>
  Nombre: <CLIENT>
  Domicilio: <ADREÇA>
  Ped.: <EJE>/<SAL>/<CPA_ALBARA>
  ...
  Article  Descripció  T.Unid.  Palets  Sacos  Cantidad
  ... línies ...
  Subtotal  <palets>  <sacs>  <kg>

Final del PDF:
  Total  <palets>  <sacs>  <kg>
  Entrega paletitzada / Entrega manual

API pública: `parsejar(path) -> dict` o `parsejar_bytes(data) -> dict`.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Optional

import pdfplumber


# Regex compilades una sola vegada al carregar el mòdul.
_RE_NUM_CARREGA = re.compile(r"ORDEN DE CARGA N[ÚU]M\.?:\s*(\d{4})/(\d{2})/(\d{7})")
_RE_FECHA_CARGA = re.compile(r"Fecha carga:\s*(\d{2}/\d{2}/\d{4})(?:\s+(\d{1,2}:\d{2}))?")
_RE_FECHA_ENTREGA = re.compile(r"Fecha entrega:\s*(\d{2}/\d{2}/\d{4})")
_RE_TRANSPORTISTA = re.compile(r"Transportista contractual:\s*(.+?)$", re.MULTILINE)
# La matrícula està a la mateixa línia que el label. Si està buida, no hem de
# capturar el contingut de la línia següent (era el bug que agafava "C/").
_RE_MATRICULA = re.compile(r"Matr[íi]cula veh[íi]culo:\s*([A-Z0-9\-]{4,12})")
# Descripció curta: línia centrada just després de "HORARIO DE CARGA DE...".
# Aquesta línia és tota en majúscules (sense ":") i no és cap dels camps fixos.
_RE_DESCRIPCIO = re.compile(
    r"HORARIO DE CARGA DE [^\n]+\n([^\n]+)",
)

_RE_POBLACIO = re.compile(r"Poblaci[óo]n:\s*(\d{5})\s+(.+?)$", re.MULTILINE)
_RE_NOMBRE = re.compile(r"Nombre:\s*(.+?)$", re.MULTILINE)
_RE_PEDIDO = re.compile(r"Ped\.?:\s*(\d{4})/(\d{2})/(\d{7})")

# Els PDFs de KAIS porten codis de barres `¨...¬` adjacents al text (sobretot
# als noms de client a les pàgines 2+). Cal netejar-los abans de processar.
# IMPORTANT: només consumim espais horitzontals als laterals (\h o [ \t]),
# mai \n, perquè altrament fusionaríem línies adjacents (Nombre/Domicilio).
_RE_BARCODE = re.compile(r"[ \t]*¨[^¨¬\n]*¬[ \t]*")

# Línia d'article: codi (4-5 dígits o lletres+dígits), descripció lliure,
# T.Unid. (UNI, GRA, S+dígits), palets (int), sacs (float), cantidad (float).
_RE_LINIA = re.compile(
    r"^(?P<art_codi>[A-Z0-9]{4,8})\s+"
    r"(?P<descrip>.+?)\s+"
    r"(?P<tunitat>UNI|GRA|S\d+)\s+"
    r"(?P<palets>\d+)\s+"
    r"(?P<sacs>-?[\d.]+)\s+"
    r"(?P<quan>-?[\d.]+)\s*$",
)

_RE_SUBTOTAL = re.compile(r"^Subtotal\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s*$")
_RE_TOTAL = re.compile(r"^Total\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s*$")
_RE_ENTREGA_PAL = re.compile(r"^Entrega paletitzada\s+([-\d.]+)\s*$")
_RE_ENTREGA_MAN = re.compile(r"^Entrega manual\s+([-\d.]+)\s*$")


@dataclass
class LiniaPdf:
    art_codi: str
    art_descrip: str
    tunitat: str
    palets: int = 0
    sacs: float = 0.0
    quan: float = 0.0    # "Cantidad" del PDF


@dataclass
class ComandaPdf:
    pedido: str = ""        # "eje/sal/cpa_albara" — el que el PDF anomena "Ped."
    cp: str = ""            # 5 dígits
    pobla: str = ""
    cli_nom: str = ""
    domicili: str = ""
    sub_palets: int = 0
    sub_sacs: float = 0.0
    sub_quan: float = 0.0
    linies: list[LiniaPdf] = field(default_factory=list)


@dataclass
class OrdreCarregaPdf:
    """Resultat estructurat del parsing del PDF."""
    carrega_id: str = ""           # "eje/sal/car_numero"
    eje: str = ""
    sca: str = ""
    car: str = ""
    descripcio: str = ""           # ex. "MATAS 1P SACS BCN"
    transportista: str = ""        # nom complet
    matricula: str = ""
    fecha_carga: Optional[str] = None     # ISO "YYYY-MM-DD"
    hora_carga: Optional[str] = None      # "HH:MM"
    fecha_entrega: Optional[str] = None   # ISO
    comandes: list[ComandaPdf] = field(default_factory=list)
    total_palets: int = 0
    total_sacs: float = 0.0
    total_quan: float = 0.0
    entrega_paletitzada: Optional[float] = None
    entrega_manual: Optional[float] = None


def _data_iso(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    d, m, y = s.split("/")
    return f"{y}-{m}-{d}"


def parsejar(path: str) -> OrdreCarregaPdf:
    """Parsa un PDF de l'ordre de càrrega i retorna l'estructura extreta."""
    with open(path, "rb") as f:
        return parsejar_bytes(f.read())


def parsejar_bytes(data: bytes) -> OrdreCarregaPdf:
    """Versió que accepta directament els bytes del PDF (per a Graph API)."""
    res = OrdreCarregaPdf()

    full_text = ""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            full_text += txt + "\n"
    # Treure els codis de barres `¨...¬` que pdfplumber concatena al text.
    full_text = _RE_BARCODE.sub(" ", full_text)

    # --- Capçalera (apareix igual a cada pàgina, només extraiem un cop) ---
    m = _RE_NUM_CARREGA.search(full_text)
    if m:
        res.eje, res.sca, res.car = m.group(1), m.group(2), m.group(3)
        res.carrega_id = f"{res.eje}/{res.sca}/{res.car}"

    m = _RE_FECHA_CARGA.search(full_text)
    if m:
        res.fecha_carga = _data_iso(m.group(1))
        res.hora_carga = m.group(2)
    m = _RE_FECHA_ENTREGA.search(full_text)
    if m:
        res.fecha_entrega = _data_iso(m.group(1))

    m = _RE_TRANSPORTISTA.search(full_text)
    if m:
        res.transportista = m.group(1).strip()

    m = _RE_MATRICULA.search(full_text)
    if m:
        res.matricula = m.group(1).strip()

    # Descripció curta (nom de la càrrega): és la línia just després de
    # "HORARIO DE CARGA DE ...". Exemples: "MATAS 1P SACS BCN", "VARIS TISA",
    # "ESCAPA PAL PRATS".
    m = _RE_DESCRIPCIO.search(full_text)
    if m:
        res.descripcio = m.group(1).strip()

    # --- Comandes ---
    # Estratègia: separar el text per blocs "Población:". Per cada bloc, extreure
    # nom, pedido, línies d'articles fins al Subtotal.
    blocks = re.split(r"(?=Poblaci[óo]n:\s*\d{5})", full_text)
    for block in blocks[1:]:  # blocks[0] és la capçalera abans del primer "Población:"
        cmd = ComandaPdf()
        m = _RE_POBLACIO.search(block)
        if m:
            cmd.cp = m.group(1)
            cmd.pobla = m.group(2).strip()
        m = _RE_NOMBRE.search(block)
        if m:
            cmd.cli_nom = m.group(1).strip()
        m = _RE_PEDIDO.search(block)
        if m:
            cmd.pedido = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

        # Línies d'articles + Subtotal
        for line in block.splitlines():
            line_strip = line.strip()
            mlin = _RE_LINIA.match(line_strip)
            if mlin:
                cmd.linies.append(LiniaPdf(
                    art_codi=mlin.group("art_codi"),
                    art_descrip=mlin.group("descrip").strip(),
                    tunitat=mlin.group("tunitat"),
                    palets=int(mlin.group("palets")),
                    sacs=float(mlin.group("sacs")),
                    quan=float(mlin.group("quan")),
                ))
                continue
            msub = _RE_SUBTOTAL.match(line_strip)
            if msub:
                cmd.sub_palets = int(msub.group(1))
                cmd.sub_sacs = float(msub.group(2))
                cmd.sub_quan = float(msub.group(3))
                # Tancat aquest bloc: stop early per evitar arrossegar línies d'altres comandes.
                break

        if cmd.pedido or cmd.cli_nom:
            res.comandes.append(cmd)

    # --- Totals globals ---
    for line in full_text.splitlines():
        line_strip = line.strip()
        mtot = _RE_TOTAL.match(line_strip)
        if mtot and res.total_quan == 0:  # només la primera ocurrència
            res.total_palets = int(mtot.group(1))
            res.total_sacs = float(mtot.group(2))
            res.total_quan = float(mtot.group(3))
            continue
        m_ep = _RE_ENTREGA_PAL.match(line_strip)
        if m_ep and res.entrega_paletitzada is None:
            res.entrega_paletitzada = float(m_ep.group(1))
            continue
        m_em = _RE_ENTREGA_MAN.match(line_strip)
        if m_em and res.entrega_manual is None:
            res.entrega_manual = float(m_em.group(1))

    return res
