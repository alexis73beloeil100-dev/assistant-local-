"""Inventaire logiciel : ce qui est installe sur cette machine.

Complete le releve materiel (hardware.py) et l'index des fichiers : logiciels
installes, services, taches planifiees, pilotes tiers, navigateurs.

Comme tout le reste, **rien n'est ecrit sur le disque**. L'inventaire est
relu a chaque demarrage, en tache de fond, et range dans
assistant.connaissance, qui vit en memoire vive.

Le releve passe par un seul script PowerShell, pour la meme raison que le
releve materiel : quinze interrogations separees feraient attendre le
demarrage de plusieurs dizaines de secondes.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from assistant import connaissance

CREATE_NO_WINDOW = 0x08000000

# L'inventaire est plus lourd que le releve materiel : les taches planifiees et
# les pilotes se comptent en centaines.
TIMEOUT = 180

_donnees: dict | None = None
_erreur = ""
_verrou = threading.Lock()


def _script() -> Path:
    """Localise inventaire.ps1, en sources comme dans l'executable packagee."""
    voisin = Path(__file__).resolve().parent / "inventaire.ps1"
    if voisin.is_file():
        return voisin
    base = getattr(sys, "_MEIPASS", None)
    if base:
        embarque = Path(base) / "assistant" / "skills" / "inventaire.ps1"
        if embarque.is_file():
            return embarque
    return voisin


SCRIPT = _script()


def collect(force: bool = False) -> dict:
    """Execute l'inventaire et range ce qu'il trouve dans la connaissance."""
    global _donnees, _erreur

    with _verrou:
        if _donnees is not None and not force:
            return _donnees

        if not SCRIPT.exists():
            _erreur = f"Script d'inventaire introuvable : {SCRIPT}"
            return {}

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            destination = fh.name

        try:
            resultat = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(SCRIPT), "-Destination", destination],
                capture_output=True, text=True, timeout=TIMEOUT,
                encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            brut = Path(destination).read_text(encoding="utf-8").strip()
        except (subprocess.SubprocessError, OSError) as exc:
            _erreur = f"Inventaire impossible : {type(exc).__name__}: {exc}"
            return {}
        finally:
            try:
                Path(destination).unlink()
            except OSError:
                pass

        if not brut:
            _erreur = f"Inventaire vide. {(resultat.stderr or '')[:200]}"
            return {}

        try:
            _donnees = json.loads(brut)
        except json.JSONDecodeError as exc:
            _erreur = f"Inventaire illisible : {exc}"
            return {}

        _donnees["releve_a"] = time.strftime("%Y-%m-%d %H:%M")
        _ranger(_donnees)
        return _donnees


def _ranger(donnees: dict) -> None:
    """Verse l'inventaire dans la connaissance, sujet par sujet."""
    for logiciel in donnees.get("logiciels") or []:
        nom = (logiciel.get("nom") or "").strip()
        if not nom:
            continue
        details = [logiciel.get("version"), logiciel.get("editeur")]
        if logiciel.get("taille_mo"):
            details.append(f"{logiciel['taille_mo']} Mo")
        if logiciel.get("dossier"):
            details.append(str(logiciel["dossier"]))
        connaissance.apprendre(
            "logiciels", nom,
            "  ".join(str(d) for d in details if d),
            source="registre des programmes installes")

    for service in donnees.get("services") or []:
        nom = (service.get("nom") or "").strip()
        if not nom:
            continue
        connaissance.apprendre(
            "services", nom,
            f"{service.get('libelle', '')} — {service.get('etat', '?')}, "
            f"demarrage {service.get('demarre', '?')}",
            source="services Windows")

    for tache in donnees.get("taches") or []:
        nom = (tache.get("nom") or "").strip()
        if not nom:
            continue
        connaissance.apprendre(
            "taches planifiees", nom,
            f"{tache.get('chemin', '')} — {tache.get('etat', '?')}"
            + (f", par {tache['auteur']}" if tache.get("auteur") else ""),
            source="planificateur de taches")

    for pilote in donnees.get("pilotes") or []:
        appareil = (pilote.get("appareil") or "").strip()
        if not appareil:
            continue
        connaissance.apprendre(
            "pilotes", appareil,
            f"{pilote.get('editeur', '?')} version {pilote.get('version', '?')}"
            + (f" du {pilote['date']}" if pilote.get("date") else ""),
            source="pilotes signes")

    for navigateur in donnees.get("navigateurs") or []:
        nom = (navigateur.get("nom") or navigateur.get("cle") or "").strip()
        if nom:
            connaissance.apprendre("navigateurs", nom, "installe",
                                   source="clients Internet declares")


def collect_in_background(on_done=None) -> threading.Thread:
    def travail():
        donnees = collect()
        if on_done:
            on_done(donnees)

    fil = threading.Thread(target=travail, name="inventaire", daemon=True)
    fil.start()
    return fil


def pret() -> bool:
    return _donnees is not None


# --- Desinstallation ---------------------------------------------------------
#
# Ce qu'on refuse de desinstaller par cette voie, et pourquoi.
#
# Ce ne sont pas des logiciels au sens ou l'utilisateur l'entend : ce sont des
# briques dont d'autres programmes dependent, ou des pilotes. Retirer un
# "Microsoft Visual C++ Redistributable" ne libere presque rien et casse en
# silence les applications qui s'appuient dessus -- le defaut n'apparait qu'au
# lancement suivant de l'une d'elles, sans rapport visible avec ce qu'on vient
# de faire.
#
# La liste ne pretend pas etre complete. Elle couvre ce qu'un nettoyage
# enthousiaste attrape en premier.
JAMAIS_DESINSTALLER = (
    "assistantlocal",
    "microsoft visual c++",
    "microsoft .net",
    ".net framework",
    ".net runtime",
    "microsoft edge webview",
    "nvidia graphics driver",
    "nvidia display",
    "amd software",
    "amd chipset",
    "intel chipset",
    "realtek",
    "microsoft defender",
    "windows update",
)


