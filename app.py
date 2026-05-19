from supabase import create_client
from supabase_upload import upload_file_to_supabase
from flask import Flask, render_template, jsonify, request, send_file, abort, redirect, url_for
from pathlib import Path
import json, threading, webbrowser, os, sqlite3
from datetime import datetime

# Sauvegarde automatique GitHub Render
try:
    from backup_github import backup_to_github
    from restore_github import restore_from_github_if_needed
except Exception:
    backup_to_github = None
    restore_from_github_if_needed = None


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / 'data'
CONFIG_FILE = DATA_DIR / 'config.json'
DB_FILE = DATA_DIR / 'esi_tickets.db'
TICKETS_SUB = 'tickets'
FILES_SUB = 'fichiers'
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__, template_folder='templates', static_folder='static')

def choose_shared_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Choisis le dossier partagé ESI Tickets")
        root.destroy()
        if path:
            return path
    except Exception:
        pass
    return ''

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}

def save_config(cfg):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')

def ensure_shared_root():
    root = APP_DIR
    (root / TICKETS_SUB).mkdir(parents=True, exist_ok=True)
    (root / FILES_SUB).mkdir(parents=True, exist_ok=True)
    return root

def tickets_dir():
    return ensure_shared_root() / TICKETS_SUB

def files_dir():
    return ensure_shared_root() / FILES_SUB

def ticket_file(ticket_id):
    return tickets_dir() / f'{ticket_id}.json'

