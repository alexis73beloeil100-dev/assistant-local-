"""Signaler un probleme, depuis l'application, sans intermediaire.

Un defaut qui n'est pas remonte n'est pas corrige, et la distance entre "ca ne
marche pas" et un rapport utilisable decourage a peu pres tout le monde :
retrouver un numero de version, dire quel Windows, expliquer ce qu'on faisait.
Ce module fait ce travail a la place de l'utilisateur.

COMMENT LE RAPPORT ARRIVE, et pourquoi ainsi.

Il passe par une issue GitHub, ouverte dans le navigateur avec le formulaire
DEJA REMPLI. L'utilisateur lit, corrige, envoie -- ou renonce. Trois raisons :

  1. Aucun identifiant ne transite par l'application. Envoyer un courriel
     demanderait un mot de passe de messagerie, ou une cle d'API pour un
     service tiers. Une application qui detient une cle capable d'ecrire chez
     son auteur est une application qu'on ne devrait pas installer.
  2. Rien ne part sans que la personne l'ait vu. Le formulaire s'ouvre, elle
     lit exactement ce qui sera publie. Un envoi silencieux qui emporterait
     des chemins de fichiers et un nom de machine serait une fuite, pas un
     support.
  3. L'auteur recoit une notification GitHub, l'echange reste attache au
     probleme, et la correction s'y rattache.

CE QUE LE RAPPORT CONTIENT : la version, Windows, le materiel en une ligne, et
les dernieres erreurs du journal. Rien d'autre -- pas de chemins personnels,
pas de noms de fichiers, pas de contenu lu. Le depot est public : ce qui part
la-bas y reste.
"""
from __future__ import annotations

import platform
import subprocess
import urllib.parse
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

# Le depot ou vont les rapports. Lu depuis le distant git plutot qu'ecrit en
# dur : un depot renomme ou reprisé n'enverrait pas les rapports dans le vide.
DEPOT_PAR_DEFAUT = "alexis73beloeil100-dev/assistant-local-"

# Nombre de lignes de journal jointes. Assez pour situer une erreur, trop peu
# pour emporter une session entiere.
LIGNES_JOURNAL = 15


def depot() -> str:
    """Le depot GitHub de cette copie, ou celui par defaut."""
    try:
        racine = Path(__file__).resolve().parent.parent
        sortie = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=str(racine),
            capture_output=True, text=True, timeout=10,
            creationflags=CREATE_NO_WINDOW)
        url = (sortie.stdout or "").strip()
        if "github.com" in url:
            chemin = url.split("github.com")[-1].lstrip(":/")
            return chemin.removesuffix(".git")
    except (subprocess.SubprocessError, OSError):
        pass
    return DEPOT_PAR_DEFAUT


def _dernieres_erreurs() -> str:
    """Les dernieres lignes du journal d'erreurs, s'il y en a un."""
    try:
        from assistant import config

        journal = config.DATA_DIR / "logs" / "erreurs.log"
        if not journal.is_file():
            journal = Path(__file__).resolve().parent.parent / "erreurs.log"
        if not journal.is_file():
            return ""
        lignes = journal.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
        return "\n".join(lignes[-LIGNES_JOURNAL:])
    except OSError:
        return ""


def contexte() -> str:
    """Ce qui sera joint au rapport, en clair, pour que l'utilisateur le lise.

    Fabrique ici et montre AVANT l'envoi. Un rapport technique assemble dans
    le dos de la personne qui le signe est exactement ce qu'on ne veut pas.
    """
    from assistant import __version__

    lignes = [f"Version : {__version__}",
              f"Windows : {platform.platform()}",
              f"Python  : {platform.python_version()}"]

    try:
        from assistant.skills import hardware

        donnees = hardware.collect() or {}
        machine = donnees.get("machine") or {}
        cpu = (donnees.get("cpu") or {}).get("name", "")
        gpu = ((donnees.get("gpu") or [{}])[0] or {}).get("name", "")
        materiel = " / ".join(x for x in (machine.get("board"), cpu, gpu) if x)
        if materiel:
            lignes.append(f"Materiel : {materiel}")
    except Exception:  # noqa: BLE001 - un rapport sans materiel vaut mieux que pas de rapport
        pass

    erreurs = _dernieres_erreurs()
    if erreurs:
        lignes.append("")
        lignes.append("Dernieres erreurs :")
        lignes.append(erreurs)
    return "\n".join(lignes)


