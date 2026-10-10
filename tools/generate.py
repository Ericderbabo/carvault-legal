#!/usr/bin/env python3
"""Erzeugt die Rechtstext-Seiten aus dem, was der CarVault-Server gerade ausliefert.

Die Seiten sind ein Abzug der Datenbanktexte (legal_documents). Nach jeder Content-Migration
neu erzeugen, sonst widersprechen sich App und Webseite:

    python3 tools/generate.py            # holt von https://api.carvaultapp.de
    python3 tools/generate.py --api URL  # anderer Server

Deutsch ist Quelle und maßgeblich (L10); die englischen Seiten liegen unter en/.
Die Seiten "Konto löschen" (konto-loeschen.html, en/delete-account.html) kommen nicht vom Server;
ihr Text steht unten in DELETE_BODY und wird mit erzeugt, damit Navigation und Aussehen gleich bleiben.
Die Index-Seite (index.html) ebenso.
"""
import argparse
import datetime
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STYLE = (
    "body{font:16px/1.6 system-ui,sans-serif;max-width:46rem;margin:0 auto;padding:1.5rem 16px;"
    "color:#1b1b1b;background:#fff}h2{margin-top:2rem;font-size:1.25rem}nav a{margin-right:1rem}"
    ".meta{margin-top:3rem;font-size:.875rem;color:#666}"
    "@media(prefers-color-scheme:dark){body{background:#121212;color:#e8e8e8}a{color:#8ab4f8}.meta{color:#aaa}}"
)

LANGS = {
    "de": {
        "dir": "",
        "pages": {
            "privacy-policy": ("datenschutz.html", "Datenschutzerklärung"),
            "imprint": ("impressum.html", "Impressum"),
            "terms": ("agb.html", "Nutzungsbedingungen"),
        },
        "delete": ("konto-loeschen.html", "Konto löschen"),
        "other": ("English", "en/"),
        "meta": "Stand: {date} (Version {version})",
        "months": None,
    },
    "en": {
        "dir": "en/",
        "pages": {
            "privacy-policy": ("privacy.html", "Privacy Policy"),
            "imprint": ("imprint.html", "Imprint"),
            "terms": ("terms.html", "Terms of Use"),
        },
        "delete": ("delete-account.html", "Delete account"),
        "other": ("Deutsch", "../"),
        "meta": "Last updated: {date} (version {version}). The German version is authoritative.",
        "months": ["January", "February", "March", "April", "May", "June", "July", "August",
                   "September", "October", "November", "December"],
    },
}


def nav(lang, current_file):
    cfg = LANGS[lang]
    links = [cfg["pages"][d] for d in ("privacy-policy", "imprint", "terms")] + [cfg["delete"]]
    parts = [f'<a href="{f}">{html.escape(t)}</a>' for f, t in links]
    label, href = cfg["other"]
    other_file = LANGS["en" if lang == "de" else "de"]
    target = current_file
    for doc, (f, _) in cfg["pages"].items():
        if f == current_file:
            target = other_file["pages"][doc][0]
    if current_file == cfg["delete"][0]:
        target = other_file["delete"][0]
    parts.append(f'<a href="{href}{target}" hreflang="{"en" if lang == "de" else "de"}">{label}</a>')
    return "<nav>" + "".join(parts) + "</nav>"


def inline(text):
    out = html.escape(text, quote=True)
    # Fett darf über einen Zeilenumbruch gehen; Umbrüche werden erst danach zu <br>.
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out, flags=re.S)
    return out.replace("\n", "<br>")


def to_html(markdown):
    """Kleines Markdown wie in legal_documents: '## ' Überschriften, '- ' Listen, '**fett**'.
    Die erste Überschrift wird h1, Zeilenumbrüche im Absatz bleiben als <br> erhalten."""
    blocks = re.split(r"\n\s*\n", markdown.strip())
    out = []
    first_heading = True
    for block in blocks:
        lines = block.split("\n")
        if len(lines) == 1 and lines[0].startswith("## "):
            tag = "h1" if first_heading else "h2"
            first_heading = False
            out.append(f"<{tag}>{inline(lines[0][3:].strip())}</{tag}>")
            continue
        if all(re.match(r"^\s*- ", l) for l in lines):
            items = "".join(f"<li>{inline(re.sub(r'^\s*- ', '', l))}</li>" for l in lines)
            out.append(f"<ul>{items}</ul>")
            continue
        if any(l.startswith("## ") or re.match(r"^\s*- ", l) for l in lines):
            # gemischter Block: zeilenweise zerlegen
            para, items = [], []
            for l in lines:
                if l.startswith("## "):
                    raise SystemExit(f"Überschrift mitten im Absatz: {l!r}")
                if re.match(r"^\s*- ", l):
                    if para:
                        out.append("<p>" + inline("\n".join(para)) + "</p>")
                        para = []
                    items.append(re.sub(r"^\s*- ", "", l))
                else:
                    if items:
                        out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
                        items = []
                    para.append(l)
            if para:
                out.append("<p>" + inline("\n".join(para)) + "</p>")
            if items:
                out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            continue
        out.append("<p>" + inline("\n".join(lines)) + "</p>")
    return "\n".join(out)


