from __future__ import annotations

import json
import mimetypes
import os
import math
import tempfile
import shutil
import unicodedata
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from matrice_caisses.t1 import T1Inputs, calculer_t1, options_t1
from matrice_caisses.t1_t6 import T1T6Inputs, OeuvreT1T6, calculer_t1_t6, options_t1_t6
from matrice_caisses.mrt import MRTInputs, calculer_mrt, options_mrt
from matrice_caisses.t1_t3_mrt import T1T3MRTInputs, MRTItem, calculer_t1_t3_mrt, options_t1_t3_mrt
from matrice_caisses.t_glissieres import TGlissieresInputs, TableauGlissiere, calculer_t_glissieres, options_t_glissieres
from matrice_caisses.t_separations_mousse import TSeparationsMousseInputs, OeuvreSeparationMousse, calculer_t_separations_mousse, options_t_separations_mousse
from matrice_caisses.objet1 import Objet1Inputs, calculer_objet1, options_objet1

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5000"))

CLASSIQUES = {
    "Tableaux": ["T1", "T1-T6", "MRT", "T1-T3 MRT", "T à Glissières", "T Séparations mousse"],
    "Objets": ["Objet 1", "Objet 2 à 6", "Tapisserie"],
    "Caissons / Wrapp": ["Wrapp"],
}
MIGRES = {"T1", "T1-T6", "MRT", "T1-T3 MRT", "T à Glissières", "T Séparations mousse", "Objet 1"}


def load_onglets():
    path = DATA_DIR / "onglets_excel.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def as_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return default


def fmt(value):
    if isinstance(value, (int, float)):
        return round(value, 2)
    return value


