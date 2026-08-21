"""Synthese vocale, via les voix Windows deja installees.

Pas de telechargement, pas de reseau : Windows sait deja parler francais.

Deux decisions valent explication.

1. On parle a SAPI directement, en COM, sans pyttsx3. La couche pyttsx3
   fonctionne pour UNE phrase puis rend la main en 0,1 s sans rien dire :
   sa boucle interne est consommee par le premier runAndWait(). Mesure sur
   cette machine : enonce 1 -> 3,8 s et du son ; enonces 2 et 3 -> 0,1 s et
   le silence. SpVoice.Speak, lui, se rappelle indefiniment.

2. On lit le magasin "OneCore" en plus du magasin SAPI classique. Windows y
   range des voix que SAPI n'enumere pas : sur cette machine, SAPI ne voyait
   qu'Hortense (feminine, seche) alors que Paul, voix masculine francaise,
   etait deja installe. Il s'agit d'une simple lecture d'une seconde
   categorie de jetons -- aucune ecriture dans le registre, aucun droit
   administrateur.

Un fil dedie possede l'objet vocal, car un objet COM appartient au fil qui
l'a cree : appele depuis un autre fil il ne parle pas. L'interface faisant
tout son travail dans des threads, la voix ne fonctionnait jamais en usage
reel avant cette correction.
"""
from __future__ import annotations

import queue
import re
import threading

from assistant import settings

# Ce qui se lit mal a voix haute : chemins, tableaux, barres de progression.
# Un chemin Windows va de la lettre de lecteur jusqu'a la fin de la ligne.
# On ne peut pas s'arreter au premier espace : "C:\Program Files\..." en
# contient, et on ne garderait que "C:\Program".
_PATH_RE = re.compile(r"[A-Za-z]:\\.*$")

# La categorie de jetons que SAPI n'ouvre pas de lui-meme.
ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"

# A defaut de choix explicite, on cherche dans cet ordre : une voix francaise
# masculine, puis n'importe quelle voix francaise, puis n'importe quoi.
# Julie passe avant Hortense : plus posee a l'oreille.
PREFERENCES = ["paul", "julie", "hortense"]

_demandes: queue.Queue = queue.Queue()
_fil: threading.Thread | None = None
_demarrage = threading.Lock()
_voix_choisie: str | None = None


def _jetons(voix) -> list:
    """Toutes les voix de la machine : magasin classique ET magasin OneCore.

    Les deux magasins se recoupent partiellement. On deduplique sur le nom,
    en gardant la premiere rencontree.
    """
    import comtypes.client

    trouves, vus = [], set()
    for source in ("classique", "onecore"):
        try:
            if source == "classique":
                jetons = list(voix.GetVoices())
            else:
                cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
                cat.SetId(ONECORE, False)
                jetons = list(cat.EnumerateTokens())
        except Exception:  # noqa: BLE001
            continue
        for jeton in jetons:
            try:
                nom = jeton.GetDescription()
            except Exception:  # noqa: BLE001
                continue
            if nom in vus:
                continue
            vus.add(nom)
            trouves.append((nom, jeton))
    return trouves


def _est_francaise(nom: str, jeton) -> bool:
    if "french" in nom.lower() or "francais" in nom.lower():
        return True
    try:
        # 40C est l'identifiant Windows du francais de France.
        return "40c" in str(jeton.GetAttribute("Language")).lower()
    except Exception:  # noqa: BLE001
        return False


def _est_masculine(nom: str, jeton) -> bool:
    try:
        return str(jeton.GetAttribute("Gender")).lower().startswith("m")
    except Exception:  # noqa: BLE001
        return any(p in nom.lower() for p in ("paul", "david", "mark"))


