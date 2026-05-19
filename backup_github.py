import os
import io
import base64
import json
import zipfile
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

APP_DIR = Path(__file__).resolve().parent
GITHUB_BACKUP_PATH = "backup/esi_tickets_backup.zip"

def _github_env():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPO", "").strip()
    branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
    return token, repo, branch

def _api_request(method, url, token, payload=None):
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ESI-Tickets-Backup"
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}

def _make_backup_zip():
    buffer = io.BytesIO()
    folders_to_save = [
        APP_DIR / "data",
        APP_DIR / "tickets",
        APP_DIR / "fichiers",
    ]

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in folders_to_save:
            if not folder.exists():
                continue
            for file in folder.rglob("*"):
                if file.is_file():
                    z.write(file, file.relative_to(APP_DIR).as_posix())

        z.writestr(
            "backup_info.json",
            json.dumps({
                "created_at": datetime.now().isoformat(),
                "folders": ["data", "tickets", "fichiers"]
            }, indent=2, ensure_ascii=False)
        )

    buffer.seek(0)
    return buffer.read()

def backup_to_github():
    token, repo, branch = _github_env()
    if not token or not repo:
        print("[BACKUP] GITHUB_TOKEN ou GITHUB_REPO manquant : sauvegarde ignorée.")
        return False

    try:
        content = _make_backup_zip()
        encoded = base64.b64encode(content).decode("ascii")

        api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"
        sha = None

        try:
            existing = _api_request("GET", f"{api_url}?ref={branch}", token)
            sha = existing.get("sha")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

        payload = {
            "message": f"Sauvegarde automatique ESI Tickets - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "content": encoded,
            "branch": branch
        }
        if sha:
            payload["sha"] = sha

        _api_request("PUT", api_url, token, payload)
        print("[BACKUP] Sauvegarde GitHub effectuée.")
        return True

    except Exception as e:
        print(f"[BACKUP] Erreur sauvegarde GitHub : {e}")
        return False