def calculate_sheet(sheet: str, data: dict):
    if sheet == "T1":
        inputs = T1Inputs(
            longueur_cm=as_float(data.get("longueur_cm")),
            epaisseur_cm=as_float(data.get("epaisseur_cm")),
            hauteur_cm=as_float(data.get("hauteur_cm")),
            type_isolant=data.get("type_isolant") or None,
            fermeture=data.get("fermeture") or None,
            peinture=data.get("peinture") or None,
            tyvek=data.get("tyvek") or None,
            type_calage=data.get("type_calage") or None,
            type_contreplaque=data.get("type_contreplaque") or None,
            garnissage=data.get("garnissage") or None,
            option_calage=data.get("option_calage") or None,
            epaisseur_mousse=data.get("epaisseur_mousse") or None,
        )
        return calculer_t1(inputs)
    if sheet == "T1-T6":
        oeuvres = []
        for item in data.get("oeuvres", []):
            oeuvres.append(OeuvreT1T6(
                longueur_cm=as_float(item.get("longueur_cm")),
                epaisseur_cm=as_float(item.get("epaisseur_cm")),
                hauteur_cm=as_float(item.get("hauteur_cm")),
                type_calage=item.get("type_calage") or None,
            ))
        inputs = T1T6Inputs(
            type_isolant=data.get("type_isolant") or None,
            fermeture=data.get("fermeture") or None,
            peinture=data.get("peinture") or None,
            tyvek=data.get("tyvek") or None,
            type_contreplaque=data.get("type_contreplaque") or None,
            garnissage=data.get("garnissage") or None,
            option_calage=data.get("option_calage") or None,
            oeuvres=oeuvres,
        )
        return calculer_t1_t6(inputs)

    if sheet == "T1-T3 MRT":
        mrts = []
        for item in data.get("mrts", []):
            mrts.append(MRTItem(
                mode_dimensions=item.get("mode_dimensions") or None,
                longueur_cm=as_float(item.get("longueur_cm")),
                epaisseur_cm=as_float(item.get("epaisseur_cm")),
                hauteur_cm=as_float(item.get("hauteur_cm")),
                face_mrt=item.get("face_mrt") or None,
                arriere_mrt=item.get("arriere_mrt") or None,
            ))
        inputs = T1T3MRTInputs(
            type_contreplaque=data.get("type_contreplaque") or None,
            barres=data.get("barres") or None,
            garnissage=data.get("garnissage") or None,
            type_isolant=data.get("type_isolant") or None,
            fermeture=data.get("fermeture") or None,
            peinture=data.get("peinture") or None,
            poignees=data.get("poignees") or None,
            skis=data.get("skis") or None,
            option_calage=data.get("option_calage") or None,
            type_calage=data.get("type_calage") or None,
            responsable_dossier=data.get("responsable_dossier") or None,
            client=data.get("client") or None,
            delai=data.get("delai") or None,
            mrts=mrts,
        )
        return calculer_t1_t3_mrt(inputs)

    if sheet == "T à Glissières":
        tableaux = []
        for item in data.get("tableaux", []):
            tableaux.append(TableauGlissiere(
                inventaire=item.get("inventaire") or None,
                longueur_cm=as_float(item.get("longueur_cm")),
                largeur_cm=as_float(item.get("largeur_cm")),
                hauteur_cm=as_float(item.get("hauteur_cm")),
                quantite=as_float(item.get("quantite"), 1),
                intervalle=as_float(item.get("intervalle"), 2.2),
            ))
        inputs = TGlissieresInputs(
            type_contreplaque=data.get("type_contreplaque") or None,
            barres=data.get("barres") or None,
            garnissage=data.get("garnissage") or None,
            type_isolant=data.get("type_isolant") or None,
            fermeture=data.get("fermeture") or None,
            peinture=data.get("peinture") or None,
            poignees=data.get("poignees") or None,
            skis=data.get("skis") or None,
            epaisseur_mousse=data.get("epaisseur_mousse") or None,
            cuvette_au_dessus=data.get("cuvette_au_dessus") or None,
            responsable_dossier=data.get("responsable_dossier") or None,
            client=data.get("client") or None,
            delai=data.get("delai") or None,
            tableaux=tableaux,
        )
        return calculer_t_glissieres(inputs)

    if sheet == "T Séparations mousse":
        rang1 = []
        for item in data.get("rang1", []):
            rang1.append(OeuvreSeparationMousse(
                longueur_cm=as_float(item.get("longueur_cm")),
                largeur_cm=as_float(item.get("largeur_cm")),
                hauteur_cm=as_float(item.get("hauteur_cm")),
            ))
        rang2 = []
        for item in data.get("rang2", []):
            rang2.append(OeuvreSeparationMousse(
                longueur_cm=as_float(item.get("longueur_cm")),
                largeur_cm=as_float(item.get("largeur_cm")),
                hauteur_cm=as_float(item.get("hauteur_cm")),
            ))
        inputs = TSeparationsMousseInputs(
            type_contreplaque=data.get("type_contreplaque") or None,
            barres=data.get("barres") or None,
            garnissage=data.get("garnissage") or None,
            type_isolant=data.get("type_isolant") or None,
            fermeture=data.get("fermeture") or None,
            peinture=data.get("peinture") or None,
            skis=data.get("skis") or None,
            poignees=data.get("poignees") or None,
            separations=data.get("separations") or None,
            responsable_dossier=data.get("responsable_dossier") or None,
            client=data.get("client") or None,
            delai=data.get("delai") or None,
            rang1=rang1,
            rang2=rang2,
        )
        return calculer_t_separations_mousse(inputs)

    if sheet == "Objet 1":
        inputs = Objet1Inputs(
            longueur_cm=as_float(data.get("longueur_cm")),
            largeur_cm=as_float(data.get("largeur_cm") or data.get("epaisseur_cm")),
            hauteur_cm=as_float(data.get("hauteur_cm")),
            type_contreplaque=data.get("type_contreplaque") or None,
            barres=data.get("barres") or None,
            garnissage=data.get("garnissage") or None,
            type_isolant=data.get("type_isolant") or None,
            fermeture=data.get("fermeture") or None,
            peinture=data.get("peinture") or None,
            poignees=data.get("poignees") or None,
            skis=data.get("skis") or None,
            cuvette_au_dessus=data.get("cuvette_au_dessus") or None,
            option=data.get("option") or None,
            nombre_cote_ouvrant=data.get("nombre_cote_ouvrant") or None,
            type_calage=data.get("type_calage") or None,
            nombre_calages=as_float(data.get("nombre_calages")),
            plateau_interieur=data.get("plateau_interieur") or None,
            base=data.get("base") or None,
            responsable_dossier=data.get("responsable_dossier") or None,
            client=data.get("client") or None,
        )
        return calculer_objet1(inputs)
    if sheet == "MRT":
        inputs = MRTInputs(
            longueur_cm=as_float(data.get("longueur_cm")),
            epaisseur_cm=as_float(data.get("epaisseur_cm")),
            hauteur_cm=as_float(data.get("hauteur_cm")),
            mode_dimensions=data.get("mode_dimensions") or None,
            type_contreplaque=data.get("type_contreplaque") or None,
            barres=data.get("barres") or None,
            fermeture=data.get("fermeture") or None,
            poignees=data.get("poignees") or None,
            face_mrt=data.get("face_mrt") or None,
            arriere_mrt=data.get("arriere_mrt") or None,
            responsable_dossier=data.get("responsable_dossier") or None,
            client=data.get("client") or None,
            categorie=data.get("categorie") or None,
        )
        return calculer_mrt(inputs)
    raise ValueError("Ce type de caisse n'est pas encore migré.")


