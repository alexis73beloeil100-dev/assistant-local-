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


def lien_du_rapport(description: str, technique: str = "",
                    joindre: bool = True) -> str:
    """Construit l'adresse de l'issue GitHub, formulaire pre-rempli."""
    corps = [description.strip() or "(decris ici ce qui s'est passe)", ""]
    if joindre and technique.strip():
        corps += ["---", "```", technique.strip(), "```"]

    titre = (description.strip().splitlines() or ["Probleme rencontre"])[0]
    parametres = urllib.parse.urlencode({
        "title": titre[:80],
        "body": "\n".join(corps),
        "labels": "retour utilisateur",
    })
    return f"https://github.com/{depot()}/issues/new?{parametres}"


def ouvrir(description: str, joindre: bool = True) -> str:
    """Ouvre le formulaire pre-rempli dans le navigateur.

    On OUVRE, on n'envoie pas. C'est la personne qui appuie sur le bouton de
    publication, apres avoir lu ce qui part -- et le depot etant public, ce
    qui part y reste.
    """
    lien = lien_du_rapport(description, contexte(), joindre)
    if len(lien) > 8000:
        # Au-dela, les navigateurs tronquent l'adresse en silence et le
        # rapport arrive ampute sans que personne le voie.
        lien = lien_du_rapport(description, "", False)
    try:
        subprocess.Popen(["cmd", "/c", "start", "", lien],
                         creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return f"Le navigateur n'a pas pu s'ouvrir : {exc}"
    return ("Formulaire ouvert dans le navigateur. Relis ce qui part, "
            "puis publie : rien n'est envoye tant que tu n'as pas clique.")
