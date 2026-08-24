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
import time

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

    besoin = nom.strip().lower()

    # Le nom COMPLET l'emporte sur tout le reste.
    #
    # audio_outputs() affiche "Haut-parleurs (7.1 Surround Sound)". Quatre
    # sorties de cette machine commencent par "Haut-parleurs" : rendue telle
    # quelle, cette reponse etait refusee comme ambigue. Autrement dit,
    # l'outil ne savait pas relire ce qu'il venait d'ecrire, et un "remets le
    # son sur les enceintes" pouvait laisser la machine sur la mauvaise
    # sortie. Une egalite exacte ne peut jamais etre ambigue : elle passe
    # avant la recherche par morceau de nom.
    exactes = [a for a in appareils if a.FriendlyName.strip().lower() == besoin]
    if len(exactes) == 1:
        return _basculer(exactes[0])

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
        # On donne les noms COMPLETS, et on dit qu'ils sont utilisables tels
        # quels : une liste qu'on ne peut pas recopier ne fait pas avancer.
        noms = "\n".join(f"  - {a.FriendlyName}" for a in correspondances)
        return (f"Plusieurs sorties correspondent a \"{nom}\". "
                f"Reprends le nom complet :\n{noms}")

    return _basculer(correspondances[0])


def _basculer(cible) -> str:
    """Rend la sortie par defaut, et le confirme."""
    from pycaw.utils import AudioUtilities

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
        # Sans confirmation : la veille ne perd rien, tout est encore la au
        # reveil. Demander l'accord pour ca revenait a faire confirmer un
        # appui sur le bouton de veille du clavier.
        routine=True,
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
        # Sans confirmation : le DELAI est la confirmation. L'utilisateur voit
        # le compte a rebours et dispose de "annule l'arret" pendant tout ce
        # temps -- une fenetre en plus ne protege de rien.
        routine=True,
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


# --- Lecture en cours : musique, films, videos -------------------------------
#
# On envoie les touches multimedia du clavier, pas des commandes a une
# application precise. C'est ce qui fait qu'une seule implementation pilote
# Spotify, VLC, YouTube dans le navigateur, Netflix et le lecteur Windows :
# toutes ecoutent ces touches. Cibler une application par son nom aurait
# demande un pilote par application, et aurait casse a chaque mise a jour.

_TOUCHES_MEDIA = {
    "play": (0xB3, "Lecture / pause"),
    "pause": (0xB3, "Lecture / pause"),
    "suivant": (0xB0, "Piste suivante"),
    "precedent": (0xB1, "Piste precedente"),
    "stop": (0xB2, "Arret de la lecture"),
}

_SYNONYMES_MEDIA = {
    "lecture": "play", "lire": "play", "jouer": "play", "reprendre": "play",
    "pause": "pause", "arreter": "stop", "arret": "stop",
    "suivante": "suivant", "suivant": "suivant", "next": "suivant",
    "avance": "suivant", "changer": "suivant", "passer": "suivant",
    "precedente": "precedent", "precedent": "precedent", "retour": "precedent",
    "back": "precedent", "recommencer": "precedent",
}

KEYEVENTF_KEYUP = 0x0002


def _frapper(code: int) -> None:
    import ctypes

    ctypes.windll.user32.keybd_event(code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)


def media(action: str) -> str:
    """Pilote la lecture en cours, quelle que soit l'application.

    Aucune confirmation : mettre en pause n'est pas une modification de la
    machine, et demander l'accord pour chaque "pause" serait insupportable.
    """
    demande = (action or "").strip().lower()
    cle = _SYNONYMES_MEDIA.get(demande, demande)
    if cle not in _TOUCHES_MEDIA:
        return ("Actions possibles : play, pause, suivant, precedent, stop.")

    code, libelle = _TOUCHES_MEDIA[cle]
    try:
        _frapper(code)
    except Exception as exc:  # noqa: BLE001
        return f"Touche multimedia impossible : {type(exc).__name__}: {exc}"
    return (f"{libelle}. Si rien ne bouge, c'est qu'aucune application ne "
            "lit quoi que ce soit.")