def fmt_date(iso, lang):
    d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    d = d.astimezone(datetime.timezone(datetime.timedelta(hours=2)))  # Berlin, Sommerzeit reicht als Tag
    if lang == "de":
        return d.strftime("%d.%m.%Y")
    return f"{d.day} {LANGS['en']['months'][d.month - 1]} {d.year}"


def page(lang, filename, title, body, meta=""):
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>CarVault – {html.escape(title)}</title><style>{STYLE}</style></head><body>"
        f"{nav(lang, filename)}{body}"
        + (f'\n<p class="meta">{html.escape(meta)}</p>' if meta else "")
        + "</body></html>\n"
    )


DELETE_BODY = {
    "de": (
        "<h1>Konto und Daten löschen</h1>\n"
        "<p>Du kannst dein CarVault-Konto jederzeit selbst löschen. Dabei werden alle ausschließlich dir zugeordneten "
        "Daten sofort und endgültig gelöscht, darunter Sichtungen, Fotos, Sammlung, Freundschaften und Einstellungen. "
        "Ausnahmen und Details stehen in der <a href=\"datenschutz.html\">Datenschutzerklärung</a>, Abschnitt 14 und 15.</p>\n"
        "<h2>In der App</h2>\n"
        "<ol><li>CarVault öffnen und anmelden.</li><li>Einstellungen öffnen.</li><li>„Konto löschen“ antippen und bestätigen.</li></ol>\n"
        "<p>Ein laufendes Abo über Google Play wird dabei von uns gekündigt. Ein Abo über den App Store musst du selbst "
        "in den Abos deines Apple-Kontos beenden.</p>\n"
        "<h2>Ohne Zugriff auf die App</h2>\n"
        "<p>Kannst du die App nicht mehr öffnen, schreib uns von der E-Mail-Adresse deines Kontos an "
        "<a href=\"mailto:support@carvaultapp.de\">support@carvaultapp.de</a> mit dem Betreff „Konto löschen“. "
        "Wir löschen das Konto und antworten dir, sobald es erledigt ist.</p>\n"
        "<h2>Datenexport</h2>\n"
        "<p>Vor dem Löschen kannst du in der App unter Einstellungen → „Meine Daten exportieren“ alle Daten herunterladen.</p>"
    ),
    "en": (
        "<h1>Delete your account and data</h1>\n"
        "<p>You can delete your CarVault account yourself at any time. All data assigned only to you is deleted "
        "immediately and permanently, including sightings, photos, collection, friendships and settings. "
        "Exceptions and details are in the <a href=\"privacy.html\">Privacy Policy</a>, Sections 14 and 15.</p>\n"
        "<h2>In the app</h2>\n"
        "<ol><li>Open CarVault and sign in.</li><li>Open Settings.</li><li>Tap “Delete account” and confirm.</li></ol>\n"
        "<p>We cancel an active Google Play subscription for you. A subscription through the App Store has to be "
        "ended by you in the subscriptions of your Apple account.</p>\n"
        "<h2>Without access to the app</h2>\n"
        "<p>If you can no longer open the app, write to us from your account’s email address at "
        "<a href=\"mailto:support@carvaultapp.de\">support@carvaultapp.de</a> with the subject “Delete account”. "
        "We delete the account and reply once it is done.</p>\n"
        "<h2>Data export</h2>\n"
        "<p>Before deleting, you can download all your data in the app under Settings → “Export my data”.</p>"
    ),
}


def index_page():
    def links(lang):
        cfg = LANGS[lang]
        items = [cfg["pages"][d] for d in ("privacy-policy", "imprint", "terms")] + [cfg["delete"]]
        return "".join(f'<a href="{cfg["dir"]}{f}">{html.escape(t)}</a>' for f, t in items)
    return (
        '<!doctype html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>CarVault – Rechtliches / Legal</title><style>{STYLE}</style></head><body><h1>CarVault</h1>"
        f'<h2>Deutsch</h2><nav>{links("de")}</nav><h2 lang="en">English</h2><nav lang="en">{links("en")}</nav>'
        "</body></html>\n"
    )


def fetch(api, doc, lang):
    with urllib.request.urlopen(f"{api}/legal/{doc}?lang={lang}", timeout=30) as r:
        data = json.load(r)
    if data.get("locale") != lang:
        raise SystemExit(f"{doc}?lang={lang}: Server liefert {data.get('locale')!r} – "
                         "englische Fassung veraltet (source_version), erst die Datenbank nachziehen")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="https://api.carvaultapp.de")
    args = ap.parse_args()
    for lang, cfg in LANGS.items():
        (ROOT / cfg["dir"]).mkdir(exist_ok=True)
        for doc, (filename, title) in cfg["pages"].items():
            data = fetch(args.api, doc, lang)
            meta = cfg["meta"].format(date=fmt_date(data["updatedAt"], lang), version=data["version"])
            (ROOT / cfg["dir"] / filename).write_text(
                page(lang, filename, title, to_html(data["content"]), meta), encoding="utf-8")
            print(f"{cfg['dir']}{filename}: {doc} {lang} Version {data['version']}")
        filename, title = cfg["delete"]
        (ROOT / cfg["dir"] / filename).write_text(
            page(lang, filename, title, DELETE_BODY[lang]), encoding="utf-8")
    (ROOT / "index.html").write_text(index_page(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