def ticket_folder(ticket_id):
    path = files_dir() / ticket_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with db_connect() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY,
            module TEXT,
            status TEXT,
            createdAt TEXT,
            updatedAt TEXT,
            dossier TEXT,
            ref TEXT,
            preteur TEXT,
            expo TEXT,
            objet TEXT,
            chargeProjet TEXT,
            typeCaisse TEXT,
            dimensions TEXT,
            dateEmballage TEXT,
            prixDevis TEXT,
            dateRdv TEXT,
            heureRdv TEXT,
            lieuRdv TEXT,
            commentaire TEXT,
            validatedAt TEXT,
            raw_json TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS fiches (
            ticket_id TEXT PRIMARY KEY,
            longueur TEXT,
            largeur TEXT,
            hauteur TEXT,
            dimensionsExt TEXT,
            prixAchat TEXT,
            typeCaisseFiche TEXT,
            bilanCarbone TEXT,
            poids TEXT,
            choixCaissier TEXT,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT,
            kind TEXT,
            name TEXT,
            size INTEGER,
            FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_module ON tickets(module)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_dossier ON tickets(dossier)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_createdAt ON tickets(createdAt)")
        conn.commit()

def _as_text(value, default=''):
    if value is None:
        return default
    return str(value)

def _ticket_from_row(row):
    return {
        'id': row['id'],
        'module': row['module'] or '',
        'status': row['status'] or '',
        'createdAt': row['createdAt'] or '',
        'updatedAt': row['updatedAt'] or '',
        'dossier': row['dossier'] or '',
        'ref': row['ref'] or '',
        'preteur': row['preteur'] or '-',
        'expo': row['expo'] or '-',
        'objet': row['objet'] or '-',
        'chargeProjet': row['chargeProjet'] or '-',
        'typeCaisse': row['typeCaisse'] or '-',
        'dimensions': row['dimensions'] or '-',
        'dateEmballage': row['dateEmballage'] or '-',
        'prixDevis': row['prixDevis'] or '-',
        'dateRdv': row['dateRdv'] or '-',
        'heureRdv': row['heureRdv'] or '-',
        'lieuRdv': row['lieuRdv'] or '-',
        'commentaire': row['commentaire'] or '',
        'validatedAt': row['validatedAt'] or ''
    }

def _attach_children(conn, ticket):
    fiche = conn.execute("SELECT * FROM fiches WHERE ticket_id=?", (ticket['id'],)).fetchone()
    if fiche:
        ticket['fiche'] = {
            'longueur': fiche['longueur'] or '',
            'largeur': fiche['largeur'] or '',
            'hauteur': fiche['hauteur'] or '',
            'dimensionsExt': fiche['dimensionsExt'] or '',
            'prixAchat': fiche['prixAchat'] or '',
            'typeCaisseFiche': fiche['typeCaisseFiche'] or '',
            'bilanCarbone': fiche['bilanCarbone'] or '',
            'poids': fiche['poids'] or '',
            'choixCaissier': fiche['choixCaissier'] or ''
        }

    ticket['files'] = []
    ticket['managerSheets'] = []
    rows = conn.execute("SELECT kind, name, size FROM files WHERE ticket_id=? ORDER BY id", (ticket['id'],)).fetchall()
    for f in rows:
        item = {'name': f['name'] or '', 'size': f['size']}
        if f['kind'] == 'gestionnaire':
            ticket['managerSheets'].append(item)
        else:
            ticket['files'].append(item)
    return ticket

def _read_json_tickets():
    out = []
    for path in tickets_dir().glob('*.json'):
        try:
            out.append(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            pass
    out.sort(key=lambda x: str(x.get('createdAt','')), reverse=True)
    return out

def list_tickets():
    init_db()

    merged = {}

    # Tickets SQLite
    try:
        with db_connect() as conn:
            rows = conn.execute("SELECT * FROM tickets ORDER BY createdAt DESC").fetchall()
            for row in rows:
                ticket = _attach_children(conn, _ticket_from_row(row))
                if ticket.get('id'):
                    merged[ticket['id']] = ticket
    except Exception:
        pass

    # Tickets JSON non présents en base
    for ticket in _read_json_tickets():
        tid = ticket.get('id')
        if tid and tid not in merged:
            merged[tid] = ticket

    tickets = list(merged.values())
    tickets.sort(key=lambda x: str(x.get('createdAt', '')), reverse=True)

    return tickets

def next_id(prefix):
    init_db()
    nums = []
    try:
        with db_connect() as conn:
            rows = conn.execute("SELECT id FROM tickets WHERE id LIKE ?", (prefix + '-%',)).fetchall()
            for row in rows:
                try:
                    nums.append(int(str(row['id']).split('-')[1]))
                except Exception:
                    pass
    except Exception:
        pass
    for t in _read_json_tickets():
        tid = str(t.get('id',''))
        if tid.startswith(prefix + '-'):
            try:
                nums.append(int(tid.split('-')[1]))
            except Exception:
                pass
    mx = max(nums) if nums else 0
    return f"{prefix}-{mx+1:03d}"

def save_ticket(ticket):
    init_db()
    with db_connect() as conn:
        conn.execute("""
        INSERT OR REPLACE INTO tickets (
            id, module, status, createdAt, updatedAt, dossier, ref, preteur,
            expo, objet, chargeProjet, typeCaisse, dimensions, dateEmballage,
            prixDevis, dateRdv, heureRdv, lieuRdv, commentaire, validatedAt, raw_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            _as_text(ticket.get('id')),
            _as_text(ticket.get('module')),
            _as_text(ticket.get('status')),
            _as_text(ticket.get('createdAt')),
            _as_text(ticket.get('updatedAt')),
            _as_text(ticket.get('dossier')),
            _as_text(ticket.get('ref')),
            _as_text(ticket.get('preteur')),
            _as_text(ticket.get('expo')),
            _as_text(ticket.get('objet')),
            _as_text(ticket.get('chargeProjet')),
            _as_text(ticket.get('typeCaisse')),
            _as_text(ticket.get('dimensions')),
            _as_text(ticket.get('dateEmballage')),
            _as_text(ticket.get('prixDevis')),
            _as_text(ticket.get('dateRdv')),
            _as_text(ticket.get('heureRdv')),
            _as_text(ticket.get('lieuRdv')),
            _as_text(ticket.get('commentaire')),
            _as_text(ticket.get('validatedAt')),
            json.dumps(ticket, ensure_ascii=False)
        ))

        fiche = ticket.get('fiche') or {}
        if fiche:
            conn.execute("""
            INSERT OR REPLACE INTO fiches (
                ticket_id, longueur, largeur, hauteur, dimensionsExt, prixAchat,
                typeCaisseFiche, bilanCarbone, poids, choixCaissier
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                ticket.get('id'),
                _as_text(fiche.get('longueur')),
                _as_text(fiche.get('largeur')),
                _as_text(fiche.get('hauteur')),
                _as_text(fiche.get('dimensionsExt')),
                _as_text(fiche.get('prixAchat')),
                _as_text(fiche.get('typeCaisseFiche')),
                _as_text(fiche.get('bilanCarbone')),
                _as_text(fiche.get('poids')),
                _as_text(fiche.get('choixCaissier')),
            ))
        else:
            conn.execute("DELETE FROM fiches WHERE ticket_id=?", (ticket.get('id'),))

        conn.execute("DELETE FROM files WHERE ticket_id=?", (ticket.get('id'),))
        for fs in ticket.get('files') or []:
            if fs and fs.get('name'):
                conn.execute("INSERT INTO files(ticket_id, kind, name, size) VALUES (?,?,?,?)", (ticket.get('id'), 'demandeur', _as_text(fs.get('name')), fs.get('size')))

        manager_sheets = list(ticket.get('managerSheets') or [])
        legacy = ticket.get('managerSheet')
        if legacy and isinstance(legacy, dict) and legacy.get('name'):
            if not any(x.get('name') == legacy.get('name') for x in manager_sheets):
                manager_sheets.append(legacy)
        for fs in manager_sheets:
            if fs and fs.get('name'):
                conn.execute("INSERT INTO files(ticket_id, kind, name, size) VALUES (?,?,?,?)", (ticket.get('id'), 'gestionnaire', _as_text(fs.get('name')), fs.get('size')))
        conn.commit()

    ticket_file(ticket['id']).write_text(json.dumps(ticket, indent=2, ensure_ascii=False), encoding='utf-8')

@app.route('/')
def index():
    return redirect(url_for('demandeur'))

@app.route('/demandeur')
def demandeur():
    return render_template('demandeur.html')

@app.route('/gestionnaire')
def gestionnaire():
    from flask import request, redirect, url_for
    if request.args.get('pwd') != '1234':
        return redirect(url_for('login'))
    return render_template('gestionnaire.html')

@app.route('/login', methods=['GET','POST'])
def login():
    from flask import request, redirect, render_template_string
    error = ''
    if request.method == 'POST':
        if request.form.get('password') == '1234':
            return redirect('/gestionnaire?pwd=1234')
        error = 'Mot de passe incorrect'
    return render_template_string("""<!DOCTYPE html>
<html lang='fr'>
<head>
<meta charset='UTF-8'>
<meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>Connexion gestionnaire</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;background:linear-gradient(180deg,#eef6fb 0%,#f6f8fb 100%);margin:0;display:flex;align-items:center;justify-content:center;height:100vh;color:#1e293b}
.card{background:#fff;border:1px solid #dbe7f0;border-radius:20px;padding:28px;box-shadow:0 12px 30px rgba(15,23,42,.08);width:360px}
h1{margin:0 0 10px;font-size:28px} p{margin:0 0 18px;color:#64748b}
input{width:100%;padding:12px 14px;border:1px solid #dbe7f0;border-radius:14px;font-size:15px;box-sizing:border-box}
button{margin-top:14px;width:100%;padding:12px 14px;border:none;border-radius:14px;background:linear-gradient(135deg,#0ea5e9 0%, #0284c7 100%);color:#fff;font-weight:700;cursor:pointer}
.err{margin-top:12px;color:#b91c1c;font-size:13px}
</style>
</head>
<body>
  <form class='card' method='post'>
    <h1>Gestion Tickets</h1>
    <p>Accès protégé par mot de passe</p>
    <input type='password' name='password' placeholder='Mot de passe' autofocus />
    <button type='submit'>Entrer</button>
    {% if error %}<div class='err'>{{ error }}</div>{% endif %}
  </form>
</body>
</html>""", error=error)

@app.route('/api/status')
def api_status():
    root = ensure_shared_root()
    return jsonify({'shared_path': str(root), 'mode': 'automatic_app_folder'})

@app.route('/api/tickets')
def api_tickets():
    status = request.args.get('status')
    tickets = list_tickets()
    if status:
        tickets = [t for t in tickets if t.get('status') == status]
    return jsonify(tickets)

@app.route('/api/tickets', methods=['POST'])
def api_create_ticket():
    form = request.form
    module = form.get('module','')
    prefix = 'DEM' if module == 'Fiche de caisse' else ('DEV' if module == 'Demande de devis' else 'AV')
    ticket_id = next_id(prefix)
    ticket = {
        'id': ticket_id,
        'module': module,
        'status': 'Demande créée',
        'createdAt': datetime.now().isoformat(),
        'dossier': form.get('dossier',''),
        'ref': form.get('ref',''),
        'preteur': form.get('preteur','-') or '-',
        'expo': form.get('expo','-') or '-',
        'objet': form.get('objet','-') or '-',
        'chargeProjet': form.get('chargeProjet','-') or '-',
        'typeCaisse': form.get('typeCaisse','-') or '-',
        'dimensions': form.get('dimensions','-') or '-',
        'dateEmballage': form.get('dateEmballage','-') or '-',
        'prixDevis': form.get('prixDevis','-') or '-',
        'dateRdv': form.get('dateRdv','-') or '-',
        'heureRdv': form.get('heureRdv','-') or '-',
        'lieuRdv': form.get('lieuRdv','-') or '-',
        'commentaire': form.get('commentaire',''),
        'files': [],
        'managerSheets': []
    }
    folder = ticket_folder(ticket_id)

    for fs in request.files.getlist('files'):
        if not fs.filename:
            continue

        content = fs.read()

        supabase.storage.from_("uploads").upload(
            f"{ticket_id}/{fs.filename}",
            content,
            {"content-type": fs.content_type}
        )

        size = len(content)

        ticket['files'].append({
            'name': fs.filename,
            'size': size
        })

    save_ticket(ticket)
    return jsonify({'ok': True, 'id': ticket_id})


@app.route('/api/tickets/<ticket_id>', methods=['PUT'])
def api_update_ticket(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404

    data = request.get_json(silent=True) or {}

    editable_fields = [
        'dossier',
        'ref',
        'preteur',
        'expo',
        'objet',
        'chargeProjet',
        'typeCaisse',
        'dimensions',
        'dateEmballage',
        'prixDevis',
        'dateRdv',
        'heureRdv',
        'lieuRdv',
        'commentaire'
    ]

    for field in editable_fields:
        if field in data:
            ticket[field] = data.get(field, '')

    if 'expo' in data and 'objet' not in data:
        ticket['objet'] = data.get('expo', '')

    ticket['updatedAt'] = datetime.now().isoformat()
    save_ticket(ticket)
    return jsonify({'ok': True})

@app.route('/api/tickets/<ticket_id>/status', methods=['PATCH'])
def api_update_status(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404
    data = request.get_json(silent=True) or {}
    ticket['status'] = data.get('status', ticket.get('status'))
    ticket['updatedAt'] = datetime.now().isoformat()
    save_ticket(ticket)
    return jsonify({'ok': True})

@app.route('/api/tickets/<ticket_id>/manager-sheet', methods=['POST'])
def api_manager_sheet(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404

    files = request.files.getlist('files')
    if not files:
        single = request.files.get('file')
        if single:
            files = [single]

    valid_files = [fs for fs in files if fs and fs.filename]
    if not valid_files:
        return jsonify({'error': 'Fichier manquant'}), 400

    folder = ticket_folder(ticket_id)
    manager_sheets = list(ticket.get('managerSheets') or [])
    legacy = ticket.get('managerSheet')
    if legacy and isinstance(legacy, dict) and legacy.get('name'):
        if not any(x.get('name') == legacy.get('name') for x in manager_sheets):
            manager_sheets.append(legacy)

    for fs in valid_files:
        dest = folder / fs.filename
        fs.save(dest)
        size = dest.stat().st_size if dest.exists() else None
        manager_sheets = [x for x in manager_sheets if x.get('name') != fs.filename]
        manager_sheets.append({'name': fs.filename, 'size': size})

    ticket['managerSheets'] = manager_sheets
    ticket['updatedAt'] = datetime.now().isoformat()
    save_ticket(ticket)
    return jsonify({'ok': True})

@app.route('/api/tickets/<ticket_id>/download/<filename>')
def api_download_file(ticket_id, filename):
    path = ticket_folder(ticket_id) / filename
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)

@app.route('/api/tickets/<ticket_id>/download-sheet/<filename>')
def api_download_sheet(ticket_id, filename):
    file_path = ticket_folder(ticket_id) / filename
    if not file_path.exists():
        abort(404)
    return send_file(file_path, as_attachment=True, download_name=filename)


def load_ticket(ticket_id):
    init_db()
    try:
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row:
                return _attach_children(conn, _ticket_from_row(row))
    except Exception:
        pass
    path = ticket_file(ticket_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding='utf-8'))

@app.route('/api/tickets/<ticket_id>/fiche', methods=['GET'])
def api_get_fiche(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404
    return jsonify(ticket.get('fiche', {}))

@app.route('/api/tickets/<ticket_id>/fiche', methods=['POST'])
def api_save_fiche(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404
    data = request.get_json(silent=True) or {}
    longueur = data.get('longueur', '')
    largeur = data.get('largeur', '')
    hauteur = data.get('hauteur', '')
    dimensions_ext = " x ".join([v for v in [longueur, largeur, hauteur] if str(v).strip()])
    ticket['fiche'] = {
        'longueur': longueur,
        'largeur': largeur,
        'hauteur': hauteur,
        'dimensionsExt': dimensions_ext,
        'prixAchat': data.get('prixAchat', ''),
        'typeCaisseFiche': data.get('typeCaisseFiche', ''),
        'bilanCarbone': data.get('bilanCarbone', ''),
        'poids': data.get('poids', ''),
        'choixCaissier': data.get('choixCaissier', '')
    }
    save_ticket(ticket)
    return jsonify({'ok': True})



@app.route('/api/export/excel')
def api_export_excel():
    try:
        from openpyxl import Workbook
        import io
    except Exception:
        return jsonify({'error': "openpyxl non installé"}), 500

    tickets = list_tickets()

    wb = Workbook()
    ws = wb.active
    ws.title = "Tickets"

    ws.append([
        "ID","Module","Statut","Date création","Dossier / Client",
        "Réf / N° caisse","Chargé de projet","Projet / Expo",
        "Type de caisse","Dimensions","Prix devis",
        "Prix d'achat","Commentaire","Choix du caissier",
        "Date RDV","Heure RDV","Lieu RDV"
    ])

    for t in tickets:
        fiche = t.get('fiche', {}) or {}
        ws.append([
            t.get('id',''),
            t.get('module',''),
            t.get('status',''),
            t.get('createdAt',''),
            t.get('dossier',''),
            t.get('ref',''),
            t.get('chargeProjet',''),
            t.get('expo') or t.get('objet',''),
            t.get('typeCaisse',''),
            t.get('dimensions',''),
            t.get('prixDevis',''),
            fiche.get('prixAchat',''),
            t.get('commentaire',''),
            fiche.get('choixCaissier',''),
            t.get('dateRdv',''),
            t.get('heureRdv',''),
            t.get('lieuRdv','')
        ])

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="tickets_esi.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



@app.route('/api/tickets/<ticket_id>/export-pdf')
def api_export_ticket_pdf(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404

    import io
    import textwrap

    def clean(value):
        if value is None or value == '':
            return '-'
        return str(value).replace('\r', ' ').replace('\n', ' ')

    def add_wrapped(lines, label, value):
        text = label + " : " + clean(value)
        for part in textwrap.wrap(text, width=82) or [text]:
            lines.append(part)

    lines = []
    lines.append("ESI TICKETS - DETAIL TICKET")
    lines.append("=" * 70)
    lines.append("")
    add_wrapped(lines, "ID", ticket.get('id'))
    add_wrapped(lines, "Module", ticket.get('module'))
    add_wrapped(lines, "Statut", ticket.get('status'))
    add_wrapped(lines, "Dossier / Client", ticket.get('dossier'))
    add_wrapped(lines, "Reference", ticket.get('ref'))
    add_wrapped(lines, "Charge de projet", ticket.get('chargeProjet'))
    add_wrapped(lines, "Projet / Expo", ticket.get('expo') or ticket.get('objet'))
    add_wrapped(lines, "Preteur", ticket.get('preteur'))
    add_wrapped(lines, "Type de caisse", ticket.get('typeCaisse'))
    add_wrapped(lines, "Dimensions", ticket.get('dimensions'))
    add_wrapped(lines, "Prix devis", ticket.get('prixDevis'))
    add_wrapped(lines, "Lieu RDV", ticket.get('lieuRdv'))
    add_wrapped(lines, "Date RDV", ticket.get('dateRdv'))
    add_wrapped(lines, "Heure RDV", ticket.get('heureRdv'))

    lines.append("")
    lines.append("COMMENTAIRE / INFORMATIONS")
    lines.append("-" * 70)
    commentaire = clean(ticket.get('commentaire'))
    for part in textwrap.wrap(commentaire, width=82) or ['-']:
        lines.append(part)

    fiche = ticket.get('fiche') or {}
    if fiche:
        lines.append("")
        lines.append("INFORMATIONS FICHE")
        lines.append("-" * 70)
        add_wrapped(lines, "Dimensions exterieures", fiche.get('dimensionsExt'))
        add_wrapped(lines, "Prix achat", fiche.get('prixAchat'))
        add_wrapped(lines, "Type caisse fiche", fiche.get('typeCaisseFiche'))
        add_wrapped(lines, "Bilan carbone", fiche.get('bilanCarbone'))
        add_wrapped(lines, "Poids", fiche.get('poids'))
        add_wrapped(lines, "Choix caissier", fiche.get('choixCaissier'))

    lines.append("")
    lines.append("DOCUMENTS DU DEMANDEUR")
    lines.append("-" * 70)
    files = ticket.get('files') or []
    if files:
        for f in files:
            lines.append("- " + clean(f.get('name')))
    else:
        lines.append("- Aucun document")

    manager_sheets = ticket.get('managerSheets') or []
    if manager_sheets:
        lines.append("")
        lines.append("DOCUMENTS GESTIONNAIRE")
        lines.append("-" * 70)
        for f in manager_sheets:
            lines.append("- " + clean(f.get('name')))

    lines.append("")
    lines.append("NOTES / ACTIONS A PREVOIR")
    lines.append("-" * 70)
    lines.append("")
    lines.append("_" * 70)
    lines.append("")
    lines.append("_" * 70)
    lines.append("")
    lines.append("_" * 70)

    def pdf_escape(value):
        value = str(value)
        value = value.replace("\\", "\\\\")
        value = value.replace("(", "\\(")
        value = value.replace(")", "\\)")
        return value

    page_width, page_height = 595, 842
    margin_left = 42
    y_start = 800
    line_height = 14
    max_lines = 53
    chunks = [lines[i:i+max_lines] for i in range(0, len(lines), max_lines)] or [["Ticket vide"]]

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        None,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    ]

    page_refs = []
    for chunk in chunks:
        content_obj_num = len(objects) + 1
        content_lines = ["BT", "/F1 10 Tf", f"{margin_left} {y_start} Td"]
        first = True
        for line in chunk:
            if not first:
                content_lines.append(f"0 -{line_height} Td")
            first = False
            content_lines.append(f"({pdf_escape(line)}) Tj")
        content_lines.append("ET")

        stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream")

        page_obj_num = len(objects) + 1
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_num} 0 R >>"
        )
        objects.append(page.encode("latin-1"))
        page_refs.append(f"{page_obj_num} 0 R")

    objects[1] = f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(page_refs)} >>".encode("latin-1")

    pdf = io.BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = []

    for i, obj in enumerate(objects, start=1):
        offsets.append(pdf.tell())
        pdf.write(f"{i} 0 obj\n".encode("latin-1"))
        pdf.write(obj)
        pdf.write(b"\nendobj\n")

    xref_pos = pdf.tell()
    pdf.write(f"xref\n0 {len(objects)+1}\n".encode("latin-1"))
    pdf.write(b"0000000000 65535 f \n")
    for offset in offsets:
        pdf.write(f"{offset:010d} 00000 n \n".encode("latin-1"))

    trailer = f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    pdf.write(trailer.encode("latin-1"))
    pdf.seek(0)

    return send_file(
        pdf,
        as_attachment=True,
        download_name=f"{ticket.get('id','ticket')}.pdf",
        mimetype='application/pdf'
    )


@app.route('/api/restart')
def api_restart():
    import os
    os._exit(0)

@app.route('/splash')
def splash():
    return """
    <html>
    <head>
        <title>ESI Tickets</title>
        <style>
            body{margin:0;display:flex;justify-content:center;align-items:center;height:100vh;background:linear-gradient(180deg,#eef6fb,#f6f8fb);font-family:Arial;}
            .box{text-align:center;}
            img{width:120px;margin-bottom:20px;}
            h1{margin:0;color:#0284c7;}
            p{color:#64748b;}
        </style>
        <script>
            setTimeout(()=>{window.location.href="/demandeur";},1500);
        </script>
    </head>
    <body>
        <div class="box">
            <img id="splashLogo" src="/static/logo.jpg" onerror="
                const logos=['/static/logo.png','/static/logo%20esi.jpg'];
                const idx=Number(this.dataset.idx||0);
                if(idx<logos.length){this.dataset.idx=idx+1;this.src=logos[idx];}
                else{this.style.display='none';}
            ">
            <h1>ESI Tickets</h1>
            <p>Chargement en cours...</p>
        </div>
    </body>
    </html>
    """


@app.route('/api/tickets/<ticket_id>/validate-aller-voir', methods=['POST'])
def api_validate_aller_voir(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404
    ticket['status'] = 'En cours'
    ticket['validatedAt'] = datetime.now().isoformat()
    save_ticket(ticket)
    return jsonify({'ok': True})

@app.route('/api/tickets/<ticket_id>/calendar.ics')
def api_ticket_calendar_ics(ticket_id):
    ticket = load_ticket(ticket_id)
    if not ticket:
        return jsonify({'error': 'Ticket introuvable'}), 404

    date_rdv = ticket.get('dateRdv')
    heure_rdv = ticket.get('heureRdv')
    if not date_rdv or not heure_rdv or date_rdv == '-' or heure_rdv == '-':
        return jsonify({'error': 'Date/heure manquante'}), 400

    from datetime import timedelta
    start = datetime.fromisoformat(f"{date_rdv}T{heure_rdv}:00")
    end = start + timedelta(hours=2)

    def fmt(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    lieu = (ticket.get('lieuRdv') or '').strip()
    dossier = (ticket.get('dossier') or '').strip()
    summary = f"Aller voir - {lieu} - {dossier}"

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:{fmt(start)}
DTEND:{fmt(end)}
SUMMARY:{summary}
END:VEVENT
END:VCALENDAR"""

    from flask import Response
    return Response(ics, mimetype='text/calendar')


print("[BACKUP] Scheduler appelé au démarrage Render")
def start_github_backup_scheduler():
    print("[BACKUP] Fonction start_github_backup_scheduler lancée")
    if backup_to_github is None:
        return

    def loop():
        import time
        time.sleep(120)
        while True:
            try:
                backup_to_github()
            except Exception as e:
                print(f"[BACKUP] Erreur planification : {e}")
            time.sleep(300)

    t = threading.Thread(target=loop, daemon=True)
    t.start()


def open_browser():
    webbrowser.open('http://127.0.0.1:5050/splash')
ensure_shared_root()

if restore_from_github_if_needed is not None:
    restore_from_github_if_needed()

init_db()
start_github_backup_scheduler()
if __name__ == '__main__':
      app.run(host='127.0.0.1', port=5050, debug=False)
