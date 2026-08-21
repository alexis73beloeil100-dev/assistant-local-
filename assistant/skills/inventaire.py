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
