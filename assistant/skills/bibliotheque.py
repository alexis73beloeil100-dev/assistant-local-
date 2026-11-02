"""La bibliotheque locale : de la documentation de reference, sur le PC.

Le modele a appris a coder pendant son entrainement, mais un petit modele
oublie des details, et son savoir s'arrete a une date. Plutot que de
chercher sur Internet a chaque question, on telecharge UNE fois des
documentations de reference, on les decoupe et on les indexe (SQLite FTS5) :
la recherche repond ensuite en une fraction de seconde, meme hors ligne.

Sources :
  - python      : documentation officielle de Python (texte), docs.python.org
                  -- licence PSF ;
  - cppreference: la reference du C++ et de sa bibliotheque standard, archive
                  hors ligne publiee par le projet cppreference-doc
                  -- CC-BY-SA 3.0 et GFDL.

Rien n'est livre avec l'application : tout se telecharge a la demande, et se
retelecharge apres une reinitialisation du PC.
"""
from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from pathlib import Path

from assistant import config, safety

DOSSIER = config.DATA_DIR / "bibliotheque"
BASE = DOSSIER / "bibliotheque.db"
DELAI = 60
MORCEAU = 1800
AGENT = "AssistantLocal/1.0 (https://github.com/alexis73beloeil100-dev/assistant-local-)"

PYTHON_PAGE = "https://docs.python.org/3/download.html"
CPP_RELEASE = "https://api.github.com/repos/PeterFeicht/cppreference-doc/releases/latest"
CPP_SECOURS = ("https://github.com/PeterFeicht/cppreference-doc/releases/download/"
               "v20220730/html-book-20220730.zip")

SOURCES = {
    "python": "Documentation officielle de Python (licence PSF)",
    "cppreference": "Reference du C++ et de sa bibliotheque standard (CC-BY-SA 3.0)",
}


def _connexion() -> sqlite3.Connection:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(BASE)
    c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
              "source UNINDEXED, titre, chemin UNINDEXED, texte, "
              "tokenize='unicode61 remove_diacritics 2')")
    return c


# --- Decouper ----------------------------------------------------------------

def decouper(texte: str, taille: int = MORCEAU) -> list[str]:
    """Des morceaux d'environ `taille` caracteres, coupes entre paragraphes."""
    paragraphes = [p.strip() for p in re.split(r"\n\s*\n", texte) if p.strip()]
    morceaux, courant = [], ""
    for p in paragraphes:
        if courant and len(courant) + len(p) > taille:
            morceaux.append(courant)
            courant = ""
        courant = f"{courant}\n\n{p}" if courant else p
        while len(courant) > taille * 2:
            morceaux.append(courant[:taille])
            courant = courant[taille:]
    if courant:
        morceaux.append(courant)
    return morceaux


def indexer_archive(source: str, donnees: bytes) -> int:
    """Indexe une archive zip de .txt ou de .html. Rend le nombre de morceaux."""
    from assistant.skills import web

    lignes = []
    with zipfile.ZipFile(io.BytesIO(donnees)) as archive:
        for nom in archive.namelist():
            bas = nom.lower()
            if not bas.endswith((".txt", ".html", ".htm")):
                continue
            # L'historique des versions noie la recherche sous les "bpo-..."
            # sans rien expliquer : on ne garde que la documentation.
            if "whatsnew/" in bas or "changelog" in bas:
                continue
            brut = archive.read(nom).decode("utf-8", errors="replace")
            if bas.endswith((".html", ".htm")):
                titre = re.search(r"(?is)<title>(.*?)</title>", brut)
                titre = web._texte(titre.group(1)) if titre else Path(nom).stem
                texte = web.texte_de_page(brut)
            else:
                premiere = next((l for l in brut.splitlines() if l.strip()), Path(nom).stem)
                titre, texte = premiere.strip()[:200], brut
            for morceau in decouper(texte):
                lignes.append((source, titre, nom, morceau))
    with _connexion() as c:
        c.execute("DELETE FROM docs WHERE source = ?", (source,))
        c.executemany("INSERT INTO docs VALUES (?, ?, ?, ?)", lignes)
    return len(lignes)


# --- Telecharger ----------------------------------------------------------------