# Les endroits ou ca casse, nommes par ce que la personne a sous les yeux.
#
# Une liste libre donne "ca marche pas" ; une liste de modules techniques
# demande de savoir lequel est en cause, ce que justement on ne sait pas quand
# on rencontre un defaut. On nomme donc le GESTE, pas le module.
CATEGORIES = [
    ("La conversation", "il repond a cote, invente, ou ne repond pas"),
    ("La voix", "le micro n'ecrit rien, ou la lecture a voix haute"),
    ("Les fichiers joints", "une image ou un document mal lu"),
    ("L'eclairage RGB", "les LED ne suivent pas, ou reviennent en arriere"),
    ("Reparer Windows", "sfc, DISM, ou l'examen antivirus"),
    ("Le telephone", "presse-papier partage, macros, appairage"),
    ("Les panneaux", "un affichage faux, vide ou illisible"),
    ("L'installation", "installer, mettre a jour, desinstaller"),
    ("Autre chose", ""),
]


def capture_pour_le_rapport() -> tuple[bool, str]:
    """Photographie l'ecran et la depose sur le Bureau.

    Elle n'est PAS envoyee automatiquement, et ce n'est pas un oubli : GitHub
    n'accepte pas d'image par adresse, seulement par depot dans le
    formulaire. On prepare donc le fichier et on dit ou il est -- la personne
    le glisse dans l'issue, ce qui lui laisse au passage l'occasion de
    regarder ce qu'elle publie.

    Une capture d'ecran montre tout ce qui etait affiche : une conversation,
    un nom de dossier, une fenetre restee ouverte a cote. Sur un depot
    public, cela ne se rattrape pas.
    """
    from assistant.skills import vision

    ok, temporaire = vision.capture(0)
    if not ok:
        return False, temporaire

    try:
        from creer_raccourci import desktop  # type: ignore

        dossier = desktop()
    except Exception:  # noqa: BLE001
        dossier = Path.home() / "Desktop"

    import shutil
    import time

    cible = dossier / f"probleme_{time.strftime('%Y-%m-%d_%Hh%M%S')}.png"
    try:
        shutil.move(temporaire, cible)
    except OSError as exc:
        return False, f"Capture impossible a deposer : {exc}"
    return True, str(cible)


def lien_du_rapport(description: str, technique: str = "",
                    joindre: bool = True, categorie: str = "",
                    capture: str = "") -> str:
    """Construit l'adresse de l'issue GitHub, formulaire pre-rempli."""
    corps = []
    if categorie:
        corps.append(f"**Ou :** {categorie}")
        corps.append("")
    corps += [description.strip() or "(decris ici ce qui s'est passe)", ""]
    if capture:
        corps += ["**Capture d'ecran :** glisse ici le fichier",
                  f"`{capture}`", ""]
    if joindre and technique.strip():
        corps += ["---", "```", technique.strip(), "```"]

    premiere = (description.strip().splitlines() or ["Probleme rencontre"])[0]
    titre = f"[{categorie}] {premiere}" if categorie else premiere
    parametres = urllib.parse.urlencode({
        "title": titre[:80],
        "body": "\n".join(corps),
        "labels": "retour utilisateur",
    })
    return f"https://github.com/{depot()}/issues/new?{parametres}"


def ouvrir(description: str, joindre: bool = True, categorie: str = "",
           capture: str = "") -> str:
    """Ouvre le formulaire pre-rempli dans le navigateur.

    On OUVRE, on n'envoie pas. C'est la personne qui appuie sur le bouton de
    publication, apres avoir lu ce qui part -- et le depot etant public, ce
    qui part y reste.
    """
    lien = lien_du_rapport(description, contexte(), joindre, categorie,
                           capture)
    if len(lien) > 8000:
        # Au-dela, les navigateurs tronquent l'adresse en silence et le
        # rapport arrive ampute sans que personne le voie.
        lien = lien_du_rapport(description, "", False, categorie, capture)
    try:
        subprocess.Popen(["cmd", "/c", "start", "", lien],
                         creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return f"Le navigateur n'a pas pu s'ouvrir : {exc}"
    fin = ("Formulaire ouvert dans le navigateur. Relis ce qui part, "
           "puis publie : rien n'est envoye tant que tu n'as pas clique.")
    if capture:
        fin += ("\nLa capture est sur ton Bureau : glisse-la dans le "
                f"formulaire.\n{capture}")
    return fin