# --- Ecrire au clavier -------------------------------------------------------
#
# Le texte est injecte en Unicode, caractere par caractere, et non par des
# codes de touches. Un code de touche depend de la disposition du clavier :
# la meme frappe donne "a" en AZERTY et "q" en QWERTY, et tous les accents
# seraient perdus.

_cible_precedente = 0


def memoriser_cible(hwnd: int) -> None:
    """Retient la fenetre qui avait le focus avant la notre.

    Sans cela, "tape bonjour" ecrirait dans l'assistant lui-meme : au moment
    ou l'utilisateur clique ou parle, c'est notre fenetre qui est au premier
    plan, pas celle ou il veut ecrire.
    """
    global _cible_precedente
    if hwnd:
        _cible_precedente = int(hwnd)


def _rendre_le_focus() -> bool:
    if not _cible_precedente:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if not user32.IsWindow(_cible_precedente):
            return False
        user32.SetForegroundWindow(_cible_precedente)
        time.sleep(0.15)      # laisser Windows effectuer la bascule
        return True
    except Exception:  # noqa: BLE001
        return False


def taper(texte: str, ask=None) -> str:
    """Ecrit un texte dans la fenetre active, comme au clavier.

    **Sans demander confirmation.** Demander l'accord pour un texte que
    l'utilisateur vient de dicter ou d'ecrire lui-meme n'apporte rien : il
    connait deja le contenu, et une fenetre de plus entre la demande et la
    frappe rend la fonction inutilisable pour ce a quoi elle sert -- dicter
    dans un logiciel qui ne connait pas la dictee.

    L'action reste JOURNALISEE : on peut toujours savoir ce qui a ete tape et
    quand. C'est la trace qui compte ici, pas la barriere.
    """
    texte = texte or ""
    if not texte:
        return "Rien a taper."

    action = safety.Action(
        kind="clavier",
        summary=f"Taper {len(texte)} caractere(s) dans la fenetre active",
        # Prefixe volontaire. `targets` est le champ compare aux chemins
        # proteges : un texte commencant par "C:\\Windows" aurait ete refuse
        # comme si on modifiait le dossier systeme, alors qu'on ne fait que
        # l'ecrire. Le prefixe le sort de l'espace des chemins.
        targets=[f"texte: {texte[:200]}"],
        reversible=False,
        details="Le texte part dans l'application au premier plan.",
    )
    try:
        # La demande de l'utilisateur EST l'accord.
        safety.guard(action, ask=ask or (lambda _texte: True))
    except safety.Refused as exc:
        return str(exc)

    rendu = _rendre_le_focus()
    try:
        _injecter(texte)
    except Exception as exc:  # noqa: BLE001
        return f"Frappe impossible : {type(exc).__name__}: {exc}"

    ou = "dans la fenetre precedente" if rendu else "dans la fenetre active"
    return f"{len(texte)} caractere(s) tapes {ou}."


# Les touches qu'une combinaison peut nommer.
#
# Liste FERMEE, et c'est le point important : une macro declenchee depuis le
# telephone ne doit pouvoir envoyer que ce qui figure ici. Accepter un code de
# touche arbitraire venu du reseau reviendrait a offrir un clavier complet a
# qui trouve le jeton du serveur.
TOUCHES = {
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "maj": 0x10,
    "win": 0x5B, "windows": 0x5B, "tab": 0x09, "entree": 0x0D,
    "enter": 0x0D, "echap": 0x1B, "esc": 0x1B, "espace": 0x20,
    "suppr": 0x2E, "delete": 0x2E, "retour": 0x08, "backspace": 0x08,
    "haut": 0x26, "bas": 0x28, "gauche": 0x25, "droite": 0x27,
    "debut": 0x24, "fin": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "impr": 0x2C, "inser": 0x2D,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
    **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"},
    **{c: ord(c) for c in "0123456789"},
}


