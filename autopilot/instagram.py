"""Veröffentlichen über die offizielle "Instagram API with Instagram Login" (graph.instagram.com).
Kein Login-Bot, keine Facebook-Seite nötig."""
import os
import subprocess
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .einstellungen import KitFehler

API_VERSION = "v21.0"
API = f"https://graph.instagram.com/{API_VERSION}"
REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
WARTEN_SEKUNDEN = 10
WARTEN_VERSUCHE = 30


def _sitzung():
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "POST"],
    )))
    return s


SITZUNG = _sitzung()

# Häufige Meta-Fehler in verständlicher Form
ERKLAERUNGEN = {
    190: "Der Instagram-Token ist ungültig oder abgelaufen. Erzeuge im Meta-Dashboard einen neuen "
         "(Anleitung Schritt 4) und ersetze das GitHub-Secret IG_ACCESS_TOKEN.",
    10: "Der App fehlt die Berechtigung zum Posten. Beim Token-Erzeugen alle Häkchen bestätigen "
        "(instagram_business_content_publish).",
    9004: "Instagram konnte die Datei nicht abrufen. Ist das GitHub-Repository öffentlich (public)?",
    2207026: "Das Video hat ein Format, das Instagram ablehnt.",
}


def _fehler(resp):
    try:
        err = resp.json().get("error", {})
    except ValueError:
        err = {}
    code, sub = err.get("code"), err.get("error_subcode")
    hilfe = ERKLAERUNGEN.get(sub) or ERKLAERUNGEN.get(code) or ""
    meldung = err.get("message") or resp.text[:200]
    return KitFehler(f"Instagram meldet einen Fehler (HTTP {resp.status_code}): {meldung}. {hilfe}".strip())


def _get(pfad, token, **params):
    resp = SITZUNG.get(f"{API}/{pfad}", params={**params, "access_token": token}, timeout=30)
    if not resp.ok:
        raise _fehler(resp)
    return resp.json()


def konto(token):
    """Gibt (user_id, username) des Tokens zurück."""
    daten = _get("me", token, fields="user_id,username")
    return str(daten.get("user_id") or daten.get("id")), daten.get("username", "")


def konto_pruefen(token, erwartet):
    uid, name = konto(token)
    if name.lower() != erwartet.lower():
        raise KitFehler(
            f"Der Token gehört zu @{name}, in einstellungen.yml steht aber @{erwartet}. "
            "Es wurde NICHT gepostet. Bitte instagram_name oder den Token korrigieren."
        )
    return uid


def oeffentliche_url(datei, branch="media"):
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise KitFehler("GITHUB_REPOSITORY fehlt (läuft das außerhalb von GitHub Actions?).")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{os.path.basename(datei)}"


def _container(uid, token, post, url):
    daten = {"access_token": token}
    if post["typ"] == "reel":
        daten.update(media_type="REELS", video_url=url, caption=post["caption"])
    elif post["typ"] == "story":
        daten.update(media_type="STORIES", image_url=url)
    else:
        daten.update(image_url=url, caption=post["caption"])
    resp = SITZUNG.post(f"{API}/{uid}/media", data=daten, timeout=60)
    if not resp.ok:
        raise _fehler(resp)
    return resp.json()["id"]


def _warten(container_id, token, schlafen=time.sleep):
    for _ in range(WARTEN_VERSUCHE):
        status = _get(container_id, token, fields="status_code,status").get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise KitFehler("Instagram konnte die Datei nicht verarbeiten (status ERROR).")
        schlafen(WARTEN_SEKUNDEN)
    raise KitFehler("Instagram hat die Datei nicht rechtzeitig verarbeitet. Beim nächsten Lauf wird es erneut versucht.")


def veroeffentlichen(token, uid, post, schlafen=time.sleep):
    url = oeffentliche_url(post["datei"])
    for runde in (1, 2):
        cid = _container(uid, token, post, url)
        _warten(cid, token, schlafen)
        resp = SITZUNG.post(f"{API}/{uid}/media_publish", data={"creation_id": cid, "access_token": token},
                            timeout=60)
        if resp.ok:
            return resp.json().get("id")
        if runde == 2 or "2207006" not in resp.text:  # 2207006 = Container verschwunden, neu anlegen hilft
            raise _fehler(resp)
        schlafen(20)
    return None


# ---------------------------------------------------------------- Token-Erneuerung

def token_erneuern(token):
    """Verlängert den Token um 60 Tage. Gibt (neuer_token, tage) zurück."""
    resp = SITZUNG.get(REFRESH_URL, params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
    if not resp.ok:
        raise _fehler(resp)
    daten = resp.json()
    return daten["access_token"], int(daten.get("expires_in", 0)) // 86400


def secret_speichern(name, wert, ausfuehren=subprocess.run):
    """Speichert das GitHub-Secret mit der GitHub-CLI (Wert über stdin, nie im Log)."""
    if not os.environ.get("GH_TOKEN"):
        raise KitFehler(
            "Das Secret SECRETS_WRITE_TOKEN fehlt, deshalb kann der verlängerte Token nicht gespeichert "
            "werden. Anleitung Schritt 6."
        )
    befehl = ["gh", "secret", "set", name, "--repo", os.environ.get("GITHUB_REPOSITORY", "")]
    ergebnis = ausfuehren(befehl, input=wert, text=True, capture_output=True)
    if ergebnis.returncode != 0:
        raise KitFehler(
            "Der neue Token konnte nicht gespeichert werden. Hat SECRETS_WRITE_TOKEN die Berechtigung "
            "'Secrets: Read and write' für genau dieses Repository?"
        )
