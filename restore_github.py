import os
import io
import base64
import json
import zipfile
import urllib.request
import urllib.error
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
GITHUB_BACKUP_PATH = "backup/esi_tickets_backup.zip"

def _github_env():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
    return token, repo, branch

def _api_get(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ESI-Tickets-Restore"
        },
        method="GET"
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))

def _local_data_exists():
    db_file = APP_DIR / "data" / "esi_tickets.db"
    tickets_dir = APP_DIR / "tickets"
    fichiers_dir = APP_DIR / "fichiers"

    if db_file.exists() and db_file.stat().st_size > 0:
        return True
    if tickets_dir.exists() and any(tickets_dir.glob("*.json")):
        return True
    if fichiers_dir.exists() and any(p.is_file() for p in fichiers_dir.rglob("*")):
        return True
    return False

def restore_from_github_if_needed(force=False):
    token, repo, branch = _github_env()
    if not token or not repo:
        print("[RESTORE] GITHUB_TOKEN ou GITHUB_REPO manquant : restauration ignorée.")
        return False

    if not force and _local_data_exists():
        print("[RESTORE] Données locales déjà présentes : restauration ignorée.")
        return False

    try:
        api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}?ref={branch}"
        data = _api_get(api_url, token)
        content = base64.b64decode(data["content"])

        with zipfile.ZipFile(io.BytesIO(content), "r") as z:
            for member in z.namelist():
                if member.endswith("/"):
                    continue

                target = APP_DIR / member
                if not str(target.resolve()).startswith(str(APP_DIR.resolve())):
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())

        print("[RESTORE] Restauration GitHub effectuée.")
        return True

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print("[RESTORE] Aucune sauvegarde trouvée sur GitHub.")
            return False
        print(f"[RESTORE] Erreur HTTP restauration GitHub : {e}")
        return False

    except Exception as e:
        print(f"[RESTORE] Erreur restauration GitHub : {e}")
        return False