def raccourci(combinaison: str, ask=None) -> str:
    """Envoie une combinaison de touches, par exemple "ctrl+s" ou "alt+tab".

    Les modificateurs sont enfonces dans l'ordre donne, la derniere touche est
    frappee, puis tout est relache DANS L'ORDRE INVERSE. Relacher dans le
    desordre laisse Windows croire qu'une touche est encore enfoncee : la
    machine se met a tout selectionner ou a ouvrir des menus, et il faut
    appuyer soi-meme sur la touche fantome pour s'en sortir.
    """
    import ctypes

    noms = [m.strip().lower() for m in str(combinaison).split("+") if m.strip()]
    if not noms:
        return "Aucune touche donnee."

    inconnues = [n for n in noms if n not in TOUCHES]
    if inconnues:
        return (f"Touche inconnue : {', '.join(inconnues)}. "
                "Je n'envoie que des touches nommees, jamais un code brut.")

    action = safety.Action(
        kind="clavier",
        summary=f"Envoyer la combinaison {'+'.join(noms)}",
        targets=[f"touches: {'+'.join(noms)}"],
        reversible=False,
        details="La combinaison part dans l'application au premier plan.",
    )
    try:
        safety.guard(action, ask=ask or (lambda _texte: True))
    except safety.Refused as exc:
        return str(exc)

    _rendre_le_focus()
    user32 = ctypes.windll.user32
    codes = [TOUCHES[n] for n in noms]
    try:
        for code in codes:
            user32.keybd_event(code, 0, 0, 0)
            time.sleep(0.01)
        for code in reversed(codes):
            user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)
    except Exception as exc:  # noqa: BLE001
        return f"Combinaison impossible : {type(exc).__name__}: {exc}"
    return f"Combinaison {'+'.join(noms)} envoyee."


# --- Souris ------------------------------------------------------------------
#
# Le clic change la nature de ce que l'assistant peut faire, et il faut le dire
# ici plutot que le decouvrir plus tard. Jusqu'a present, la pire chose qu'une
# erreur pouvait produire etait du texte de travers. Un clic mal place appuie
# sur "Supprimer", "Formater" ou "Accepter" dans une fenetre que personne n'a
# comprise, et cela ne se defait pas.
#
# D'ou la regle : ces fonctions executent des COORDONNEES, elles ne cherchent
# rien a l'ecran. Le modele ne decide jamais ou cliquer -- il ne voit l'ecran
# qu'a travers un modele de vision qui se trompe encore. Ce qui les appelle,
# c'est une macro que l'utilisateur a enregistree lui-meme, en sachant ou.

BOUTONS = {
    "gauche": (0x0002, 0x0004),
    "droit": (0x0008, 0x0010),
    "milieu": (0x0020, 0x0040),
}