def _choisir(voix) -> str | None:
    """Retient la meilleure voix disponible et l'applique.

    Le reglage de l'utilisateur, s'il en a pose un, l'emporte sur tout.
    """
    disponibles = _jetons(voix)
    if not disponibles:
        return None

    demande = str(settings.get("voix", "") or "").strip().lower()
    if demande:
        for nom, jeton in disponibles:
            if demande in nom.lower():
                voix.Voice = jeton
                return nom

    francaises = [(n, j) for n, j in disponibles if _est_francaise(n, j)]
    masculines = [(n, j) for n, j in francaises if _est_masculine(n, j)]

    for lot in (masculines, francaises, disponibles):
        if not lot:
            continue
        # A l'interieur d'un lot, l'ordre de preference departage.
        def rang(paire):
            bas = paire[0].lower()
            for i, cle in enumerate(PREFERENCES):
                if cle in bas:
                    return i
            return len(PREFERENCES)

        nom, jeton = sorted(lot, key=rang)[0]
        voix.Voice = jeton
        return nom
    return None


def _boucle() -> None:
    """Possede l'objet vocal et parle, indefiniment.

    Chaque demande porte un evenement, pour que l'appelant puisse attendre la
    fin de l'enonce s'il en a besoin.
    """
    global _voix_choisie

    def vider(motif=None):
        """Ne jamais laisser un appelant bloque si la voix est indisponible."""
        while True:
            demande = _demandes.get()
            if demande is None:
                return
            demande[1].set()

    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        voix = comtypes.client.CreateObject("SAPI.SpVoice")
        _voix_choisie = _choisir(voix)
        try:
            voix.Rate = int(settings.get("voix_debit", 0) or 0)
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        vider()
        return

    while True:
        demande = _demandes.get()
        if demande is None:
            return
        texte, fini = demande
        try:
            voix.Speak(texte)
        except Exception:  # noqa: BLE001
            pass
        finally:
            fini.set()


def _assurer_fil() -> None:
    global _fil
    with _demarrage:
        if _fil is not None and _fil.is_alive():
            return
        _fil = threading.Thread(target=_boucle, name="voix", daemon=True)
        _fil.start()


def voices() -> list[str]:
    """Voix utilisables sur la machine, les deux magasins confondus."""
    try:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        voix = comtypes.client.CreateObject("SAPI.SpVoice")
        return [nom for nom, _jeton in _jetons(voix)]
    except Exception:  # noqa: BLE001
        return []


def choisir_voix(nom: str) -> None:
    """Impose une voix. Prend effet au prochain demarrage du fil de parole."""
    settings.set("voix", nom)
    arreter()


def speakable(text: str, max_chars: int = 400) -> str:
    """Reduit un texte d'ecran a quelque chose d'ecoutable.

    Les chemins complets sont remplaces par le seul nom de fichier : entendre
    "C deux points antislash Program Files antislash..." n'aide personne.
    """
    lignes = [
        _PATH_RE.sub(lambda m: m.group(0).rstrip().rsplit("\\", 1)[-1], ligne)
        for ligne in text.splitlines()
    ]
    texte = ". ".join(ligne.strip() for ligne in lignes if ligne.strip())
    texte = re.sub(r"[#*`|>_]+", " ", texte)
    texte = re.sub(r"\s+", " ", texte).strip()
    if len(texte) > max_chars:
        coupe = texte[:max_chars]
        texte = coupe.rsplit(".", 1)[0] + "." if "." in coupe else coupe
    return texte


def say(text: str, blocking: bool = False, timeout: float = 60.0) -> None:
    """Prononce un texte.

    L'appel est asynchrone par defaut : la demande part dans la file et
    l'appelant continue. Rien ne sert de bloquer un thread d'interface
    pendant que la machine parle.
    """
    texte = speakable(text)
    if not texte:
        return

    _assurer_fil()
    fini = threading.Event()
    _demandes.put((texte, fini))
    if blocking:
        fini.wait(timeout=timeout)


def voix_utilisee() -> str:
    """Nom de la voix retenue, une fois le fil demarre."""
    return _voix_choisie or "(pas encore determinee)"


def arreter() -> None:
    """Arrete le fil de parole, proprement."""
    global _fil
    if _fil is not None and _fil.is_alive():
        _demandes.put(None)
        _fil.join(timeout=5)
    _fil = None
