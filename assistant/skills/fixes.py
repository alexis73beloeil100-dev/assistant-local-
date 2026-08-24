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
        # Sans confirmation : c'est une case a cocher, pas une decision. La
        # commande exacte est sauvegardee avant, "reactiver <nom>" la remet.
        routine=True,
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
        routine=True,
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

def arreter_processus(cible: str, ask=None, routine: bool = True) -> Result:
    """Arrete un processus qui monopolise la machine.

    Refuse les processus systeme : arreter lsass ou csrss fait tomber la
    session immediatement, ce n'est jamais ce que l'utilisateur veut.

    Sans confirmation, par defaut. Fermer un programme est un geste ordinaire,
    et le reouvrir coute un clic. Demander l'accord a chaque "ferme Chrome"
    rendait la commande vocale absurde : il fallait lacher ce qu'on faisait
    pour cliquer "oui" a ce qu'on venait de dire a voix haute.

    Ce qui protege ici, ce n'est pas la question posee : c'est NEVER_KILL, qui
    refuse les processus systeme quoi qu'on demande, et le journal des actions
    qui garde la trace de tout.
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
        routine=routine,
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
        # Sans confirmation : ce qui pourrait casser Windows est deja refuse
        # plus haut par CRITICAL_SERVICES, avant meme d'arriver ici. Ce qui
        # reste, ce sont des services ordinaires qu'on relance.
        routine=True,
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    _run(["net", "stop", nom], timeout=90)
    ok, sortie = _run(["net", "start", nom], timeout=90)
    if ok:
        return Result(True, f"Service {nom} redemarre.")

    if not _acces_refuse(sortie):
        return Result(False, f"Echec : {sortie[:200]}")

    # Droits insuffisants -- le cas NORMAL, pas l'exception.
    #
    # L'assistant tourne volontairement sans privileges : c'est ce sur quoi
    # repose son garde-fou. Or gerer un service Windows demande toujours
    # l'administrateur. L'ancien message conseillait donc de relancer toute
    # l'application en administrateur, ce qui defaisait exactement la
    # propriete qu'on cherche a garder -- et rendait l'outil inutilisable
    # dans les faits.
    #
    # On demande donc l'elevation POUR CETTE SEULE OPERATION, comme le fait
    # deja le RGB. Une fenetre Windows, puis on relit l'etat du service au
    # lieu de croire un compte-rendu.
    from assistant.skills.rgb import _executer_eleve

    erreur = _executer_eleve([
        f"Stop-Service -Name '{nom}' -Force -ErrorAction SilentlyContinue",
        f"Start-Service -Name '{nom}' -ErrorAction SilentlyContinue",
    ])
    if erreur:
        return Result(False, erreur)

    etat = etat_service(nom)
    if "running" in etat.lower() or "en cours" in etat.lower():
        return Result(True, f"Service {nom} redemarre (avec elevation).")
    return Result(False, (
        f"{nom} n'a pas redemarre : l'autorisation administrateur a "
        f"probablement ete refusee. Etat actuel : {etat}."
    ))


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
    # Le caractere a la place de l'accent est note ".?" et non "\W?" : un
    # accent correctement decode ("è") est une LETTRE, que \W ne matche pas.
    # La premiere version ne reconnaissait donc que les messages abimes, et
    # echouait sur une machine ou l'encodage fonctionne.
    motifs = (
        r"acc.?s\s+refus",           # "Acces refuse" / "Accès refusé"
        r"access\s+is\s+denied",
        r"access\s+denied",
        r"erreur\s+syst.?me\s+5",    # "L'erreur système 5 s'est produite"
        r"system\s+error\s+5",
        r"zugriff\s+verweigert",
    )
    return any(re.search(motif, texte) for motif in motifs)


# --- Caches -----------------------------------------------------------------

def vider_cache(nom: str, ask=None) -> Result:
    """Vide un cache identifie par analyser_nettoyage, vers la corbeille."""
    from assistant.index import db
    from assistant.skills import cleanup

    # Les candidats se chiffrent depuis l'index : sans lui, la requete SQL
    # tombait sur une table absente et remontait une erreur sqlite brute.
    if not db.is_ready():
        return Result(False, (
            "L'index des fichiers est encore en construction "
            "(environ 80 secondes apres le demarrage). "
            "Le reste de l'assistant fonctionne deja."
        ))

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


# --- Reparation de Windows lui-meme -----------------------------------------
#
# Deux outils de Microsoft, et l'ordre entre eux n'est pas une preference.
#
# sfc compare chaque fichier systeme a sa version d'origine et remplace ceux
# qui sont abimes. Il prend cette version d'origine dans le magasin de
# composants de Windows -- si CE magasin est lui-meme abime, sfc annonce
# qu'il a trouve des erreurs sans pouvoir les corriger, et le relancer dix
# fois n'y changera rien.
#
# DISM repare le magasin. C'est pour cela qu'il vient AVANT quand sfc echoue :
# il refait la source dans laquelle sfc puise.

SFC = "sfc /scannow"
DISM = "DISM /Online /Cleanup-Image /RestoreHealth"


def _lancer_en_admin(commande: str, fenetre: str) -> tuple[bool, str]:
    """Ouvre une console administrateur VISIBLE, et n'attend pas la fin.

    CACHEE, et la progression revient DANS l'application.

    La premiere version ouvrait une console noire, pour que la progression
    reste visible : une reparation cachee derriere un assistant qui semble
    fige se fait interrompre a mi-chemin. Le raisonnement tenait, la mise en
    oeuvre etait mauvaise. Une fenetre noire par action, sur une application
    qui en enchaine, donne l'impression d'un bricolage -- et l'utilisateur l'a
    dit avant meme d'avoir fini de les essayer.

    La sortie part donc dans un fichier journal que le panneau relit. On garde
    ce qui comptait -- la progression est visible, personne ne croit
    l'application figee -- sans la fenetre.

    Ce qui NE PEUT PAS disparaitre : l'invite UAC. sfc et DISM exigent les
    droits administrateur, cette fenetre appartient a Windows, et une
    application qui saurait s'en passer serait une faille, pas une
    fonctionnalite.

    Sans attendre non plus : bloquer l'assistant une demi-heure le rendrait
    inutilisable.
    """
    import tempfile
    from pathlib import Path as _Path

    dossier = _Path(tempfile.gettempdir())
    # Un journal par operation : deux reparations lancees a la suite ne
    # doivent pas melanger leurs lignes dans le meme fichier.
    etiquette = "".join(c if c.isalnum() else "_" for c in fenetre)[:40]
    journal = dossier / f"assistant_{etiquette}.log"
    script = dossier / f"assistant_{etiquette}.cmd"

    # Le journal ne contient QUE la sortie de la commande, et le signal de fin
    # vit dans un fichier a part.
    #
    # Melanger les deux a coute une heure : sfc.exe ecrit en UTF-16, une
    # ligne d'en-tete ecrite en UTF-8 avant lui decalait tout le reste d'un
    # octet, et le panneau affichait du chinois. Un fichier, un encodage.
    temoin = journal.with_suffix(".fini")
    try:
        journal.write_bytes(b"")
        temoin.unlink(missing_ok=True)
        script.write_text("\r\n".join([
            "@echo off",
            f'{commande} > "{journal}" 2>&1',
            f'echo fini> "{temoin}"',
        ]), encoding="utf-8")
    except OSError as exc:
        return False, f"Ecriture impossible : {exc}"

    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command",
             f"Start-Process -FilePath '{script}' -Verb RunAs "
             "-WindowStyle Hidden"],
            capture_output=True, text=True, timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"Elevation impossible : {type(exc).__name__}: {exc}"
    return True, str(journal)


def progression(journal: str) -> tuple[bool, str]:
    """Ou en est une operation lancee en arriere-plan.

    Rend (terminee, derniere ligne utile). sfc reecrit sa progression sur la
    meme ligne avec des retours chariot : le journal contient donc une seule
    ligne enorme, dont seul le dernier morceau interesse.
    """
    from pathlib import Path as _Path

    chemin = _Path(journal)
    fini = chemin.with_suffix(".fini").exists()
    try:
        octets = chemin.read_bytes()
    except OSError:
        return fini, "En attente ..."

    # sfc.exe ecrit en UTF-16, un octet nul entre chaque lettre. Lu en UTF-8,
    # son "La verification" ressortait "L a   v e r i f i c a t i o n". On
    # reconnait l'encodage au lieu de le supposer : DISM et Defender, eux,
    # ecrivent en 8 bits.
    if octets.count(b"\x00") > len(octets) // 4:
        brut = octets.decode("utf-16-le", errors="replace")
    else:
        brut = octets.decode("utf-8", errors="replace")

    morceaux = [m.strip() for m in brut.replace("\r", "\n").split("\n")]
    utiles = [m for m in morceaux if m]
    if not utiles:
        return fini, ("Termine." if fini else "En cours ...")

    if fini:
        # A la fin, le verdict tient dans les dernieres lignes, pas dans la
        # progression : on en montre plusieurs.
        return True, "\n".join(utiles[-8:])
    return False, utiles[-1]


def verifier_fichiers_systeme(ask=None) -> Result:
    """Lance sfc /scannow : les fichiers systeme abimes sont remplaces.

    Irreversible au sens du garde-fou, et c'est voulu : une reparation ne
    s'annule pas. Rien n'est detruit pour autant -- sfc ne touche qu'aux
    fichiers de Windows, jamais aux donnees personnelles.
    """
    action = safety.Action(
        kind="systeme",
        summary="Verifier et reparer les fichiers systeme de Windows (sfc)",
        targets=["fichiers systeme de Windows"],
        reversible=False,
        details=(f"{SFC} -- compare chaque fichier systeme a sa version "
                 "d'origine et remplace ceux qui sont abimes. 5 a 15 minutes, "
                 "dans une fenetre administrateur separee. Aucune donnee "
                 "personnelle n'est touchee."),
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    ok, journal = _lancer_en_admin(SFC, "Verification des fichiers systeme")
    if not ok:
        return Result(False, journal)

    return Result(True, (
        "Verification lancee. Compte 5 a 15 minutes ; la progression "
        f"s'affiche dans le panneau Reparer Windows.\n[journal:{journal}]\n"
        "  \"aucune violation d'integrite\" : Windows est sain.\n"
        "  \"a reussi a reparer\"           : c'etait abime, c'est corrige.\n"
        "  \"n'a pas pu reparer\"           : le magasin de composants est "
        "lui-meme abime. Demande-moi alors de reparer l'image de Windows, "
        "puis relance cette verification."
    ))


def reparer_image_windows(ask=None) -> Result:
    """Lance DISM /RestoreHealth : repare le magasin dont sfc se sert.

    A demander quand sfc annonce avoir trouve des erreurs sans pouvoir les
    corriger. Relancer sfc dans ce cas ne sert a rien : c'est sa source qui
    est en cause, pas sa lecture.

    Seule reparation de l'assistant qui utilise le reseau : DISM va chercher
    les fichiers sains manquants aupres de Windows Update. C'est une
    exception assumee -- sans elle, un magasin abime ne se repare pas -- et
    elle ne part que sur demande explicite.
    """
    action = safety.Action(
        kind="systeme",
        summary="Reparer l'image de Windows (DISM RestoreHealth)",
        targets=["magasin de composants de Windows"],
        reversible=False,
        details=(f"{DISM} -- repare la reserve de fichiers d'origine dans "
                 "laquelle sfc puise. 10 a 30 minutes, dans une fenetre "
                 "administrateur separee. Peut telecharger des fichiers sains "
                 "depuis Windows Update."),
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    ok, journal = _lancer_en_admin(DISM, "Reparation de l'image de Windows")
    if not ok:
        return Result(False, journal)

    return Result(True, (
        "Reparation de l'image lancee. Compte 10 a 30 minutes ; la "
        "progression reste longtemps a 20 %, c'est normal.\n"
        f"[journal:{journal}]\n"
        "Quand elle est finie, demande-moi la verification des fichiers "
        "systeme : c'est elle qui repare, maintenant qu'elle a une source "
        "saine."
    ))


# --- Recherche de menaces ----------------------------------------------------
#
# Windows Defender est deja installe et deja actif sur cette machine : le
# releve materiel lit son etat a chaque demarrage, et reparation.py signale
# ses signatures perimees. Ce qui manquait, c'est de pouvoir LANCER un examen.
#
# On ne fait pas installer un antivirus tiers. Il y en a un, il fonctionne, et
# en superposer un second est la meilleure facon de ralentir la machine et de
# faire s'accuser mutuellement deux protections.

SCAN_RAPIDE = "QuickScan"
SCAN_COMPLET = "FullScan"


def _menaces_connues() -> str:
    """Ce que Defender a deja trouve, historique compris."""
    ok, sortie = _run([
        "powershell.exe", "-NoProfile", "-Command",
        "Get-MpThreatDetection | Sort-Object InitialDetectionTime "
        "-Descending | Select-Object -First 10 "
        "ThreatID, InitialDetectionTime, Resources | Format-List",
    ], timeout=60)
    return sortie if ok else ""


def menaces() -> str:
    """Ce que Defender a detecte, et l'etat de la protection.

    Lecture seule : aucune analyse n'est lancee ici. Repondre "rien" apres
    quinze minutes d'attente n'est pas la meme chose que repondre "rien" tout
    de suite, et les deux questions se posent separement.
    """
    from assistant.skills import hardware

    lignes = ["PROTECTION ANTIVIRUS", ""]
    try:
        donnees = hardware.collect() or {}
    except Exception as exc:  # noqa: BLE001 - un releve muet vaut mieux qu'un plantage
        donnees = {}
        lignes.append(f"  Etat illisible : {type(exc).__name__}")

    defender = donnees.get("defender") or {}
    if defender:
        actif = defender.get("realtime")
        lignes.append(f"  Protection en temps reel   "
                      f"{'active' if actif else 'DESACTIVEE'}")
        age = defender.get("signature_age")
        if isinstance(age, (int, float)):
            etat = "a jour" if age <= 7 else f"perimees ({age:.0f} jours)"
            lignes.append(f"  Signatures                 {etat}")

    trouve = _menaces_connues()
    lignes.append("")
    if trouve.strip():
        lignes.append("  Menaces deja detectees par Defender :")
        lignes.extend(f"    {l}" for l in trouve.strip().splitlines()[:20])
    else:
        lignes.append("  Aucune menace dans l'historique de Defender.")

    lignes.append("")
    lignes.append("  Demande-moi une analyse si tu veux qu'il cherche "
                  "maintenant.")
    return "\n".join(lignes)


def analyser_menaces(complet: bool = False, ask=None) -> Result:
    """Lance un examen antivirus avec Defender.

    Les signatures sont mises a jour AVANT, et ce n'est pas du zele : un
    examen mene avec des signatures d'il y a trois semaines ne reconnait pas
    ce qui est apparu depuis, et rend un "aucune menace" qui rassure a tort.
    C'est pire que pas d'examen du tout.

    L'examen tourne dans une fenetre administrateur visible, sans qu'on
    l'attende -- meme raison que pour sfc. Le rapide dure une dizaine de
    minutes, le complet plusieurs heures : attendre l'un ou l'autre gelerait
    l'assistant.
    """
    genre = SCAN_COMPLET if complet else SCAN_RAPIDE
    duree = ("plusieurs heures" if complet else "5 a 20 minutes")

    action = safety.Action(
        kind="systeme",
        summary=f"Lancer un examen antivirus ({'complet' if complet else 'rapide'})",
        targets=["Windows Defender"],
        reversible=True,
        details=(f"Met a jour les signatures, puis examine la machine. "
                 f"Dure {duree}, dans une fenetre administrateur separee. "
                 "Rien n'est supprime sans que Defender le signale."),
        # Chercher des menaces ne casse rien et ne s'annule pas non plus :
        # c'est une lecture, longue mais inoffensive.
        routine=True,
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return Result(False, str(exc))

    commande = (f"powershell -NoProfile -Command \"Update-MpSignature; "
                f"Start-MpScan -ScanType {genre}\"")
    ok, journal = _lancer_en_admin(commande, f"Examen antivirus ({genre})")
    if not ok:
        return Result(False, journal)

    return Result(True, (
        f"Examen {'complet' if complet else 'rapide'} lance, apres mise a "
        f"jour des signatures. Compte {duree}.\n"
        f"[journal:{journal}]\n"
        "Defender n'annonce aucun pourcentage : la ligne de progression ne "
        "bougera qu'a la fin.\n"
        "Quand c'est fini, demande-moi les menaces detectees."
    ))


# --- Catalogue des correctifs disponibles ------------------------------------

def disponibles() -> str:
    """Ce que l'assistant sait reparer, pour que l'utilisateur le sache."""
    return "\n".join([
        "Correctifs disponibles (chacun demande confirmation) :",
        "",
        "  desactiver un programme au demarrage   la commande est conservee",
        "  reactiver un programme au demarrage    depuis la sauvegarde",
        "  arreter un processus                   refuse les processus systeme",
        "  redemarrer un service                  refuse les services critiques",
        "  vider un cache                         part a la corbeille",
        "  verifier les fichiers systeme          sfc, 5 a 15 min, en admin",
        "  reparer l'image de Windows             DISM, 10 a 30 min, en admin",
        "  analyser les menaces                   Defender, signatures a jour",
        "",
        "Les cinq premiers sont reversibles. Les deux reparations de Windows "
        "ne le sont pas : on ne defait pas un fichier repare.",
        "",
        "Tout est journalise dans data/logs/actions.jsonl, accepte comme refuse.",
    ])
