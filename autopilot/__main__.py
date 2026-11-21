"""Insta-Autopilot – Befehle:

  python -m autopilot lauf --aktion automatisch   alles, was der GitHub-Workflow braucht
  python -m autopilot pruefen                     Einrichtung prüfen
  python -m autopilot vorschau                    alles erzeugen, nichts posten
  python -m autopilot erstellen --typ reel        einzelnen Post erzeugen (zum Testen)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

from . import design, inhalte, instagram, reel, reels
from .einstellungen import AUSGABE, ROOT, VERLAUF, KitFehler, laden

AKTIONEN = ("automatisch", "setup-pruefen", "vorschau", "jetzt-posten", "jetzt-story-posten", "token-erneuern")


def _zusammenfassung(text):
    pfad = os.environ.get("GITHUB_STEP_SUMMARY")
    if pfad:
        with open(pfad, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def _maskieren(wert):
    if wert and os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{wert}")


def _token():
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        raise KitFehler("Das GitHub-Secret IG_ACCESS_TOKEN fehlt. Siehe Anleitung, Instagram-Zugang.")
    _maskieren(token)
    return token


def _jetzt(cfg):
    return datetime.now(cfg["zeitzone"])


def _lesen(typ):
    pfad = os.path.join(AUSGABE, f"{typ}.json")
    if not os.path.exists(pfad):
        return None
    with open(pfad, encoding="utf-8") as f:
        return json.load(f)


def _schreiben(post):
    os.makedirs(AUSGABE, exist_ok=True)
    with open(os.path.join(AUSGABE, f"{post['typ']}.json"), "w", encoding="utf-8") as f:
        json.dump(post, f, ensure_ascii=False, indent=2)
    print(f"Erstellt: {post['datei']}  ({post['text'][:60]})")
    return post


def _rel(pfad):
    return os.path.relpath(pfad, ROOT).replace("\\", "/")


# ---------------------------------------------------------------- erstellen

def _zitat_fuer_story(cfg, verlauf, eintraege):
    bild = _lesen("bild")
    gesucht = bild["eintrag_id"] if bild else None
    if not gesucht and verlauf["heute_bild"].get("datum") == _jetzt(cfg).date().isoformat():
        gesucht = verlauf["heute_bild"].get("id")
    treffer = [e for e in eintraege if e["id"] == gesucht]
    hg = bild["hintergrund"] if bild and treffer else None
    return (treffer[0] if treffer else inhalte.naechster(eintraege, verlauf, "bild", cfg["reihenfolge"])), hg


def erstellen(cfg, typ, verlauf=None, eintraege=None, sprecher_fabrik=None):
    verlauf = verlauf if verlauf is not None else inhalte.verlauf_laden()
    os.makedirs(AUSGABE, exist_ok=True)
    stempel = _jetzt(cfg).strftime("%Y%m%d_%H%M")
    art = cfg["inhaltsart"]

    if typ == "story" and art != "zitate":
        reel_post = _lesen("reel")
        if not reel_post or not reel_post.get("titelbild"):
            raise KitFehler("Die Story zeigt das Titelbild des Reels. Es gibt heute noch kein Reel.")
        datei = os.path.join(AUSGABE, f"story_{stempel}.jpg")
        shutil.copy(os.path.join(ROOT, reel_post["titelbild"]), datei)
        return _schreiben({"typ": "story", "datei": _rel(datei), "caption": "", "text": reel_post["text"],
                           "hintergrund": None})

    if typ in ("bild", "story"):
        eintraege = eintraege or inhalte.posts_laden()
        if typ == "story":
            eintrag, hg = _zitat_fuer_story(cfg, verlauf, eintraege)
        else:
            eintrag, hg = inhalte.naechster(eintraege, verlauf, "bild", cfg["reihenfolge"]), None
        hg = hg or design.hintergrund_waehlen(cfg, verlauf)
        datei = os.path.join(AUSGABE, f"{typ}_{stempel}_{eintrag['id']}.jpg")
        design.bild_zeichnen(cfg, eintrag, hg, design.FEED if typ == "bild" else design.HOCH, datei)
        return _schreiben({"typ": typ, "datei": _rel(datei), "eintrag_id": eintrag["id"], "text": eintrag["text"],
                           "hintergrund": hg,
                           "caption": "" if typ == "story" else inhalte.caption_bauen(cfg, eintrag)})

    # ---- Reel
    musik = reel.musik_waehlen()
    if art == "zitate":
        eintraege = eintraege or inhalte.posts_laden()
        eintrag = inhalte.naechster(eintraege, verlauf, "reel", cfg["reihenfolge"])
        hg = design.hintergrund_waehlen(cfg, verlauf)
        datei = os.path.join(AUSGABE, f"reel_{stempel}_{eintrag['id']}.mp4")
        reel.reel_bauen(cfg, eintrag, hg, datei, musik=musik)
        return _schreiben({"typ": "reel", "datei": _rel(datei), "eintrag_id": eintrag["id"], "text": eintrag["text"],
                           "hintergrund": hg, "caption": inhalte.caption_bauen(cfg, eintrag)})

    if art == "geschichten":
        from . import geschichten, sprecher

        skript = geschichten.neue_geschichte(cfg["geschichten"], verlauf)
        fabrik = sprecher_fabrik or sprecher.Sprecher
        stimme = fabrik(cfg["geschichten"]["sprechtempo"]) if cfg["geschichten"]["sprecher"] == "thorsten" else None
        datei = os.path.join(AUSGABE, f"reel_{stempel}.mp4")
        dauer, titel, quellen = reels.geschichten_reel(cfg, skript, datei, musik, stimme)
        return _schreiben({"typ": "reel", "datei": _rel(datei), "titelbild": _rel(titel),
                           "text": skript["hook"]["text"].replace("*", ""), "skript": skript,
                           "merken": skript["merken"], "bildquellen": quellen, "dauer": dauer,
                           "caption": reels.geschichten_caption(cfg, skript), "hintergrund": None})

    # eigene_medien
    dateien = reels.medien_waehlen(cfg, verlauf)
    if not dateien:
        raise KitFehler("Im Ordner medien liegen noch keine Fotos oder Videos. Lade welche hoch (Anleitung).")
    eintrag = None
    if cfg["eigene_medien"]["text_einblenden"]:
        eintraege = eintraege or inhalte.posts_laden()
        eintrag = inhalte.naechster(eintraege, verlauf, "reel", cfg["reihenfolge"])
    datei = os.path.join(AUSGABE, f"reel_{stempel}.mp4")
    dauer, titel = reels.medien_reel(cfg, dateien, datei, eintrag, musik)
    leer = {"text": "", "autor": "", "kategorie": ""}
    return _schreiben({"typ": "reel", "datei": _rel(datei), "titelbild": _rel(titel), "medien": dateien,
                       "eintrag_id": eintrag["id"] if eintrag else None,
                       "text": eintrag["text"] if eintrag else ", ".join(dateien), "dauer": dauer,
                       "caption": inhalte.caption_bauen(cfg, eintrag or leer), "hintergrund": None})


# ---------------------------------------------------------------- posten

def posten(cfg, typ):
    post = _lesen(typ)
    if not post:
        raise KitFehler(f"Für {typ} wurde nichts erzeugt.")
    token = _token()
    uid = instagram.konto_pruefen(token, cfg["instagram_name"], cfg["instagram_konto_id"])
    media_id = instagram.veroeffentlichen(token, uid, post)

    verlauf = inhalte.verlauf_laden()
    heute = _jetzt(cfg).date().isoformat()
    verlauf["zuletzt"][typ] = heute
    if post.get("eintrag_id") and typ in ("bild", "reel"):
        alle = [e["id"] for e in inhalte.posts_laden()]
        inhalte.als_benutzt_markieren(verlauf, typ, post["eintrag_id"], alle)
    if typ == "bild":
        verlauf["heute_bild"] = {"datum": heute, "id": post["eintrag_id"]}
    if post.get("merken"):
        verlauf["wiki_benutzt"] = (verlauf.get("wiki_benutzt", []) + post["merken"])[-2000:]
    if post.get("medien"):
        alle = reels.eigene_medien_liste()
        benutzt = [m for m in verlauf.get("medien_benutzt", []) if m in alle and m not in post["medien"]]
        if set(alle) <= set(benutzt + post["medien"]):
            benutzt = []  # Runde komplett, neue beginnt
        verlauf["medien_benutzt"] = benutzt + post["medien"]
    if post.get("hintergrund"):
        verlauf["hintergruende"] = (verlauf.get("hintergruende", []) + [post["hintergrund"]])[-design.MERKEN:]
    inhalte.verlauf_speichern(verlauf)
    print(f"✅ {typ} veröffentlicht (Instagram-ID {media_id})")
    _zusammenfassung(f"✅ **{typ}** veröffentlicht: {post['text'][:120]}")


# ---------------------------------------------------------------- token

def token_erneuern(cfg):
    token = _token()
    if instagram.ist_systemnutzer_token(token):
        print("Der Token ist ein Systemnutzer-Token und läuft nie ab. Nichts zu tun.")
        _zusammenfassung("🔑 Systemnutzer-Token: läuft nie ab, keine Verlängerung nötig.")
        return
    neu, tage = instagram.token_erneuern(token)
    _maskieren(neu)
    if neu != token:
        instagram.secret_speichern("IG_ACCESS_TOKEN", neu)
    verlauf = inhalte.verlauf_laden()
    verlauf["token_erneuert"] = _jetzt(cfg).date().isoformat()
    inhalte.verlauf_speichern(verlauf)
    print(f"✅ Token verlängert, gültig noch {tage} Tage.")
    _zusammenfassung(f"🔑 Token verlängert, gültig noch {tage} Tage.")


# ---------------------------------------------------------------- pruefen

def _cloudflare_ok():
    konto = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not konto or not token:
        return False, "Secrets CLOUDFLARE_ACCOUNT_ID und CLOUDFLARE_API_TOKEN fehlen (Anleitung: Cloudflare)"
    _maskieren(token)
    kopf = {"Authorization": f"Bearer {token}"}
    for url in (f"https://api.cloudflare.com/client/v4/accounts/{konto}/tokens/verify",
                "https://api.cloudflare.com/client/v4/user/tokens/verify"):
        try:
            if instagram.SITZUNG.get(url, headers=kopf, timeout=30).ok:
                return True, "Cloudflare-Zugang gültig"
        except Exception:  # noqa: BLE001, S112 - nächste Prüfadresse versuchen
            continue
    return False, "Cloudflare lehnt den API-Token ab. Account-ID und Token prüfen (Anleitung: Cloudflare)"


NAMEN = {"zitate": "Zitat-Posts", "geschichten": "KI-Story-Reels", "eigene_medien": "Reels aus eigenen Medien"}


def pruefen():
    zeilen, fehler = ["## Einrichtung prüfen", ""], 0

    def ok(text):
        zeilen.append(f"- ✅ {text}")

    def schlecht(text):
        nonlocal fehler
        fehler += 1
        zeilen.append(f"- ❌ {text}")

    try:
        cfg = laden()
        ok(f"einstellungen.yml in Ordnung: @{cfg['instagram_name']}, Inhaltsart {NAMEN[cfg['inhaltsart']]}")
    except KitFehler as exc:
        schlecht(str(exc))
        cfg = None

    art = cfg["inhaltsart"] if cfg else None
    if art in ("zitate", "eigene_medien"):
        try:
            ok(f"posts.csv: {len(inhalte.posts_laden())} Texte gefunden")
        except KitFehler as exc:
            schlecht(str(exc))
    if art == "zitate":
        fotos = design.eigene_hintergruende()
        ok(f"Hintergründe: {len(fotos)} eigene Fotos" if fotos else "Hintergründe: Farbverläufe (keine eigenen Fotos)")
    if art == "geschichten":
        from . import geschichten
        quelle = cfg["geschichten"]["quelle"]
        if quelle == "eigene_texte":
            n = len(geschichten.eigene_texte_laden())
            (ok if n else schlecht)(f"inhalte/geschichten.txt: {n} eigene Texte" if n else
                                    "inhalte/geschichten.txt enthält noch keinen Text")
        else:
            ok({"wikipedia": "Quelle: Wikipedia (wahre Geschichten mit Quellenangabe)",
                "fiktion": "Quelle: Fiktion (frei erfundene Geschichten, in der Caption gekennzeichnet)"}[quelle])
        erfolg, text = _cloudflare_ok()
        (ok if erfolg else schlecht)(text)
        if cfg["geschichten"]["text_ki"] == "claude":
            if os.environ.get("ANTHROPIC_API_KEY", "").strip():
                ok("Claude-API-Schlüssel hinterlegt (kostenpflichtige Option)")
            else:
                schlecht("text_ki ist \"claude\", aber das Secret ANTHROPIC_API_KEY fehlt")
    if art == "eigene_medien":
        anzahl, n = len(reels.eigene_medien_liste()), cfg["eigene_medien"]["pro_reel"]
        if anzahl == 0:
            schlecht("Der Ordner medien ist leer. Lade Fotos oder Videos hoch")
        else:
            ok(f"{anzahl} Fotos/Videos im Ordner medien (reicht für {max(1, anzahl // n)} Reels ohne Wiederholung)")
    if cfg:
        ok("Musik für Reels gefunden" if reel.musik_waehlen() else "Keine Musik im Ordner musik: Reels ohne Musik")

    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        try:
            antwort = instagram.SITZUNG.get(f"https://api.github.com/repos/{repo}", timeout=30,
                                            headers={"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}"})
            if antwort.ok and antwort.json().get("private"):
                schlecht("Das Repository ist privat. Settings → General → ganz unten 'Change visibility' → Public")
            elif antwort.ok:
                ok("Repository ist öffentlich")
        except Exception as exc:  # noqa: BLE001
            print(f"Hinweis: Sichtbarkeit nicht prüfbar ({type(exc).__name__})")

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        schlecht("Secret IG_ACCESS_TOKEN fehlt")
    else:
        _maskieren(token)
        try:
            _, name = instagram.konto(token, cfg["instagram_konto_id"] if cfg else None)
            if cfg and name.lower() != cfg["instagram_name"].lower():
                schlecht(f"Token gehört zu @{name}, in einstellungen.yml steht @{cfg['instagram_name']}")
            else:
                ok(f"Instagram-Token gültig für @{name}")
        except KitFehler as exc:
            schlecht(str(exc))

    if token and instagram.ist_systemnutzer_token(token):
        ok("Systemnutzer-Token: läuft nie ab, SECRETS_WRITE_TOKEN wird nicht gebraucht")
    elif os.environ.get("GH_TOKEN"):
        ok("SECRETS_WRITE_TOKEN hinterlegt (Token-Verlängerung läuft automatisch)")
    elif token:
        schlecht("Secret SECRETS_WRITE_TOKEN fehlt: dein Instagram-Token (IGAA…) läuft sonst nach 60 Tagen ab")

    if cfg:
        tage_namen = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        for typ in ("bild", "reel"):
            p = cfg["plan"][typ]
            if p["aktiv"]:
                tage = ", ".join(tage_namen[t] for t in p["tage"])
                ok(f"{typ.capitalize()}: {tage} ab {p['uhrzeit'][0]:02d}:{p['uhrzeit'][1]:02d} Uhr")
        if cfg["plan"]["story"]["aktiv"]:
            ok("Story: zusammen mit dem " + ("Tages-Bild" if art == "zitate" else "Reel"))

    zeilen += ["", "**Alles bereit!** 🎉" if not fehler else f"**{fehler} Punkt(e) noch offen.** Siehe ❌ oben."]
    text = "\n".join(zeilen)
    print(text)
    _zusammenfassung(text)
    return fehler == 0


# ---------------------------------------------------------------- vorschau

def vorschau(cfg, sprecher_fabrik=None):
    verlauf = inhalte.verlauf_laden()  # wird NICHT gespeichert
    typen = (["bild"] if cfg["inhaltsart"] == "zitate" else []) + ["reel", "story"]
    teile = ["## Vorschau (nichts wurde gepostet)", "", "Unten unter **Artifacts** → *vorschau* herunterladen.", ""]
    for typ in typen:
        post = erstellen(cfg, typ, verlauf, sprecher_fabrik=sprecher_fabrik)
        teile.append(f"- **{typ}**: {post['text'][:120]}")
        if post["caption"]:
            teile.append(f"  Caption: `{post['caption'][:140].replace(chr(10), ' ')}…`")
        if "farbverlauf" in post.get("bildquellen", []):
            teile.append("  ⚠️ Einige KI-Bilder fehlten und wurden durch Farbverläufe ersetzt.")
    _zusammenfassung("\n".join(teile))


# ---------------------------------------------------------------- git

def _git(*args, cwd=ROOT, check=True):
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def medien_bereitstellen():
    """Legt die fertigen Dateien in den Branch "media", den Instagram öffentlich abrufen kann.
    Der Branch wird jedes Mal ersetzt, damit das Repository klein bleibt."""
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        raise KitFehler("GITHUB_REPOSITORY/GITHUB_TOKEN fehlen (läuft das außerhalb von GitHub?).")
    ordner = tempfile.mkdtemp(prefix="media_")
    for datei in os.listdir(AUSGABE):
        if datei.lower().endswith((".jpg", ".mp4")):
            shutil.copy(os.path.join(AUSGABE, datei), ordner)
    wer = ["-c", "user.name=autopilot", "-c", "user.email=autopilot@users.noreply.github.com"]
    _git("init", "-q", "-b", "media", cwd=ordner)
    _git(*wer, "add", "-A", cwd=ordner)
    _git(*wer, "commit", "-qm", "Medien", cwd=ordner)
    _git("push", "-qf", f"https://x-access-token:{token}@github.com/{repo}.git", "media", cwd=ordner)
    time.sleep(20)  # bis die Dateien öffentlich abrufbar sind


def verlauf_sichern():
    if not os.path.exists(VERLAUF) or not os.environ.get("GITHUB_ACTIONS"):
        return
    _git("config", "user.name", "autopilot")
    _git("config", "user.email", "autopilot@users.noreply.github.com")
    _git("add", os.path.relpath(VERLAUF, ROOT))
    if _git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    _git("commit", "-qm", "Verlauf aktualisiert")
    for _ in range(3):
        if _git("pull", "-q", "--rebase", check=False).returncode == 0 and _git("push", "-q", check=False).returncode == 0:
            return
        time.sleep(5)
    print("::warning::Verlauf konnte nicht gespeichert werden.")


# ---------------------------------------------------------------- lauf

def lauf(aktion, bereitstellen=None):
    if aktion == "setup-pruefen":
        return 0 if pruefen() else 1
    cfg = laden()
    if aktion == "vorschau":
        vorschau(cfg)
        return 0

    bereitstellen = bereitstellen or medien_bereitstellen
    verlauf = inhalte.verlauf_laden()
    haupt = "bild" if cfg["inhaltsart"] == "zitate" else "reel"
    nur_story = aktion == "jetzt-story-posten"
    if aktion == "automatisch":
        typen = inhalte.faellig(cfg, verlauf, _jetzt(cfg))
        token = (not instagram.ist_systemnutzer_token(os.environ.get("IG_ACCESS_TOKEN", "").strip())
                 and inhalte.token_faellig(verlauf, _jetzt(cfg).date()))
        inhalte.verlauf_speichern(verlauf)
    elif aktion == "jetzt-posten":
        typen, token = [haupt] + (["story"] if cfg["plan"]["story"]["aktiv"] else []), False
    elif nur_story:
        typen, token = ([haupt, "story"] if haupt == "reel" else ["story"]), False
    else:
        typen, token = [], aktion == "token-erneuern"
    if not typen and not token:
        print("Gerade ist nichts dran. Der nächste Lauf prüft in einer Stunde wieder.")
        verlauf_sichern()
        return 0

    fehler = 0
    try:
        erzeugt = []
        for typ in typen:
            try:
                erstellen(cfg, typ, verlauf)
                erzeugt.append(typ)
            except KitFehler as exc:
                print(f"::error::{exc}")
                _zusammenfassung(f"❌ {typ}: {exc}")
                fehler = 1
        if "wiki_abgelehnt" in verlauf:  # ungeeignete Artikel nicht jeden Tag erneut prüfen
            gespeichert = inhalte.verlauf_laden()
            gespeichert["wiki_abgelehnt"] = verlauf["wiki_abgelehnt"]
            inhalte.verlauf_speichern(gespeichert)
        posten_liste = [t for t in erzeugt if not (nur_story and t == "reel" and haupt == "reel")]
        if posten_liste:
            bereitstellen()
        for typ in posten_liste:
            try:
                posten(cfg, typ)
            except KitFehler as exc:
                print(f"::error::{exc}")
                _zusammenfassung(f"❌ {typ}: {exc}")
                fehler = 1
        if token:
            token_erneuern(cfg)
    finally:
        verlauf_sichern()
    return fehler


def main(argv=None):
    parser = argparse.ArgumentParser(prog="autopilot")
    unter = parser.add_subparsers(dest="befehl", required=True)
    unter.add_parser("lauf").add_argument("--aktion", default="automatisch", choices=AKTIONEN)
    unter.add_parser("erstellen").add_argument("--typ", choices=["bild", "story", "reel"], required=True)
    unter.add_parser("pruefen")
    unter.add_parser("vorschau")
    args = parser.parse_args(argv)
    try:
        if args.befehl == "lauf":
            return lauf(args.aktion)
        if args.befehl == "pruefen":
            return 0 if pruefen() else 1
        cfg = laden()
        if args.befehl == "vorschau":
            vorschau(cfg)
        else:
            erstellen(cfg, args.typ)
    except KitFehler as exc:
        print(f"::error::{exc}" if os.environ.get("GITHUB_ACTIONS") else f"FEHLER: {exc}")
        _zusammenfassung(f"❌ {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
