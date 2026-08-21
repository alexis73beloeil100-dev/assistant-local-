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
    cible: str          # chemin du raccourci, de l'exe, URI, ou AUMID
    source: str         # "menu demarrer", "microsoft store", "windows", "index"

    @property
    def est_store(self) -> bool:
        """Une application du Store se lance autrement qu'un fichier."""
        return self.source == "microsoft store"


def _from_apps_folder() -> list[App]:
    """Tout ce que Windows sait lancer, applications du Store comprises.

    Le menu Demarrer ne suffit pas : une application installee depuis le
    Microsoft Store n'a AUCUN raccourci .lnk. Xbox, YouTube Music, Netflix,
    Photos et le Terminal etaient donc invisibles pour l'assistant, qui
    repondait "cette application n'est pas installee" -- alors qu'elle
    l'etait.

    shell:AppsFolder est le dossier virtuel qui les contient toutes. Chaque
    entree y porte son nom affiche et son identifiant de modele utilisateur
    (AUMID), qui est la seule facon fiable de la lancer.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return []

    # COM appartient au thread qui l'initialise, et le catalogue est construit
    # dans un thread de fond.
    try:
        pythoncom.CoInitialize()
    except Exception:  # noqa: BLE001 - deja initialise
        pass

    try:
        shell = win32com.client.Dispatch("Shell.Application")
        elements = shell.Namespace("shell:AppsFolder").Items()
    except Exception:  # noqa: BLE001
        return []

    trouves = []
    for index in range(elements.Count):
        try:
            element = elements.Item(index)
            nom, aumid = str(element.Name), str(element.Path)
        except Exception:  # noqa: BLE001
            continue
        if not nom or not aumid:
            continue
        trouves.append(App(nom, aumid, "microsoft store"))
    return trouves


def canon(texte: str) -> str:
    """Forme comparable d'un nom d'application.

    L'apostrophe typographique et l'apostrophe droite doivent donner le meme
    resultat : "Observateur d'evenements" du menu Demarrer et
    "observateur d'evenements" de notre liste interne sont la meme chose, et
    les distinguer faisait demander "laquelle ?" pour un choix qui n'en est
    pas un.
    """
    texte = unicodedata.normalize("NFKD", texte)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    for signe in ("-", "'", "’", "_", ".", ",", "(", ")"):
        texte = texte.replace(signe, " ")
    return " ".join(texte.lower().split())


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
    """Toutes les applications lancables : Store, menu Demarrer, Windows.

    L'ordre des sources compte. Le Store vient EN PREMIER : quand une
    application existe sous les deux formes, l'entree du Store porte le nom
    exact que Windows affiche et se lance sans ambiguite, la ou un raccourci
    peut pointer vers un installeur ou un site web.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache

    applications = _from_apps_folder()
    connus = {canon(a.nom) for a in applications}

    for app in _from_start_menu():
        if canon(app.nom) not in connus:
            connus.add(canon(app.nom))
            applications.append(app)

    for nom, commande in BUILTINS.items():
        if canon(nom) not in connus:
            applications.append(App(nom, commande, "windows"))

    _cache = sorted(applications, key=lambda a: a.nom.lower())
    return _cache


def rafraichir() -> str:
    """Refait le catalogue. Une application installee depuis le lancement
    doit pouvoir etre trouvee sans redemarrer l'assistant."""
    avant = len(_cache or [])
    apres = len(catalogue(refresh=True))
    if not avant:
        return f"{apres} applications reconnues."
    difference = apres - avant
    if difference > 0:
        return f"{apres} applications reconnues ({difference} de plus)."
    if difference < 0:
        return f"{apres} applications reconnues ({-difference} de moins)."
    return f"{apres} applications reconnues, aucun changement."


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


# Ressemblance minimale pour une correspondance PUREMENT approximative,
# c'est-a-dire sans mot commun.
#
# Le seuil etait a 0,50, et il ouvrait n'importe quoi : "spotify" lancait
# TikFinity, "word" lancait Discord -- deux applications qui n'ont rien a voir,
# et dont aucune n'etait celle demandee. Ouvrir la mauvaise application est
# pire que repondre "pas trouve" : l'utilisateur ne comprend pas ce qui s'est
# passe, et doit refermer quelque chose qu'il n'a pas demande.
#
# A 0,72, "word"/"Discord" (0,46) et "spotify"/"TikFinity" (0,50) sont
# ecartes, tandis qu'une faute de frappe ou un accent manquant passe encore.
SEUIL_FLOU = 0.72


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
            # Aucun mot en commun : on n'accepte qu'une tres forte
            # ressemblance, sinon on lance autre chose.
            note = difflib.SequenceMatcher(None, demande, nom).ratio()
            if note < SEUIL_FLOU:
                continue
        scores.append((round(note, 3), app))

    scores.sort(key=lambda item: item[0], reverse=True)
    scores = _sans_doublons(scores)
    if scores and scores[0][0] >= 0.7:
        return scores

    for app in _from_index(requete):
        scores.append((0.6, app))
    scores.sort(key=lambda item: item[0], reverse=True)
    return _sans_doublons(scores)