def _logiciels() -> list[dict]:
    return (collect() or {}).get("logiciels") or []


def chercher_logiciel(nom: str) -> list[dict]:
    """Les logiciels installes dont le nom contient `nom`."""
    demande = str(nom).strip().lower()
    if not demande:
        return []
    return [l for l in _logiciels()
            if demande in str(l.get("nom") or "").lower()]


def desinstaller(nom: str, ask=None) -> str:
    """Lance la desinstallation d'un logiciel installe, par son nom.

    On n'invente jamais le chemin d'un desinstalleur : on prend la commande
    que Windows lui-meme a enregistree (UninstallString). Deviner un chemin
    casse a chaque mise a jour du logiciel, et se tromper de cible sur une
    desinstallation ne se rattrape pas.

    Rien ne se fait en silence. Le desinstalleur ouvre sa propre fenetre, et
    c'est l'utilisateur qui la termine. Ajouter un /quiet serait techniquement
    possible et serait une faute : une desinstallation silencieuse declenchee
    par une phrase mal comprise ne se defait pas.

    Irreversible, donc le garde-fou pose toujours la question -- meme si
    quelqu'un marquait un jour cette action comme geste courant.
    """
    from assistant import safety

    trouves = chercher_logiciel(nom)
    if not trouves:
        if not _logiciels():
            return (_erreur or "L'inventaire logiciel n'est pas encore pret. "
                    "Redemande dans quelques secondes.")
        return (f"Aucun logiciel installe ne correspond a \"{nom}\". "
                "Demande-moi la liste si tu veux verifier le nom exact.")

    if len(trouves) > 1:
        noms = "\n".join(f"  - {l.get('nom')}" for l in trouves[:12])
        reste = "\n  ..." if len(trouves) > 12 else ""
        return (f"{len(trouves)} logiciels correspondent a \"{nom}\" :\n"
                f"{noms}{reste}\nPrecise lequel.")

    logiciel = trouves[0]
    vrai_nom = str(logiciel.get("nom") or "").strip()
    minuscule = vrai_nom.lower()

    if any(marque in minuscule for marque in JAMAIS_DESINSTALLER):
        return (f"\"{vrai_nom}\" n'est pas une application ordinaire : c'est "
                "une brique dont d'autres programmes dependent, ou un "
                "pilote. La retirer casse en silence ce qui s'appuie dessus, "
                "et le defaut n'apparait qu'au lancement suivant de l'un "
                "d'eux. Je ne le fais pas par cette voie.")

    commande = str(logiciel.get("desinstalle") or "").strip()
    if not commande:
        return (f"\"{vrai_nom}\" ne declare aucune commande de "
                "desinstallation. C'est le cas des applications du Microsoft "
                "Store et de certains jeux, qui se retirent par leur magasin "
                "ou par leur launcher.")

    details = [str(logiciel.get(c)) for c in ("version", "editeur")
               if logiciel.get(c)]
    if logiciel.get("taille_mo"):
        details.append(f"{logiciel['taille_mo']} Mo liberes")

    action = safety.Action(
        kind="logiciel",
        summary=f"Desinstaller {vrai_nom}",
        targets=[str(logiciel.get("dossier") or vrai_nom)],
        reversible=False,
        details=("  ".join(details)
                 + f"\n    Commande enregistree par Windows : {commande[:120]}"),
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    try:
        # La chaine est une ligne de commande complete, redigee par l'editeur :
        # chemin entre guillemets, puis arguments. On la passe telle quelle au
        # shell, qui sait la decouper -- la redecouper nous-memes rate les cas
        # a guillemets imbriques, et un desinstalleur lance sur un chemin mal
        # coupe est exactement ce qu'on ne veut pas.
        subprocess.Popen(commande, shell=True)
    except OSError as exc:
        return f"Le desinstalleur n'a pas pu demarrer : {exc}"

    return (f"Desinstallation de {vrai_nom} lancee. Sa fenetre va s'ouvrir : "
            "c'est toi qui la termines, rien ne se fait en silence.\n"
            "Quand ce sera fini, demande-moi de refaire l'inventaire pour que "
            "je cesse de le croire installe.")


def resume() -> str:
    """Ce que l'inventaire a trouve, en clair."""
    donnees = collect()
    if not donnees:
        return _erreur or "Inventaire indisponible."

    lignes = ["INVENTAIRE LOGICIEL", "",
              f"  Releve le {donnees.get('releve_a', '?')}", ""]
    for cle, libelle in (("logiciels", "logiciels installes"),
                         ("services", "services Windows"),
                         ("taches", "taches planifiees (hors Microsoft)"),
                         ("pilotes", "pilotes tiers"),
                         ("navigateurs", "navigateurs")):
        lignes.append(f"  {len(donnees.get(cle) or []):>5}  {libelle}")

    actifs = [s for s in donnees.get("services") or []
              if str(s.get("etat", "")).lower() in ("running", "en cours "
                                                    "d'execution")]
    lignes.append("")
    lignes.append(f"  {len(actifs)} service(s) en cours d'execution")
    lignes.append("")
    lignes.append("Rien n'est ecrit sur le disque : cet inventaire vit en")
    lignes.append("memoire et se refait a chaque demarrage.")
    return "\n".join(lignes)