def _adresse(source: str, session) -> str:
    if source == "python":
        page = session.get(PYTHON_PAGE, timeout=DELAI, headers={"User-Agent": AGENT}).text
        lien = re.search(r'href="([^"]*docs-text\.zip)"', page)
        if not lien:
            raise RuntimeError("archive texte introuvable sur docs.python.org")
        return "https://docs.python.org/3/" + lien.group(1).lstrip("/")
    try:
        r = session.get(CPP_RELEASE, timeout=DELAI, headers={"User-Agent": AGENT})
        for a in r.json().get("assets", []):
            if re.fullmatch(r"html-book-\d+\.zip", a.get("name", "")):
                return a["browser_download_url"]
    except Exception:  # noqa: BLE001 - l'adresse de secours prend le relais
        pass
    return CPP_SECOURS


def installer(source: str, ask=None, session=None) -> str:
    import requests

    if source not in SOURCES:
        return f"Source inconnue : {source}. Disponibles : {', '.join(SOURCES)}."
    session = session or requests
    action = safety.Action(kind="reseau", summary=f"Telecharger et indexer : {SOURCES[source]}",
                           targets=[source], reversible=True, routine=True)
    try:
        if not safety.guard(action, ask=ask):
            return "Annule."
    except safety.Refused as exc:
        return str(exc)
    try:
        url = _adresse(source, session)
        r = session.get(url, timeout=DELAI * 5, headers={"User-Agent": AGENT})
        if r.status_code != 200:
            return f"Telechargement refuse ({r.status_code}) : {url}"
        nombre = indexer_archive(source, r.content)
    except (requests.RequestException, RuntimeError, zipfile.BadZipFile) as exc:
        return f"Installation impossible : {exc}"
    return (f"{SOURCES[source]} : {len(r.content) / 1e6:.1f} Mo telecharges, "
            f"{nombre} morceaux indexes. Recherche avec chercher_bibliotheque.")


# --- Chercher -------------------------------------------------------------------

def _requete_fts(texte: str) -> str:
    mots = re.findall(r"[\w:]+", texte)
    return " OR ".join(f'"{m}"' for m in mots[:12])


def chercher(requete: str, nombre: int = 6) -> str:
    if not BASE.exists():
        return ("La bibliotheque locale est vide. Installe une source avec "
                "installer_bibliotheque (python, cppreference).")
    fts = _requete_fts(requete or "")
    if not fts:
        return "Recherche vide."
    with _connexion() as c:
        lignes = c.execute(
            "SELECT source, titre, chemin, snippet(docs, 3, '[', ']', ' ... ', 60) "
            "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs, 0, 4.0, 0, 1.0) LIMIT ?",
            (fts, int(nombre))).fetchall()
    if not lignes:
        return f"Rien dans la bibliotheque locale pour « {requete} »."
    sortie = [f"Bibliotheque locale, « {requete} » :"]
    for source, titre, chemin, extrait in lignes:
        sortie += [f"- [{source}] {titre}  ({chemin})", f"  {extrait.strip()}"]
    sortie.append("Pour le texte complet d'un morceau : lire_bibliotheque avec son chemin.")
    return "\n".join(sortie)


def lire(chemin: str) -> str:
    if not BASE.exists():
        return "La bibliotheque locale est vide."
    with _connexion() as c:
        morceaux = c.execute("SELECT titre, texte FROM docs WHERE chemin = ?",
                             (chemin,)).fetchall()
    if not morceaux:
        return f"{chemin} n'est pas dans la bibliotheque."
    texte = "\n\n".join(m[1] for m in morceaux)
    return f"{morceaux[0][0]}\n\n{texte[:12000]}" + ("\n... (coupe)" if len(texte) > 12000 else "")


def etat() -> str:
    if not BASE.exists():
        return "Bibliotheque locale vide. Sources disponibles : " + ", ".join(
            f"{k} ({v})" for k, v in SOURCES.items())
    with _connexion() as c:
        comptes = dict(c.execute("SELECT source, count(*) FROM docs GROUP BY source").fetchall())
    lignes = ["Bibliotheque locale :"]
    for k, v in SOURCES.items():
        lignes.append(f"  {k:<13} {comptes.get(k, 0):>6} morceaux  {v}"
                      + ("" if comptes.get(k) else "  (non installee)"))
    return "\n".join(lignes)
