"""Correctifs : ce que l'assistant peut reparer, pas seulement constater.

Trois regles, sans exception :

  1. Chaque correctif passe par assistant.safety.guard() -- decrit avant,
     journalise apres, refuse sur les chemins proteges.
  2. Chaque correctif est reversible, et la maniere de revenir en arriere est
     enregistree AVANT d'agir. Desactiver un programme au demarrage sans
     conserver sa commande, c'est le perdre.
  3. Aucun correctif ne s'invente une cible. On agit sur ce que l'utilisateur
     a designe, jamais sur ce que le modele a devine.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from assistant import safety, settings
from assistant.util import human_size

CREATE_NO_WINDOW = 0x08000000

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Processus qu'on ne tue jamais : les arreter fait tomber la session Windows.
NEVER_KILL = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe",
    "wininit.exe", "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe",
    "explorer.exe", "dwm.exe", "fontdrvhost.exe", "audiodg.exe",
    "assistantlocal.exe",
}

# Services dont l'arret casse la machine : on refuse de les toucher.
CRITICAL_SERVICES = {
    "rpcss", "dcomlaunch", "lsm", "plugplay", "power", "profsvc",
    "samss", "schedule", "winlogon", "eventlog",
}


@dataclass
class Result:
    ok: bool
    message: str

    def __str__(self) -> str:
        return self.message


def _run(args: list[str], timeout: int = 60) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return completed.returncode == 0, (
        (completed.stdout or "") + (completed.stderr or "")
    ).strip()


# --- Programmes au demarrage ------------------------------------------------

def _startup_entries() -> dict[str, str]:
    import winreg

    entries = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                entries[name] = str(value)
    except OSError:
        pass
    return entries


def desactiver_demarrage(nom: str, ask=None) -> Result:
    """Empeche un programme de se lancer avec Windows.

    La commande est conservee dans les reglages avant suppression : sans
    elle, reactiver le programme serait impossible autrement qu'en le
    reinstallant.
    """
    import winreg

    entries = _startup_entries()
    cible = next((k for k in entries if k.lower() == nom.lower()), None)
    if cible is None:
        proches = [k for k in entries if nom.lower() in k.lower()]
        if len(proches) == 1:
            cible = proches[0]
        elif proches:
            return Result(False, "Plusieurs correspondances : "
                                 + ", ".join(proches) + ". Precise laquelle.")
        else:
            return Result(False, f"\"{nom}\" ne figure pas dans les programmes "
                                 "de demarrage de ta session.")

    commande = entries[cible]
    action = safety.Action(
        kind="registre",
        summary=f"Empecher {cible} de se lancer au demarrage de Windows",
        targets=[f"HKCU\\{RUN_KEY}\\{cible}"],
        reversible=True,
        details=f"Commande conservee pour pouvoir la remettre : {commande[:90]}",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    # Sauvegarde AVANT suppression, sinon la reactivation est impossible.
    sauvegardes = dict(settings.get("startup_backup", {}))
    sauvegardes[cible] = commande
    settings.set("startup_backup", sauvegardes)

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, cible)
    except OSError as exc:
        return Result(False, f"Echec : {exc}")

    return Result(True, f"{cible} ne se lancera plus au demarrage. "
                        f"Reversible : \"reactiver {cible}\".")


def reactiver_demarrage(nom: str, ask=None) -> Result:
    """Remet un programme desactive, a partir de la sauvegarde."""
    import winreg

    sauvegardes = dict(settings.get("startup_backup", {}))
    cible = next((k for k in sauvegardes if k.lower() == nom.lower()), None)
    if cible is None:
        return Result(False, f"Aucune sauvegarde pour \"{nom}\". "
                             f"Connus : {', '.join(sauvegardes) or 'aucun'}.")

    action = safety.Action(
        kind="registre",
        summary=f"Remettre {cible} au demarrage de Windows",
        targets=[f"HKCU\\{RUN_KEY}\\{cible}"],
        reversible=True,
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, cible, 0, winreg.REG_SZ, sauvegardes[cible])
    except OSError as exc:
        return Result(False, f"Echec : {exc}")

    del sauvegardes[cible]
    settings.set("startup_backup", sauvegardes)
    return Result(True, f"{cible} se relancera au demarrage.")


def desactivations_brutes() -> dict:
    """Programmes desactives, sous forme exploitable par l'interface.

    desactivations() rend du texte pour le modele ; le menu d'optimisation a
    besoin des donnees elles-memes pour construire ses cases a cocher.
    """
    return dict(settings.get("startup_backup", {}))


def desactivations() -> str:
    """Ce qui a ete desactive et reste reactivable."""
    sauvegardes = settings.get("startup_backup", {})
    if not sauvegardes:
        return "Aucun programme de demarrage desactive."
    lignes = ["Programmes desactives, reactivables a tout moment :"]
    for nom, commande in sauvegardes.items():
        lignes.append(f"  {nom}")
        lignes.append(f"      {commande[:100]}")
    return "\n".join(lignes)


# --- Processus --------------------------------------------------------------

def arreter_processus(cible: str, ask=None) -> Result:
    """Arrete un processus qui monopolise la machine.

    Refuse les processus systeme : arreter lsass ou csrss fait tomber la
    session immediatement, ce n'est jamais ce que l'utilisateur veut.
    """
    import psutil

    candidats = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            nom = proc.info.get("name") or ""
            if cible.isdigit() and proc.info.get("pid") == int(cible):
                candidats = [proc]
                break
            if cible.lower() in nom.lower():
                candidats.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not candidats:
        return Result(False, f"Aucun processus ne correspond a \"{cible}\".")

    interdits = [p for p in candidats
                 if (p.info.get("name") or "").lower() in NEVER_KILL]
    if interdits:
        noms = ", ".join(sorted({p.info["name"] for p in interdits}))
        return Result(False, (
            f"{noms} est un processus systeme. L'arreter ferait tomber ta "
            "session Windows. Je ne le fais pas."
        ))

    if len({p.info.get("name") for p in candidats}) > 1:
        noms = ", ".join(sorted({p.info["name"] for p in candidats}))
        return Result(False, f"Plusieurs processus correspondent : {noms}. "
                             "Precise lequel.")

    nom = candidats[0].info.get("name")
    pids = [p.pid for p in candidats]
    action = safety.Action(
        kind="processus",
        summary=f"Arreter {nom} ({len(pids)} processus)",
        targets=[f"{nom} pid {p}" for p in pids],
        reversible=True,
        details="Le programme peut etre relance normalement ensuite.",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    arretes, echecs = 0, []
    for proc in candidats:
        try:
            proc.terminate()
            arretes += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            echecs.append(f"pid {proc.pid} : {type(exc).__name__}")

    # terminate() demande poliment ; on laisse une seconde puis on insiste.
    time.sleep(1.0)
    for proc in candidats:
        try:
            if proc.is_running():
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if echecs and not arretes:
        return Result(False, f"Echec : {'; '.join(echecs)}. "
                             "Certains processus demandent les droits "
                             "administrateur.")
    return Result(True, f"{nom} arrete ({arretes} processus).")


# --- Services ---------------------------------------------------------------

def etat_service(nom: str) -> str:
    ok, sortie = _run(["sc", "query", nom])
    if not ok:
        return "inconnu"
    for ligne in sortie.splitlines():
        if "STATE" in ligne.upper() or "ÉTAT" in ligne.upper():
            return ligne.split(":")[-1].strip()
    return "inconnu"


def redemarrer_service(nom: str, ask=None) -> Result:
    """Relance un service Windows arrete ou bloque."""
    if nom.lower() in CRITICAL_SERVICES:
        return Result(False, (
            f"{nom} est un service critique de Windows. Le redemarrer peut "
            "faire tomber la session. Je ne le fais pas."
        ))

    action = safety.Action(
        kind="service",
        summary=f"Redemarrer le service {nom}",
        targets=[f"service {nom}"],
        reversible=True,
        details=f"Etat actuel : {etat_service(nom)}",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    _run(["net", "stop", nom], timeout=90)
    ok, sortie = _run(["net", "start", nom], timeout=90)
    if not ok:
        if _acces_refuse(sortie):
            return Result(False, (
                f"Droits insuffisants pour redemarrer {nom}.\n"
                "Gerer les services Windows demande les droits "
                "administrateur : clic droit sur le raccourci de l'assistant, "
                "\"Executer en tant qu'administrateur\"."
            ))
        return Result(False, f"Echec : {sortie[:200]}")
    return Result(True, f"Service {nom} redemarre.")


def _acces_refuse(sortie: str) -> bool:
    """Reconnait un refus de droits, quelle que soit la langue de Windows.

    Deux pieges se cumulent ici. D'abord l'accent : chercher "acces" dans un
    message qui dit "Acces refuse" avec accent ne matche pas. Ensuite
    l'encodage : net.exe ecrit dans la page de codes OEM, donc le caractere
    accentue revient abime et aucune normalisation ne le rattrape.

    On compare donc avec des motifs qui tolerent n'importe quel caractere a
    la place de l'accent.
    """
    import re

    texte = sortie.lower()
    motifs = (
        r"acc\W?s\s+refus",          # "Acces refuse", accent casse ou non
        r"access\s+is\s+denied",
        r"access\s+denied",
        r"erreur\s+syst\W?me\s+5",   # "L'erreur systeme 5 s'est produite"
        r"system\s+error\s+5",
        r"zugriff\s+verweigert",
    )
    return any(re.search(motif, texte) for motif in motifs)


# --- Caches -----------------------------------------------------------------

def vider_cache(nom: str, ask=None) -> Result:
    """Vide un cache identifie par analyser_nettoyage, vers la corbeille."""
    from assistant.skills import cleanup

    candidats = cleanup.candidates()
    correspondances = [
        (i + 1, c) for i, c in enumerate(candidats)
        if nom.lower() in c.label.lower() or nom.lower() in c.path.lower()
    ]
    if not correspondances:
        return Result(False, (
            f"Aucun cache ne correspond a \"{nom}\". Demande d'abord "
            "l'analyse du nettoyage."
        ))
    if len(correspondances) > 1:
        listing = ", ".join(f"{i}. {c.label}" for i, c in correspondances)
        return Result(False, f"Plusieurs correspondances : {listing}. "
                             "Precise laquelle.")

    numero, candidat = correspondances[0]
    message = cleanup.clean([numero], ask=ask)
    reussi = "corbeille" in message.lower()
    return Result(reussi, message)


# --- Catalogue des correctifs disponibles ------------------------------------

def disponibles() -> str:
    """Ce que l'assistant sait reparer, pour que l'utilisateur le sache."""
    return "\n".join([
        "Correctifs disponibles (chacun demande confirmation et est reversible) :",
        "",
        "  desactiver un programme au demarrage   la commande est conservee",
        "  reactiver un programme au demarrage    depuis la sauvegarde",
        "  arreter un processus                   refuse les processus systeme",
        "  redemarrer un service                  refuse les services critiques",
        "  vider un cache                         part a la corbeille",
        "",
        "Tout est journalise dans data/logs/actions.jsonl, accepte comme refuse.",
    ])
