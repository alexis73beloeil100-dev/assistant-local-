"""Ouvrir et fermer n'importe quelle application.

La source principale est le menu Demarrer, pas l'index des executables : un
raccourci porte le nom que l'utilisateur connait ("Discord", "Gestionnaire
des taches") la ou l'executable s'appelle souvent autrement (Update.exe,
Taskmgr.exe). Chercher par nom d'exe donnerait des resultats incomprehensibles.

L'index des fichiers sert de filet quand le raccourci n'existe pas.
"""
from __future__ import annotations

import difflib
import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path

START_MENU_DIRS = [
    Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
]

# Outils Windows courants qu'on demande par leur nom parle, et la commande
# qui les ouvre reellement.
BUILTINS = {
    "gestionnaire des taches": "taskmgr.exe",
    "gestionnaire de taches": "taskmgr.exe",
    "panneau de configuration": "control.exe",
    "parametres": "ms-settings:",
    "reglages": "ms-settings:",
    "explorateur": "explorer.exe",
    "invite de commandes": "cmd.exe",
    "powershell": "powershell.exe",
    "bloc-notes": "notepad.exe",
    "calculatrice": "calc.exe",
    "paint": "mspaint.exe",
    "gestionnaire de peripheriques": "devmgmt.msc",
    "observateur d'evenements": "eventvwr.msc",
    "services": "services.msc",
    "moniteur de ressources": "resmon.exe",
    "informations systeme": "msinfo32.exe",
    "nettoyage de disque": "cleanmgr.exe",
    "parametres son": "ms-settings:sound",
    "parametres d'affichage": "ms-settings:display",
    "applications installees": "ms-settings:appsfeatures",
}

_cache: list["App"] | None = None


@dataclass
class App:
    nom: str
    cible: str          # chemin du raccourci, de l'exe, ou URI
    source: str         # "menu demarrer", "windows", "index"


def canon(texte: str) -> str:
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    return " ".join(texte.lower().replace("-", " ").split())


def _from_start_menu() -> list[App]:
    trouves = []
    vus = set()
    for racine in START_MENU_DIRS:
        if not racine.is_dir():
            continue
        for chemin in racine.rglob("*.lnk"):
            nom = chemin.stem
            cle = canon(nom)
            # Les desinstallateurs portent des noms proches des applications
            # et seraient lances par erreur.
            if not cle or cle in vus or any(
                mot in cle for mot in ("desinstall", "uninstall", "readme",
                                       "lisez-moi", "documentation",
                                       "site web", "website")
            ):
                continue
            vus.add(cle)
            trouves.append(App(nom, str(chemin), "menu demarrer"))
    return trouves


def catalogue(refresh: bool = False) -> list[App]:
    """Toutes les applications lancables, du menu Demarrer et de Windows."""
    global _cache
    if _cache is not None and not refresh:
        return _cache

    applications = _from_start_menu()
    connus = {canon(a.nom) for a in applications}
    for nom, commande in BUILTINS.items():
        if canon(nom) not in connus:
            applications.append(App(nom, commande, "windows"))

    _cache = sorted(applications, key=lambda a: a.nom.lower())
    return _cache


def _from_index(requete: str, limite: int = 5) -> list[App]:
    """Filet de secours : cherche un executable dans l'index des fichiers."""
    from assistant.index import db

    if not db.is_ready():
        return []
    try:
        with db.connect() as conn:
            lignes = db.search(conn, requete, limit=40, ext="exe")
    except Exception:  # noqa: BLE001
        return []

    trouves = []
    for ligne in lignes[:limite]:
        chemin = ligne["path"]
        nom = Path(chemin).stem
        if any(mot in canon(nom) for mot in ("unins", "setup", "install",
                                             "update", "crash", "report")):
            continue
        trouves.append(App(nom, chemin, "index"))
    return trouves


def find(requete: str) -> list[tuple[float, App]]:
    """Classe les applications par ressemblance avec la demande."""
    demande = canon(requete)
    if not demande:
        return []

    scores = []
    for app in catalogue():
        nom = canon(app.nom)
        if nom == demande:
            note = 1.0
        elif demande in nom:
            note = 0.80 + 0.15 * (len(demande) / max(len(nom), 1))
        elif all(mot in nom for mot in demande.split()):
            note = 0.75
        else:
            note = difflib.SequenceMatcher(None, demande, nom).ratio()
        if note >= 0.5:
            scores.append((round(note, 3), app))

    scores.sort(key=lambda item: item[0], reverse=True)
    if scores and scores[0][0] >= 0.7:
        return scores

    for app in _from_index(requete):
        scores.append((0.6, app))
    scores.sort(key=lambda item: item[0], reverse=True)
    return scores


def open_app(nom: str) -> str:
    """Ouvre une application par son nom."""
    resultats = find(nom)
    if not resultats:
        return (f"Aucune application ne correspond a \"{nom}\". "
                "Demande \"liste mes applications\" pour voir ce qui est "
                "reconnu.")

    meilleur_score, meilleur = resultats[0]
    if len(resultats) > 1 and resultats[1][0] > meilleur_score - 0.08:
        noms = ", ".join(a.nom for _s, a in resultats[:4])
        return f"Plusieurs applications correspondent : {noms}. Laquelle ?"

    try:
        os.startfile(meilleur.cible)
    except OSError as exc:
        return f"Ouverture impossible de {meilleur.nom} : {exc}"
    return f"{meilleur.nom} ouvert."


def close_app(nom: str, ask=None) -> str:
    """Ferme une application. Passe par le meme garde-fou que les processus."""
    from assistant.skills import fixes

    return str(fixes.arreter_processus(nom, ask=ask))


def liste(limite: int = 60) -> str:
    applications = catalogue()
    if not applications:
        return "Aucune application detectee dans le menu Demarrer."

    par_source: dict[str, list[App]] = {}
    for app in applications:
        par_source.setdefault(app.source, []).append(app)

    lignes = [f"{len(applications)} applications reconnues", ""]
    for source, groupe in par_source.items():
        lignes.append(f"  {source.upper()}  ({len(groupe)})")
        for app in groupe[:limite]:
            lignes.append(f"     {app.nom}")
        if len(groupe) > limite:
            lignes.append(f"     ... et {len(groupe) - limite} autres")
        lignes.append("")
    lignes.append("Dis \"ouvre <nom>\" ou \"ferme <nom>\".")
    return "\n".join(lignes)