def ceil_text(value):
    if value in (None, ""):
        return "-"
    try:
        return f"{math.ceil(float(value)):,.0f}".replace(",", " ")
    except Exception:
        return str(value or "-")


def euro_text(value):
    txt = ceil_text(value)
    return "-" if txt == "-" else f"{txt} €"


def num_text(value, suffix=""):
    txt = ceil_text(value)
    return "-" if txt == "-" else f"{txt}{suffix}"


def load_parametres_matiere():
    """Paramètres modifiables issus de la feuille Prix Matiere."""
    path = DATA_DIR / "parametres_matiere.json"
    default = {"marge_cession_percent": 30}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default, **data}
    except Exception:
        return default


def taux_marge_cession():
    params = load_parametres_matiere()
    value = params.get("marge_cession_percent", 30)
    try:
        return float(str(value).replace(",", ".")) / 100.0
    except Exception:
        return 0.30


def enrich_result_with_cession(result: dict) -> dict:
    """Ajoute le prix de cession = prix d'achat + marge paramétrable."""
    enriched = dict(result or {})
    prix_achat = as_float(enriched.get("prix_vente"), None)
    marge = taux_marge_cession()
    if prix_achat is not None:
        enriched["prix_achat"] = prix_achat
        enriched["marge_cession_percent"] = round(marge * 100, 4)
        enriched["prix_cession"] = prix_achat * (1 + marge)
    return enriched



def slugify(value: str) -> str:
    value = str(value or "").strip().lower()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", "/", "\\", "."):
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "notice"


def notice_key(sheet: str, data: dict) -> str:
    """Clé stable : type de caisse + isolant + calage.
    Pour les caisses sans champ type_calage, on utilise le champ le plus proche.
    """
    isolant = data.get("type_isolant") or "Aucun"
    calage = (
        data.get("type_calage")
        or data.get("separations")
        or data.get("option_calage")
        or data.get("base")
        or "Aucun"
    )
    return "|".join([slugify(sheet), slugify(isolant), slugify(calage)])


def notices_index_path() -> Path:
    return DATA_DIR / "notices_index.json"


def load_notices_index() -> dict:
    path = notices_index_path()
    default = {"notices": []}
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("notices"), list):
            return data
    except Exception:
        pass
    return default


