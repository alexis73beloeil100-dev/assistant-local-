"""Mode jeu : preparer la machine avant de lancer un jeu.

Une seule phrase remplace une routine que les joueurs font a la main : fermer
les programmes gourmands, passer en profil performance, basculer le son sur
le casque, puis lancer le jeu.

Rien n'est ferme sans accord, et tout est reversible : "quitte le mode jeu"
remet le profil d'alimentation d'origine.
"""
from __future__ import annotations

from dataclasses import dataclass

from assistant import settings

# Programmes courants qui mangent du CPU, de la RAM ou du GPU sans etre utiles
# pendant une partie. On ne touche ni au launcher du jeu ni a l'audio.
GOURMANDS = {
    "chrome.exe": "navigateur",
    "msedge.exe": "navigateur",
    "firefox.exe": "navigateur",
    "opera.exe": "navigateur",
    "brave.exe": "navigateur",
    "slack.exe": "messagerie",
    "teams.exe": "messagerie",
    "onedrive.exe": "synchronisation",
    "dropbox.exe": "synchronisation",
    "googledrivefs.exe": "synchronisation",
    "photoshop.exe": "creation",
    "unrealeditor.exe": "moteur de jeu",
    "devenv.exe": "developpement",
    "code.exe": "developpement",
    "obs64.exe": "capture video",
    "searchindexer.exe": "indexation Windows",
}

# Jamais ferme : ce sont les compagnons normaux d'une session de jeu.
EPARGNES = {
    "discord.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
    "upc.exe", "eadesktop.exe", "riotclientservices.exe", "nvcontainer.exe",
    "assistantlocal.exe", "ollama.exe", "llama-server.exe",
}


@dataclass
class Candidat:
    nom: str
    pids: list
    ram: int
    role: str


def _candidats() -> list[Candidat]:
    import psutil

    par_nom: dict[str, Candidat] = {}
    for proc in psutil.process_iter(["name", "pid", "memory_info"]):
        try:
            nom = (proc.info.get("name") or "").lower()
            if nom not in GOURMANDS or nom in EPARGNES:
                continue
            memoire = proc.info.get("memory_info")
            ram = memoire.rss if memoire else 0
            if nom in par_nom:
                par_nom[nom].pids.append(proc.info["pid"])
                par_nom[nom].ram += ram
            else:
                par_nom[nom] = Candidat(nom, [proc.info["pid"]], ram,
                                        GOURMANDS[nom])
        except Exception:  # noqa: BLE001
            continue
    return sorted(par_nom.values(), key=lambda c: c.ram, reverse=True)


def apercu() -> str:
    """Ce que le mode jeu ferait, sans rien faire."""
    from assistant.skills import control
    from assistant.util import human_size

    trouves = _candidats()
    lignes = ["MODE JEU", ""]

    if trouves:
        total = sum(c.ram for c in trouves)
        lignes.append(f"  A fermer ({human_size(total)} de RAM liberee) :")
        for candidat in trouves:
            lignes.append(f"     {human_size(candidat.ram):>10}  "
                          f"{candidat.nom}  ({candidat.role})")
    else:
        lignes.append("  Rien de gourmand a fermer.")

    lignes.append("")
    lignes.append(f"  Alimentation actuelle : {control.power_plan()}")
    lignes.append("  Le mode jeu passera en profil performance.")
    lignes.append("")
    lignes.append("  Sortie audio actuelle :")
    for ligne in control.audio_outputs().splitlines()[1:]:
        if ligne.strip().startswith("->"):
            lignes.append(f"    {ligne.strip()}")
    lignes.append("")
    lignes.append("  Dis \"mode jeu\" pour l'activer, ou \"mode jeu avec "
                  "<jeu>\" pour enchainer sur le lancement.")
    lignes.append("  \"quitte le mode jeu\" remet le profil d'origine.")
    return "\n".join(lignes)


def activer(jeu: str = "", audio: str = "", ask=None) -> str:
    """Prepare la machine, puis lance le jeu si un nom est donne."""
    from assistant.skills import control, fixes, games
    from assistant.util import human_size

    rapport = ["MODE JEU ACTIVE", ""]

    # 1. Profil d'alimentation, apres avoir memorise l'actuel.
    if not settings.get("gamemode_plan_precedent"):
        settings.set("gamemode_plan_precedent", control.power_plan())
    rapport.append("  " + control.power_plan("performance"))

    # 2. Sortie audio, si demandee.
    if audio:
        rapport.append("  " + control.set_audio_output(audio))

    # 3. Fermeture des gourmands, chacun soumis a confirmation.
    trouves = _candidats()
    if not trouves:
        rapport.append("  Aucun programme gourmand a fermer.")
    else:
        libere = 0
        for candidat in trouves:
            resultat = fixes.arreter_processus(candidat.nom, ask=ask)
            if resultat.ok:
                libere += candidat.ram
                rapport.append(f"  ferme : {candidat.nom} "
                               f"({human_size(candidat.ram)})")
            else:
                rapport.append(f"  garde : {candidat.nom} — {resultat.message[:60]}")
        if libere:
            rapport.append(f"  {human_size(libere)} de RAM liberee.")

    settings.set("gamemode_actif", True)

    # 4. Lancement du jeu.
    if jeu:
        rapport.append("")
        ok, message = games.launch(jeu)
        rapport.append("  " + message)

    rapport.append("")
    rapport.append("  \"quitte le mode jeu\" remet le profil d'alimentation.")
    return "\n".join(rapport)


def quitter() -> str:
    """Remet la machine dans son etat d'avant."""
    from assistant.skills import control

    precedent = settings.get("gamemode_plan_precedent", "")
    settings.set("gamemode_actif", False)

    if not precedent:
        return ("Le mode jeu n'etait pas actif. "
                + control.power_plan("equilibre"))

    # On retrouve le profil d'origine par son libelle memorise.
    for cle in ("performance", "equilibre", "economie"):
        if cle in precedent.lower() or (
            cle == "performance" and "eleve" in precedent.lower()
        ):
            settings.set("gamemode_plan_precedent", "")
            return "Mode jeu quitte. " + control.power_plan(cle)

    settings.set("gamemode_plan_precedent", "")
    return "Mode jeu quitte. " + control.power_plan("equilibre")


def actif() -> bool:
    return bool(settings.get("gamemode_actif", False))
