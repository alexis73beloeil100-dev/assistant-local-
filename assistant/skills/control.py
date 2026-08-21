"""Controle du PC : son, peripheriques audio, alimentation, session.

Ce que tout le monde essaie en premier avec un assistant vocal. L'echec sur
"baisse le son" donne l'impression que rien ne marche, meme si le reste est
irreprochable.

Les actions qui coupent le travail en cours (veille, arret, redemarrage)
passent par assistant.safety. Regler le volume, non : ce serait insupportable
de confirmer chaque "monte le son".
"""
from __future__ import annotations

import subprocess
import threading

from assistant import safety

CREATE_NO_WINDOW = 0x08000000

# Profils d'alimentation Windows, par identifiant stable. Les noms sont
# traduits selon la langue du systeme, les GUID non.
POWER_PLANS = {
    "performance": ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "Performances elevees"),
    "equilibre":   ("381b4222-f694-41f0-9685-ff5bb260df2e", "Utilisation normale"),
    "economie":    ("a1841308-3541-4fab-bc81-f71556f20b4a", "Economie d'energie"),
}


def _run(args: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return result.returncode == 0, ((result.stdout or "") + (result.stderr or "")).strip()


# --- Volume -----------------------------------------------------------------

_com_local = threading.local()


def _ensure_com() -> None:
    """Initialise COM pour le thread courant.

    L'API audio de Windows est du COM : elle exige CoInitialize dans CHAQUE
    thread qui l'utilise. L'interface calcule ses panneaux dans des threads
    de fond, ou l'appel echouait sur "CoInitialize n'a pas ete appele" -- et
    le volume s'affichait a -1 sans autre explication.
    """
    if getattr(_com_local, "pret", False):
        return
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:  # noqa: BLE001 - deja initialise, ou COM indisponible
        pass
    _com_local.pret = True


def _endpoint():
    from pycaw.utils import AudioUtilities

    _ensure_com()
    return AudioUtilities.GetSpeakers().EndpointVolume


def volume() -> int:
    try:
        return round(_endpoint().GetMasterVolumeLevelScalar() * 100)
    except Exception:  # noqa: BLE001
        return -1


def set_volume(niveau: int) -> str:
    """Regle le volume general, en pourcentage."""
    niveau = max(0, min(int(niveau), 100))
    try:
        controle = _endpoint()
        controle.SetMasterVolumeLevelScalar(niveau / 100, None)
        if niveau > 0 and controle.GetMute():
            controle.SetMute(0, None)
    except Exception as exc:  # noqa: BLE001
        return f"Reglage du volume impossible : {type(exc).__name__}: {exc}"
    return f"Volume a {niveau} %."


def change_volume(delta: int) -> str:
    """Monte ou baisse le volume d'un cran."""
    actuel = volume()
    if actuel < 0:
        return "Volume illisible sur ce peripherique."
    return set_volume(actuel + delta)


def mute(couper: bool | None = None) -> str:
    """Coupe, retablit, ou bascule le son."""
    try:
        controle = _endpoint()
        etat = bool(controle.GetMute())
        cible = (not etat) if couper is None else bool(couper)
        controle.SetMute(1 if cible else 0, None)
    except Exception as exc:  # noqa: BLE001
        return f"Impossible : {type(exc).__name__}: {exc}"
    return "Son coupe." if cible else f"Son retabli ({volume()} %)."


# --- Peripheriques audio ----------------------------------------------------

def _output_devices() -> list:
    """Sorties audio actives, doublons de nom ecartes.

    Deux pieges de l'API : `state` est une enumeration (pas l'entier de
    DEVICE_STATE), et GetEndpointDataFlow rend la chaine "eRender", pas la
    valeur numerique. Comparer aux entiers filtrait tout, silencieusement.
    """
    from pycaw.utils import AudioUtilities

    _ensure_com()
    sorties = []
    vus = set()
    for appareil in AudioUtilities.GetAllDevices():
        try:
            if getattr(appareil.state, "value", appareil.state) != 1:
                continue   # 1 = Active ; les autres sont debranches
            if str(AudioUtilities.GetEndpointDataFlow(appareil.id)) != "eRender":
                continue
            nom = appareil.FriendlyName
            if not nom or nom in vus:
                continue
            vus.add(nom)
            sorties.append(appareil)
        except Exception:  # noqa: BLE001
            continue
    return sorties


def audio_outputs() -> str:
    """Peripheriques de sortie disponibles, avec celui utilise."""
    from pycaw.utils import AudioUtilities

    _ensure_com()
    try:
        actuel = AudioUtilities.GetSpeakers().FriendlyName
        appareils = _output_devices()
    except Exception as exc:  # noqa: BLE001
        return f"Liste impossible : {type(exc).__name__}: {exc}"

    if not appareils:
        return "Aucun peripherique de sortie actif."

    lignes = ["Sorties audio disponibles :"]
    for appareil in appareils:
        marque = "  ->" if appareil.FriendlyName == actuel else "    "
        lignes.append(f"{marque} {appareil.FriendlyName}")
    lignes.append("")
    lignes.append("La fleche indique la sortie utilisee.")
    return "\n".join(lignes)


def set_audio_output(nom: str) -> str:
    """Bascule la sortie audio, par exemple du casque aux haut-parleurs."""
    from pycaw.utils import AudioUtilities

    _ensure_com()
    try:
        appareils = _output_devices()
    except Exception as exc:  # noqa: BLE001
        return f"Impossible : {type(exc).__name__}: {exc}"

    besoin = nom.lower()
    correspondances = [a for a in appareils if besoin in a.FriendlyName.lower()]

    # "casque" et "haut-parleur" sont les deux demandes courantes : on les
    # traduit vers les mots que Windows emploie reellement.
    if not correspondances:
        synonymes = {
            "casque": ("headphone", "casque", "headset", "ecouteur"),
            "haut-parleur": ("speaker", "haut-parleur", "hp"),
            "hp": ("speaker", "haut-parleur"),
            "ecran": ("nvidia", "hdmi", "display"),
            "hdmi": ("hdmi", "nvidia"),
        }
        for cle, mots in synonymes.items():
            if cle in besoin:
                correspondances = [
                    a for a in appareils
                    if any(m in a.FriendlyName.lower() for m in mots)
                ]
                break

    if not correspondances:
        return (f"Aucune sortie ne correspond a \"{nom}\".\n\n"
                + audio_outputs())
    if len(correspondances) > 1:
        noms = ", ".join(a.FriendlyName for a in correspondances)
        return f"Plusieurs sorties correspondent : {noms}. Precise laquelle."

    cible = correspondances[0]
    try:
        AudioUtilities.SetDefaultDevice(cible.id)
    except Exception as exc:  # noqa: BLE001
        return f"Bascule impossible : {type(exc).__name__}: {exc}"
    return f"Sortie audio : {cible.FriendlyName}."


# --- Alimentation -----------------------------------------------------------

def power_plan(nom: str | None = None) -> str:
    """Lit ou change le profil d'alimentation de Windows."""
    if nom is None:
        ok, sortie = _run(["powercfg", "/getactivescheme"])
        return sortie if ok else "Profil illisible."

    besoin = nom.lower()
    choix = next((v for k, v in POWER_PLANS.items() if k in besoin), None)
    if choix is None:
        return ("Profils disponibles : performance, equilibre, economie.")

    guid, libelle = choix
    ok, sortie = _run(["powercfg", "/setactive", guid])
    if not ok:
        return f"Echec : {sortie[:160]}"
    return f"Profil d'alimentation : {libelle}."


# --- Session ----------------------------------------------------------------

def lock_session() -> str:
    """Verrouille la session. Sans confirmation : c'est sans risque."""
    ok, sortie = _run(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Session verrouillee." if ok else f"Echec : {sortie[:120]}"


def sleep(ask=None) -> str:
    """Met la machine en veille."""
    action = safety.Action(
        kind="processus",
        summary="Mettre la machine en veille",
        targets=["session Windows"],
        reversible=True,
        details="Le travail en cours reste ouvert.",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    # L'hibernation doit etre desactivee, sinon SetSuspendState hiberne au
    # lieu de mettre en veille.
    ok, sortie = _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    return "Mise en veille." if ok else f"Echec : {sortie[:120]}"


def shutdown(delai: int = 30, redemarrer: bool = False, ask=None) -> str:
    """Eteint ou redemarre, avec un delai pour pouvoir annuler."""
    quoi = "Redemarrer" if redemarrer else "Eteindre"
    action = safety.Action(
        kind="processus",
        summary=f"{quoi} la machine dans {delai} secondes",
        targets=["session Windows"],
        reversible=True,
        details="Annulable pendant le delai en disant \"annule l'arret\".",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    drapeau = "/r" if redemarrer else "/s"
    ok, sortie = _run(["shutdown", drapeau, "/t", str(delai)])
    if not ok:
        return f"Echec : {sortie[:160]}"
    return (f"{quoi} dans {delai} secondes. "
            "Dis \"annule l'arret\" pour revenir en arriere.")


def cancel_shutdown() -> str:
    ok, sortie = _run(["shutdown", "/a"])
    if not ok:
        return "Aucun arret n'etait programme."
    return "Arret annule."


# --- Vue d'ensemble ---------------------------------------------------------

def status() -> str:
    from pycaw.utils import AudioUtilities

    _ensure_com()
    lignes = ["CONTROLE DU PC", ""]
    niveau = volume()
    try:
        coupe = bool(_endpoint().GetMute())
    except Exception:  # noqa: BLE001
        coupe = False
    lignes.append(f"  Volume    {niveau} %" + ("   (coupe)" if coupe else ""))
    try:
        lignes.append(f"  Sortie    {AudioUtilities.GetSpeakers().FriendlyName}")
    except Exception:  # noqa: BLE001
        pass
    lignes.append(f"  {power_plan()}")
    lignes.append("")
    lignes.append(audio_outputs())
    return "\n".join(lignes)