def save_notices_index(index: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    notices_index_path().write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")




def render_pdf_first_page_to_png(pdf_path: Path, png_path: Path) -> bool:
    """Génère un aperçu PNG de la première page du PDF.
    Compatible Render/Python 3.14 grâce à pypdfium2.
    """
    try:
        import pypdfium2 as pdfium
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pdf = pdfium.PdfDocument(str(pdf_path))
        if len(pdf) == 0:
            return False
        page = pdf[0]
        bitmap = page.render(scale=1.8)
        image = bitmap.to_pil()
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        image.save(str(png_path), "PNG")
        try:
            page.close()
        except Exception:
            pass
        try:
            pdf.close()
        except Exception:
            pass
        return png_path.exists()
    except Exception:
        return False

def notice_record_to_doc(record: dict):
    if not record:
        return None
    rel_pdf = record.get("pdf") or ""
    pdf = ROOT / rel_pdf
    preview_rel = record.get("preview") or ""
    preview = ROOT / preview_rel if preview_rel else pdf.with_suffix(".png")
    return {"title": record.get("title") or "Notice technique", "pdf": pdf, "preview": preview}


def notice_record_to_api(record: dict):
    if not record:
        return None
    rel_pdf = record.get("pdf") or ""
    rel_preview = record.get("preview") or ""
    if not rel_preview and rel_pdf.lower().endswith(".pdf"):
        rel_preview = rel_pdf[:-4] + ".png"
    return {
        "title": record.get("title") or "Notice technique",
        "pdf": "/" + rel_pdf.lstrip("/"),
        "preview": "/" + rel_preview.lstrip("/") if rel_preview else "",
        "key": record.get("key") or "",
        "auto": bool(record.get("auto")),
    }


def notice_match_values(sheet: str, data: dict) -> tuple[str, str, str]:
    """Valeurs normalisées utilisées pour retrouver une notice.
    On garde la clé stable, mais on accepte aussi les anciens enregistrements
    dont la clé aurait été construite différemment.
    """
    isolant = data.get("type_isolant") or "Aucun"
    calage = (
        data.get("type_calage")
        or data.get("separations")
        or data.get("option_calage")
        or data.get("base")
        or "Aucun"
    )
    return slugify(sheet), slugify(isolant), slugify(calage)


def find_notice_record(sheet: str, data: dict):
    key = notice_key(sheet, data)
    sheet_s, isolant_s, calage_s = notice_match_values(sheet, data)
    notices = load_notices_index().get("notices", [])

    # 1) Recherche par clé exacte
    for record in notices:
        if record.get("key") == key:
            return record

    # 2) Recherche tolérante par champs enregistrés
    for record in notices:
        r_sheet = slugify(record.get("sheet") or "")
        r_isolant = slugify(record.get("type_isolant") or record.get("isolant") or "Aucun")
        r_calage = slugify(record.get("type_calage") or record.get("calage") or record.get("separations") or "Aucun")
        if (r_sheet, r_isolant, r_calage) == (sheet_s, isolant_s, calage_s):
            return record

    return None


def next_notice_id(index: dict) -> int:
    """Retourne le prochain identifiant numérique pour les notices auto."""
    max_id = 0
    for record in index.get("notices", []):
        try:
            max_id = max(max_id, int(record.get("id") or 0))
        except Exception:
            pass
    return max_id + 1


def notice_category_dir(sheet: str) -> str:
    """Dossier lisible pour ranger les notices ajoutées depuis l'application."""
    mapping = {
        "T1": "T1",
        "T1-T6": "T1-T6",
        "MRT": "MRT",
        "T1-T3 MRT": "T1-T3-MRT",
        "T à Glissières": "T-Glissieres",
        "T Séparations mousse": "T-Separations-Mousse",
        "Objet 1": "Objet1",
    }
    return mapping.get(sheet, slugify(sheet))


def register_notice(sheet: str, data: dict, title: str, source_pdf: Path) -> dict:
    key = notice_key(sheet, data)
    index = load_notices_index()

    # Si une notice existait déjà pour cette combinaison, on la remplace proprement
    # tout en gardant un nom de fichier simple et stable.
    old_record = None
    for record in index.get("notices", []):
        if record.get("key") == key:
            old_record = record
            break

    notice_id = int(old_record.get("id")) if old_record and old_record.get("id") else next_notice_id(index)
    folder = ROOT / "assets" / "notices" / "Auto" / notice_category_dir(sheet)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{notice_id:04d}.pdf"
    dest = folder / filename
    shutil.copyfile(source_pdf, dest)
    preview_path = dest.with_suffix(".png")
    preview_ok = render_pdf_first_page_to_png(dest, preview_path)

    record = {
        "id": notice_id,
        "key": key,
        "sheet": sheet,
        "type_isolant": data.get("type_isolant") or "Aucun",
        "type_calage": data.get("type_calage") or data.get("separations") or data.get("option_calage") or data.get("base") or "Aucun",
        "title": title or f"Notice technique - {sheet}",
        "pdf": str(dest.relative_to(ROOT)).replace("\\", "/"),
        "preview": str(preview_path.relative_to(ROOT)).replace("\\", "/") if preview_ok else "",
        "auto": True,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }

    notices = [r for r in index.get("notices", []) if r.get("key") != key]
    notices.append(record)
    notices.sort(key=lambda r: int(r.get("id") or 0))
    index["notices"] = notices
    save_notices_index(index)
    return record


def legacy_notice_for(sheet: str, data: dict):
    """Anciennes notices codées en dur, conservées comme secours."""
    calage = str(data.get("type_calage") or "").lower()
    isolant = str(data.get("type_isolant") or "").lower()

    def doc(title, rel_pdf):
        pdf = ROOT / rel_pdf
        return {"title": title, "pdf": pdf, "preview": pdf.with_suffix(".png")}

    if sheet == "T1" and "bandes" in calage:
        if "isotherme" in isolant or "super" in isolant or "double" in isolant:
            return doc("Caisse tableau - bandes de mousse double isotherme", "assets/notices/Tableaux/T1/bandes_mousse_double_isotherme.pdf")
        return doc("Caisse tableau - bandes de mousse", "assets/notices/T1/caisse_tableau_bandes_mousse.pdf")

    if sheet == "MRT" or sheet == "T1-T3 MRT":
        return doc("Caisse tableau MRT", "assets/notices/Tableaux/MRT/mrt.pdf")

    if sheet == "T à Glissières":
        return doc("Caisse glissières", "assets/notices/Tableaux/Glissieres/glissieres.pdf")

    if sheet == "Objet 1":
        if "banc" in calage:
            return doc("Caisse objet - bancs ouverts", "assets/notices/Objets/Objet1/caisse_objet_bancs_ouverts.pdf")
        if "guillotine" in calage:
            return doc("Caisse objet - guillotines", "assets/notices/Objets/Objet1/caisse_objet_guillotines.pdf")
        if "entourage" in calage or "mousse" in calage or "ecrin" in calage:
            if "double" in isolant:
                return doc("Caisse objet - entourage mousse double isotherme", "assets/notices/Objets/Objet1/caisse_objet_entourage_mousse_double_isotherme.pdf")
            if "super" in isolant or "30" in isolant:
                return doc("Objet superiso 30 - entourage mousse", "assets/notices/Objets/Objet1/objet_superiso30_entourage_mousse.pdf")
            if "isotherme" in isolant:
                return doc("Caisse objet - entourage mousse isotherme", "assets/notices/Objets/Objet1/caisse_objet_entourage_mousse_isotherme.pdf")
            return doc("Caisse objet - entourage mousse", "assets/notices/Objets/Objet1/caisse_objet_entourage_mousse.pdf")

    return None


def notice_for(sheet: str, data: dict):
    """Retourne d'abord une notice associée depuis le registre, puis les anciennes notices de secours."""
    registered = find_notice_record(sheet, data)
    if registered:
        return notice_record_to_doc(registered)
    return legacy_notice_for(sheet, data)


def notice_for_api(sheet: str, data: dict):
    registered = find_notice_record(sheet, data)
    if registered:
        return notice_record_to_api(registered)
    legacy = legacy_notice_for(sheet, data)
    if legacy:
        try:
            pdf_rel = str(legacy["pdf"].relative_to(ROOT)).replace("\\", "/")
            preview_rel = str(legacy["preview"].relative_to(ROOT)).replace("\\", "/")
        except Exception:
            return None
        return {"title": legacy["title"], "pdf": "/" + pdf_rel, "preview": "/" + preview_rel, "key": notice_key(sheet, data), "auto": False}
    return None


def parse_multipart_form(headers, body: bytes) -> tuple[dict, dict]:
    """Parse un formulaire multipart/form-data sans module cgi (compatible Python 3.13/3.14).
    Retourne (fields, files) avec files[name] = {filename, content, content_type}.
    """
    from email.parser import BytesParser
    from email.policy import default

    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("Requête multipart/form-data attendue.")

    raw = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body

    message = BytesParser(policy=default).parsebytes(raw)
    fields: dict[str, str] = {}
    files: dict[str, dict] = {}

    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="Content-Disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if not name:
            continue
        if filename:
            files[name] = {
                "filename": filename,
                "content": payload,
                "content_type": part.get_content_type(),
            }
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace")
    return fields, files

def generate_internal_fiche_pdf(sheet: str, data: dict, result: dict) -> bytes:
    """Génère une fiche chiffrage interne ESI sur une seule page PDF."""
    result = enrich_result_with_cession(result)
    notice = notice_for(sheet, data)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    w, h = A4
    margin = 14 * mm
    blue = colors.HexColor("#0284c7")
    sky = colors.HexColor("#0ea5e9")
    text = colors.HexColor("#0f172a")
    muted = colors.HexColor("#64748b")
    line = colors.HexColor("#dbeafe")
    light = colors.HexColor("#f8fafc")

    # Header
    c.setFillColor(light)
    c.roundRect(margin, h - 32*mm, w - 2*margin, 20*mm, 6*mm, fill=1, stroke=0)
    c.setFillColor(blue)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin + 8*mm, h - 18*mm, "ESI - FICHE CHIFFRAGE INTERNE")
    c.setFillColor(text)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin + 8*mm, h - 27*mm, str(sheet))
    c.setFillColor(muted)
    c.setFont("Helvetica", 8)
    c.drawRightString(w - margin - 8*mm, h - 18*mm, datetime.now().strftime("%d/%m/%Y"))

    # Meta / input dimensions
    y = h - 42*mm
    c.setFillColor(text)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Informations")
    y -= 8*mm
    fields = [
        ("Client", data.get("client") or "ESI"),
        ("Responsable", data.get("responsable_dossier") or "-"),
        ("Dimensions oeuvre", f"{data.get('longueur_cm') or '-'} x {data.get('largeur_cm') or data.get('epaisseur_cm') or '-'} x {data.get('hauteur_cm') or '-'} cm"),
    ]
    for lab, val in fields:
        c.setFillColor(muted); c.setFont("Helvetica-Bold", 7); c.drawString(margin, y, lab.upper())
        c.setFillColor(text); c.setFont("Helvetica-Bold", 10); c.drawString(margin + 45*mm, y, str(val))
        y -= 7*mm

    # Result cards
    dim = "-"
    dl = result.get("dimensions_exterieures_longueur")
    de = result.get("dimensions_exterieures_epaisseur")
    dh = result.get("dimensions_exterieures_hauteur")
    if dl or de or dh:
        dim = f"{num_text(dl)} x {num_text(de)} x {num_text(dh)} cm"
    cards = [
        ("Dimensions extérieures", dim),
        ("Poids caisse", num_text(result.get("poids_caisse"), " kg")),
        ("Bilan carbone", num_text(result.get("bilan_carbone"), " kg CO2e")),
        ("Prix de cession", euro_text(result.get("prix_cession"))),
    ]
    y -= 4*mm
    card_w = (w - 2*margin - 8*mm) / 2
    card_h = 20*mm
    for i, (lab, val) in enumerate(cards):
        x = margin + (i % 2) * (card_w + 8*mm)
        yy = y - (i // 2) * (card_h + 6*mm)
        c.setStrokeColor(line); c.setFillColor(light)
        c.roundRect(x, yy - card_h, card_w, card_h, 4*mm, fill=1, stroke=1)
        c.setFillColor(muted); c.setFont("Helvetica-Bold", 7); c.drawString(x + 5*mm, yy - 7*mm, lab.upper())
        c.setFillColor(text); c.setFont("Helvetica-Bold", 14); c.drawString(x + 5*mm, yy - 15*mm, str(val))
    y = y - 2*(card_h + 6*mm) - 4*mm

    # Notice preview
    c.setFillColor(blue); c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Notice technique")
    y -= 5*mm
    box_x, box_y = margin, margin + 8*mm
    box_w, box_h = w - 2*margin, y - box_y
    c.setStrokeColor(line); c.setFillColor(colors.white)
    c.roundRect(box_x, box_y, box_w, box_h, 5*mm, fill=1, stroke=1)
    preview_path = None
    if notice:
        preview_path = notice.get("preview")
        if (not preview_path or not preview_path.exists()) and notice.get("pdf") and notice["pdf"].exists():
            tmp_preview = Path(tempfile.gettempdir()) / f"notice_preview_{abs(hash(str(notice['pdf'])))}.png"
            if render_pdf_first_page_to_png(notice["pdf"], tmp_preview):
                preview_path = tmp_preview
    if notice and preview_path and preview_path.exists():
        img = ImageReader(str(preview_path))
        iw, ih = img.getSize()
        scale = min((box_w - 10*mm)/iw, (box_h - 13*mm)/ih)
        draw_w, draw_h = iw*scale, ih*scale
        c.drawImage(img, box_x + (box_w-draw_w)/2, box_y + 7*mm, width=draw_w, height=draw_h, preserveAspectRatio=True)
        c.setFillColor(text); c.setFont("Helvetica-Bold", 9)
        c.drawString(box_x + 5*mm, box_y + box_h - 7*mm, notice["title"])
    else:
        c.setFillColor(muted); c.setFont("Helvetica", 11)
        c.drawCentredString(box_x + box_w/2, box_y + box_h/2, "Aucune notice technique associée")

    c.setFillColor(muted); c.setFont("Helvetica", 7)
    c.drawRightString(w - margin, 7*mm, "Document interne généré par la matrice de chiffrage ESI")
    c.showPage()
    c.save()
    pdf_bytes = pdf_path.read_bytes()
    try:
        pdf_path.unlink()
    except Exception:
        pass
    return pdf_bytes


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            return self.send_file(ROOT / "index.html")
        if parsed.path in ("/health", "/api/health"):
            return self.send_json({"ok": True, "service": "matrice-chiffrage-esi"})
        if parsed.path == "/api/config":
            return self.send_json({
                "onglets": load_onglets(),
                "classiques": CLASSIQUES,
                "migres": sorted(MIGRES),
                "parametres_matiere": load_parametres_matiere(),
                "notices_count": len(load_notices_index().get("notices", [])),
                "deployment": {
                    "render": True,
                    "supabase_configured": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY")),
                },
                "options": {
                    "T1": options_t1(),
                    "T1-T6": options_t1_t6(),
                    "MRT": options_mrt(),
                    "T1-T3 MRT": options_t1_t3_mrt(),
                    "T à Glissières": options_t_glissieres(),
                    "T Séparations mousse": options_t_separations_mousse(),
                    "Objet 1": options_objet1(),
                },
            })
        if parsed.path == "/api/notices":
            return self.send_json(load_notices_index())
        safe = parsed.path.lstrip("/").replace("..", "")
        return self.send_file(ROOT / safe)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/calculate/"):
            sheet = unquote(parsed.path.split("/api/calculate/", 1)[1])
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
                result = enrich_result_with_cession(calculate_sheet(sheet, data))
                return self.send_json({"ok": True, "sheet": sheet, "result": {k: fmt(v) for k, v in result.items()}})
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=500)
        if parsed.path == "/api/notice/find":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
                sheet = payload.get("sheet") or ""
                data = payload.get("data") or {}
                found = notice_for_api(sheet, data)
                return self.send_json({"ok": True, "notice": found})
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=500)
        if parsed.path == "/api/notice/associate":
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length) if length else b""
                fields, files = parse_multipart_form(self.headers, body)

                sheet = fields.get("sheet", "")
                data_raw = fields.get("data", "{}")
                title = fields.get("title", "")
                data = json.loads(data_raw or "{}")
                file_item = files.get("pdf")

                if not sheet:
                    return self.send_json({"ok": False, "error": "Type de caisse manquant."}, status=400)
                if not file_item or not file_item.get("filename"):
                    return self.send_json({"ok": False, "error": "PDF manquant."}, status=400)
                if not str(file_item.get("filename", "")).lower().endswith(".pdf"):
                    return self.send_json({"ok": False, "error": "Le fichier doit être un PDF."}, status=400)
                if not file_item.get("content"):
                    return self.send_json({"ok": False, "error": "Le PDF est vide."}, status=400)

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(file_item["content"])
                    tmp_path = Path(tmp.name)
                try:
                    record = register_notice(sheet, data, title, tmp_path)
                finally:
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                return self.send_json({"ok": True, "notice": notice_record_to_api(record)})
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=500)
        if parsed.path == "/api/fiche-pdf":
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
                sheet = payload.get("sheet") or "Chiffrage"
                data = payload.get("data") or {}
                result = payload.get("result") or calculate_sheet(sheet, data)
                pdf_bytes = generate_internal_fiche_pdf(sheet, data, result)
                filename = f"fiche_chiffrage_{str(sheet).replace(' ', '_').replace('/', '-')}.pdf"
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(pdf_bytes)))
                self.end_headers()
                self.wfile.write(pdf_bytes)
                return
            except Exception as exc:
                return self.send_json({"ok": False, "error": str(exc)}, status=500)
        self.send_error(404)


def main():
    print(f"Matrice de chiffrage ESI : http://{HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