def _sans_doublons(scores: list[tuple[float, App]]) -> list[tuple[float, App]]:
    """Une meme cible ne doit apparaitre qu'une fois.

    "gestionnaire des taches" et "gestionnaire de taches" ouvrent le meme
    taskmgr.exe : les garder toutes les deux faisait repondre "plusieurs
    applications correspondent, laquelle ?" pour un choix qui n'en est pas un.
    L'ambiguite venait de nos propres synonymes.
    """
    vus = set()
    garde = []
    for note, app in scores:
        # Deux cles : la cible, et le nom. Une meme application apparait
        # souvent sous les deux formes -- une entree du Store et un raccourci
        # du menu Demarrer pointant ailleurs, mais portant le meme nom.
        for cle in (("cible", canon(app.cible)), ("nom", canon(app.nom))):
            if cle in vus:
                break
        else:
            vus.add(("cible", canon(app.cible)))
            vus.add(("nom", canon(app.nom)))
            garde.append((note, app))
    return garde


def _lancer(app: App) -> None:
    """Ouvre reellement une application, selon sa nature.

    Une application du Store ne s'ouvre pas comme un fichier : os.startfile
    sur un AUMID echoue, ou pire, Windows le prend pour un terme de recherche
    et ouvre le navigateur. C'est ce qui faisait apparaitre Microsoft Edge
    quand on demandait l'application Xbox.
    """
    import subprocess

    if app.est_store:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.cible}"])
        return
    os.startfile(app.cible)


def open_app(nom: str, refresh_si_absent: bool = True) -> str:
    """Ouvre une application par son nom."""
    resultats = find(nom)

    # Rien trouve ? L'application vient peut-etre d'etre installee. On refait
    # le catalogue une fois avant de declarer forfait : repondre "elle n'est
    # pas installee" alors qu'elle l'est est la pire des reponses.
    if not resultats and refresh_si_absent:
        catalogue(refresh=True)
        resultats = find(nom)

    if not resultats:
        return (f"Aucune application ne correspond a \"{nom}\", meme apres "
                "avoir refait la liste. Verifie l'orthographe, ou demande "
                "\"liste mes applications\".")

    meilleur_score, meilleur = resultats[0]
    # Un nom exact n'est jamais ambigu. Demander "laquelle ?" quand
    # l'utilisateur a donne le nom precis d'une application est une question
    # de trop, meme si une autre lui ressemble.
    if meilleur_score < 1.0 and len(resultats) > 1 \
            and resultats[1][0] > meilleur_score - 0.08:
        noms = ", ".join(a.nom for _s, a in resultats[:4])
        return f"Plusieurs applications correspondent : {noms}. Laquelle ?"

    try:
        _lancer(meilleur)
    except OSError as exc:
        return f"Ouverture impossible de {meilleur.nom} : {exc}"
    return f"{meilleur.nom} ouvert."


# Applications dont le nom courant ne correspond a aucun processus unique.
# Les fermer une par une obligeait l'utilisateur a deviner les noms exacts, et
# a repeter la demande trois fois -- ce que l'assistant faisait reellement
# pour Steam avant cette correction.
FAMILLES = {
    "steam": ("steam.exe", "steamwebhelper.exe", "steamservice.exe"),
    "discord": ("discord.exe",),
    "epic": ("epicgameslauncher.exe", "epicwebhelper.exe"),
    "chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "firefox": ("firefox.exe",),
    "ubisoft": ("upc.exe", "ubisoftconnect.exe"),
    "ea": ("eadesktop.exe", "eabackgroundservice.exe"),
    "riot": ("riotclientservices.exe", "leagueclient.exe"),
    "teams": ("ms-teams.exe", "teams.exe"),
    "spotify": ("spotify.exe",),
    "obs": ("obs64.exe",),
}


def close_app(nom: str, ask=None) -> str:
    """Ferme une application, TOUS ses processus compris.

    Une application n'est presque jamais un seul processus. Steam en lance
    trois : le launcher, l'assistant web et un service. Fermer le premier
    laissait les deux autres tourner, et l'utilisateur devait redemander deux
    fois -- sans connaitre les noms exacts.

    Ce qui demande les droits administrateur est signale comme tel, pas
    presente comme un echec inexplicable.
    """
    from assistant.skills import fixes

    demande = canon(nom)
    cibles = None
    for famille, processus in FAMILLES.items():
        if famille in demande:
            cibles = processus
            break

    if cibles is None:
        return str(fixes.arreter_processus(nom, ask=ask))

    fermes, absents, refuses = [], [], []
    for processus in cibles:
        resultat = fixes.arreter_processus(processus, ask=ask)
        message = resultat.message
        if resultat.ok:
            fermes.append(processus)
        elif "aucun processus" in message.lower():
            absents.append(processus)
        else:
            refuses.append((processus, message))

    lignes = []
    if fermes:
        lignes.append(f"{nom} ferme : {', '.join(fermes)}.")
    if absents:
        lignes.append(f"Deja arrete : {', '.join(absents)}.")
    for processus, message in refuses:
        if "administrateur" in message.lower() or "droits" in message.lower():
            lignes.append(
                f"{processus} est un service : il demande les droits "
                "administrateur. Il ne gene rien en tournant, et il se "
                "relancera de toute facon au prochain lancement.")
        else:
            lignes.append(f"{processus} : {message[:100]}")

    if not fermes and not absents:
        return f"{nom} ne tournait pas."
    return "\n".join(lignes)


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