def position_souris() -> tuple[int, int]:
    """Ou est le curseur, pour enregistrer une macro sans deviner."""
    import ctypes
    from ctypes import wintypes

    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def cliquer(x=None, y=None, bouton: str = "gauche", double: bool = False,
            ask=None) -> str:
    """Clique a une position donnee, ou la ou est deja le curseur.

    Sans coordonnees, on clique sur place : c'est ce qu'on veut dans une macro
    qui suit un deplacement, et cela evite de deplacer le curseur sous la main
    de l'utilisateur pour rien.
    """
    import ctypes

    if bouton not in BOUTONS:
        return (f"Bouton inconnu : \"{bouton}\". "
                f"Choisis parmi {', '.join(BOUTONS)}.")

    ou = "sur place"
    if x is not None and y is not None:
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            return "Coordonnees illisibles."
        ou = f"en {x},{y}"

    action = safety.Action(
        kind="souris",
        summary=f"Clic {bouton}{' double' if double else ''} {ou}",
        targets=[f"souris: {ou}"],
        reversible=False,
        details="Le clic part dans la fenetre au premier plan. Un clic ne se "
                "defait pas : ce qu'il declenche non plus.",
    )
    try:
        safety.guard(action, ask=ask or (lambda _texte: True))
    except safety.Refused as exc:
        return str(exc)

    user32 = ctypes.windll.user32
    enfonce, relache = BOUTONS[bouton]
    try:
        if x is not None and y is not None:
            user32.SetCursorPos(x, y)
            time.sleep(0.03)
        for _ in range(2 if double else 1):
            user32.mouse_event(enfonce, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(relache, 0, 0, 0, 0)
            time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        return f"Clic impossible : {type(exc).__name__}: {exc}"
    return f"Clic {bouton}{' double' if double else ''} {ou}."


def deplacer_souris(x, y) -> str:
    """Deplace le curseur, sans cliquer."""
    import ctypes

    try:
        x, y = int(x), int(y)
    except (TypeError, ValueError):
        return "Coordonnees illisibles."
    ctypes.windll.user32.SetCursorPos(x, y)
    return f"Curseur en {x},{y}."


def molette(crans: int) -> str:
    """Fait tourner la molette. Positif vers le haut, negatif vers le bas."""
    import ctypes

    try:
        crans = int(crans)
    except (TypeError, ValueError):
        return "Nombre de crans illisible."
    ROULETTE = 0x0800
    for _ in range(abs(crans)):
        ctypes.windll.user32.mouse_event(
            ROULETTE, 0, 0, 120 if crans > 0 else -120, 0)
        time.sleep(0.02)
    return f"Molette : {crans} cran(s)."


def _injecter(texte: str) -> None:
    """Envoie le texte en Unicode via SendInput."""
    import ctypes
    from ctypes import wintypes

    class ENTREE_CLAVIER(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _UNION(ctypes.Union):
        _fields_ = [("ki", ENTREE_CLAVIER)]

    class ENTREE(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

    ENTREE_TYPE_CLAVIER = 1
    UNICODE = 0x0004

    user32 = ctypes.windll.user32
    for caractere in texte:
        for drapeaux in (UNICODE, UNICODE | KEYEVENTF_KEYUP):
            entree = ENTREE(
                type=ENTREE_TYPE_CLAVIER,
                u=_UNION(ki=ENTREE_CLAVIER(
                    wVk=0, wScan=ord(caractere), dwFlags=drapeaux,
                    time=0, dwExtraInfo=None)),
            )
            user32.SendInput(1, ctypes.byref(entree), ctypes.sizeof(entree))
        # Une rafale sans pause fait perdre des caracteres aux applications
        # qui traitent leur file d'evenements lentement.
        time.sleep(0.004)


# --- Ouvrir le bon reglage Windows -------------------------------------------
#
# Chaque entree du pupitre pointe vers l'endroit EXACT du systeme, pas vers la
# page d'accueil des parametres. "Ou est-ce qu'on regle ca ?" est la question
# qui fait perdre le plus de temps dans Windows.

REGLAGES = {
    "son": ("ms-settings:sound", "Parametres du son"),
    "peripheriques_audio": ("ms-settings:sound-devices",
                            "Peripheriques audio"),
    "melangeur": ("ms-settings:apps-volume",
                  "Volume par application"),
    "alimentation": ("ms-settings:powersleep",
                     "Alimentation et mise en veille"),
    "profils_alimentation": ("powercfg.cpl", "Profils d'alimentation"),
    "affichage": ("ms-settings:display", "Affichage"),
    "demarrage": ("ms-settings:startupapps", "Applications au demarrage"),
    "applications": ("ms-settings:appsfeatures",
                     "Applications installees"),
    "stockage": ("ms-settings:storagesense", "Stockage"),
    "bluetooth": ("ms-settings:bluetooth", "Bluetooth et appareils"),
    "reseau": ("ms-settings:network-status", "Reseau"),
    "confidentialite_micro": ("ms-settings:privacy-microphone",
                              "Acces au microphone"),
    "notifications": ("ms-settings:notifications", "Notifications"),
    "gestionnaire": ("taskmgr.exe", "Gestionnaire des taches"),
    "peripheriques": ("devmgmt.msc", "Gestionnaire de peripheriques"),
    "disques": ("cleanmgr.exe", "Nettoyage de disque"),
}


def ouvrir_reglage(cle: str) -> str:
    """Ouvre la page de reglages Windows correspondante."""
    entree = REGLAGES.get((cle or "").strip().lower())
    if entree is None:
        return ("Reglages connus : " + ", ".join(sorted(REGLAGES)))

    cible, libelle = entree
    try:
        # explorer.exe sait ouvrir aussi bien une URI ms-settings: qu'un .cpl
        # ou un .msc ; os.startfile echoue sur certaines de ces formes.
        subprocess.Popen(["explorer.exe", cible],
                         creationflags=CREATE_NO_WINDOW)
    except OSError as exc:
        return f"Ouverture impossible : {exc}"
    return f"{libelle} ouvert."


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
