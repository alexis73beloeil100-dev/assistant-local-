"""Ce qui verse dans la connaissance tout ce que l'assistant releve deja.

Le materiel, les jeux, les programmes de demarrage, les disques etaient
releves au lancement puis ranges chacun dans son coin, utilisables seulement
par le panneau qui les affichait. Une question transversale -- "est-ce que
mon pilote graphique est a jour ?", "qu'est-ce qui pourrait ralentir Assetto
Corsa ?" -- n'avait aucun endroit ou puiser.

Tout converge desormais vers assistant.connaissance, qui vit en **memoire
vive uniquement** et se reconstruit a chaque demarrage.

Ce module ne releve rien lui-meme : il branche les competences existantes sur
le magasin. Chaque source garde donc son unique implementation.
"""
from __future__ import annotations

import threading

from assistant import connaissance


def _materiel() -> None:
    from assistant.skills import hardware

    donnees = hardware.collect()
    if not donnees:
        return

    machine, cpu = donnees.get("machine", {}), donnees.get("cpu", {})
    connaissance.apprendre("materiel", "processeur",
                           f"{str(cpu.get('name', '?')).strip()} — "
                           f"{cpu.get('cores', '?')} coeurs / "
                           f"{cpu.get('threads', '?')} threads",
                           source="releve materiel")
    connaissance.apprendre("materiel", "carte mere",
                           f"{machine.get('board', '?')}  BIOS "
                           f"{machine.get('bios', '?')} "
                           f"({machine.get('bios_date', '?')})",
                           source="releve materiel")
    connaissance.apprendre("materiel", "memoire vive",
                           f"{machine.get('ram_gb', '?')} Go sur "
                           f"{len(donnees.get('ram') or [])} barrette(s)",
                           source="releve materiel")

    for carte in donnees.get("gpu") or []:
        connaissance.apprendre(
            "materiel", f"carte graphique {carte.get('name', '?')}",
            f"pilote {carte.get('driver', '?')} du "
            f"{carte.get('driver_date', 'date inconnue')}",
            source="releve materiel")

    for disque in donnees.get("physical_disks") or []:
        connaissance.apprendre(
            "disques", str(disque.get("name", "?")),
            f"{disque.get('size_gb', '?')} Go  {disque.get('media', '?')}  "
            f"{disque.get('bus', '?')}  etat {disque.get('health', '?')}",
            source="releve materiel")

    for volume in donnees.get("volumes") or []:
        if (volume.get("size_gb") or 0) < 20:
            continue
        connaissance.apprendre(
            "disques", f"volume {volume.get('letter')}:",
            f"{volume.get('free_gb', 0):.0f} Go libres sur "
            f"{volume.get('size_gb', 0):.0f} Go — {volume.get('label', '')}",
            source="releve materiel")

    systeme = donnees.get("os", {})
    connaissance.apprendre("materiel", "windows",
                           f"{systeme.get('caption', '?')} build "
                           f"{systeme.get('build', '?')}, installe le "
                           f"{systeme.get('installed', '?')}",
                           source="releve materiel")


def _jeux() -> None:
    from assistant.skills import games

    for jeu in games.all_games():
        taille = (f"{jeu.size_bytes / 1e9:.1f} Go"
                  if jeu.size_bytes else "taille inconnue")
        connaissance.apprendre("jeux", jeu.name,
                               f"{jeu.launcher} — {taille} — {jeu.install_dir}",
                               source="detection des launchers")


def _demarrage() -> None:
    from assistant.skills import system

    for item in system.startup_items():
        connaissance.apprendre(
            "demarrage", str(item.get("name", "?")),
            f"[{item.get('source', '?')}] {str(item.get('command', ''))[:200]}",
            source="registre et dossier Demarrage")


def _applications() -> None:
    from assistant.skills import apps

    for application in apps.catalogue():
        connaissance.apprendre("applications", application.nom,
                               str(application.cible),
                               source="catalogue des applications")


def _inventaire() -> None:
    from assistant.skills import inventaire

    inventaire.collect()      # se range lui-meme dans la connaissance


# L'ordre compte : le materiel d'abord, parce que c'est ce qu'on demande le
# plus souvent, et l'inventaire logiciel en dernier, parce qu'il est le plus
# long. Chaque source est isolee -- une qui echoue ne doit pas emporter les
# autres avec elle.
SOURCES = (
    ("materiel", _materiel),
    ("jeux", _jeux),
    ("demarrage", _demarrage),
    ("applications", _applications),
    ("inventaire logiciel", _inventaire),
)


# Sources qui ont echoue au dernier passage, avec leur raison.
#
# Une source isolee par un try/except disparait sans bruit : c'est ainsi que
# les jeux ont manque a l'appel pendant un moment, parce que le code lisait
# jeu.path quand le champ s'appelle install_dir. On garde donc la trace, et le
# panneau l'affiche.
echecs: dict[str, str] = {}


def tout_apprendre(on_progress=None) -> int:
    """Verse toutes les sources dans la connaissance. Rend le nombre de faits."""
    echecs.clear()
    for nom, source in SOURCES:
        if on_progress:
            on_progress(nom)
        try:
            source()
        except Exception as exc:  # noqa: BLE001 - une source muette vaut mieux qu'un plantage
            echecs[nom] = f"{type(exc).__name__}: {exc}"
    return connaissance.total()


def en_arriere_plan(on_done=None) -> threading.Thread:
    def travail():
        total = tout_apprendre()
        if on_done:
            on_done(total)

    fil = threading.Thread(target=travail, name="apprentissage", daemon=True)
    fil.start()
    return fil


def apprendre_de_la_session(question: str, outil: str, resultat: str) -> None:
    """Retient ce qu'un outil vient d'apprendre pendant la conversation.

    C'est ce qui fait qu'une question posee deux fois ne relance pas le meme
    releve, et qu'un detail decouvert en passant reste disponible pour la
    suite de la session.

    On ne retient QUE le resume d'un resultat, jamais un contenu de fichier :
    la limite de longueur de connaissance.apprendre s'en charge, mais on
    tronque deja ici pour ne pas transporter des pages inutiles.
    """
    resume = " ".join(str(resultat).split())[:400]
    if not resume:
        return
    connaissance.apprendre("session", f"{outil} — {question[:60]}", resume,
                           source="outil appele pendant la conversation")
