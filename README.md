# Insta-Autopilot

Postet automatisch auf deinen Instagram-Account. Du wählst eine Inhaltsart:
Sprüche als Bild/Story/Reel, KI-Story-Reels mit Sprecher oder Reels aus deinen eigenen Fotos und Videos.
Läuft kostenlos auf GitHub, dein Computer muss nicht an sein. Gepostet wird über die
offizielle Instagram-Schnittstelle, ohne Login-Bot.

**Die komplette Schritt-für-Schritt-Anleitung liegt bei deinem Kauf bei.**

## Was du später anpasst

| Datei / Ordner | Wofür |
|---|---|
| `einstellungen.yml` | Inhaltsart, Account-Name, Uhrzeiten, Farben, Hashtags, Thema der Geschichten |
| `inhalte/posts.csv` | Deine Sprüche (mit Excel, Numbers oder Google Sheets bearbeiten) |
| `medien/` | Deine Fotos und Videos (Inhaltsart „eigene_medien“) |
| `hintergruende/` | Optional: eigene Hintergrundfotos für Zitat-Posts |
| `musik/` | Optional: Musik für Reels |

Alles andere (`autopilot/`, `.github/`, `schriften/`, `daten/`) bitte nicht verändern.

## Von Hand starten

Reiter **Actions** → **Instagram Autopilot** → **Run workflow** → Aktion wählen:

- `setup-pruefen`: prüft, ob alles richtig eingerichtet ist (packt beim ersten Mal das Kit aus)
- `vorschau`: erzeugt alles zum Ansehen, **postet nichts**
- `jetzt-posten`: postet sofort den Haupt-Post (und die Story, falls aktiv)
- `jetzt-story-posten`: postet nur die Story
- `token-erneuern`: verlängert den Instagram-Zugang von Hand

## Für Entwickler

```
pip install -r requirements.txt pytest
python -m pytest
python -m autopilot vorschau   # Ergebnis in ausgabe/
```

Schriftart Poppins: SIL Open Font License, siehe `schriften/OFL.txt`.
Sprecher-Stimme „Thorsten“ (Thorsten Müller, Piper TTS): Datensatz CC0. Piper wird beim Lauf
auf GitHub installiert und nicht mit dem Kit verteilt.
