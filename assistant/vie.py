"""Journal de vie de l'application : ce qui l'ouvre, et ce qui la ferme.

Ecrit parce que l'assistant a disparu deux fois dans la meme soiree sans
laisser la moindre trace : pas de `erreurs.log`, pas d'evenement Windows, pas
une ligne dans son journal. Une fenetre qui se ferme toute seule est bien plus
difficile a reparer qu'un programme qui plante bruyamment -- il n'y a rien a
lire.

Trois morts possibles, et une seule etait deja visible :

  1. une exception Python -- deja attrapee par AssistantLocal.py ;
  2. un plantage NATIF, dans une bibliotheque C (Tk, CUDA, le pilote audio).
     Python n'en sait rien et ne peut rien ecrire : seul faulthandler, arme
     avant le drame, laisse une trace ;
  3. une fin SANS drame : quelqu'un ferme la fenetre, un `taskkill` passe par
     la, Windows arrete la session. Rien a attraper de l'interieur.

Le cas 3 est le plus sournois, et c'est celui qu'on ne pouvait pas distinguer.
On l'obtient en creux : chaque demarrage ecrit une ligne, chaque arret propre
en ecrit une seconde. Au demarrage suivant, une ligne d'ouverture SANS ligne
de fermeture designe une mort brutale -- et l'assistant le dit au lieu de
faire comme si de rien n'etait.
"""
from __future__ import annotations

import atexit
import faulthandler
import json
import os
import time
from datetime import datetime

from assistant import config

# Deux fichiers, deux natures. Le premier est une liste d'evenements qu'on
# relit ; le second recoit les traces de plantage natif, qui ne sont pas du
# JSON et arrivent parfois au milieu d'une ecriture.
SESSIONS = config.LOG_DIR / "sessions.jsonl"
PLANTAGES = config.LOG_DIR / "plantages.log"

# Au-dela, la ligne d'ouverture appartient a une session si ancienne que la
# signaler n'apprendrait plus rien.
OUBLI = 7 * 24 * 3600

_arret_note = False
_flux_plantages = None


def _ecrire(evenement: dict) -> None:
    """Ajoute une ligne. Ne leve jamais : un journal ne doit rien casser."""
    try:
        SESSIONS.parent.mkdir(parents=True, exist_ok=True)
        with SESSIONS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(evenement, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _lire() -> list[dict]:
    try:
        lignes = SESSIONS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    evenements = []
    for ligne in lignes[-400:]:
        try:
            evenements.append(json.loads(ligne))
        except json.JSONDecodeError:
            continue
    return evenements


def sessions_mortes_sans_un_mot() -> list[dict]:
    """Les demarrages qui n'ont jamais eu d'arret correspondant."""
    ouvertures: dict[int, dict] = {}
    for evenement in _lire():
        pid = evenement.get("pid")
        if not isinstance(pid, int):
            continue
        if evenement.get("evt") == "start":
            ouvertures[pid] = evenement
        elif evenement.get("evt") == "exit":
            ouvertures.pop(pid, None)

    limite = time.time() - OUBLI
    # Le processus courant n'est evidemment pas encore ferme.
    ouvertures.pop(os.getpid(), None)
    return [o for o in ouvertures.values()
            if o.get("t", 0) >= limite and not _tourne_toujours(o)]


def _tourne_toujours(ouverture: dict) -> bool:
    """Ce processus est-il encore en vie ?

    Une session ouverte sans fermeture n'est pas forcement morte : elle peut
    simplement etre en cours. Sans ce filtre, une seconde instance accusait
    la premiere d'avoir plante alors qu'elle tournait tres bien a cote.

    Les numeros de processus sont recycles par Windows : trouver un processus
    portant ce numero ne suffit pas. On compare donc sa date de naissance a
    celle qu'on avait notee -- un inconnu qui a herite du numero est ne bien
    plus tard, et ne trompe personne.
    """
    try:
        import psutil

        proc = psutil.Process(int(ouverture.get("pid", -1)))
        return abs(proc.create_time() - float(ouverture.get("t", 0))) < 120
    except Exception:  # noqa: BLE001 - psutil leve des types varies
        return False


def _trace_de_plantage(pid) -> bool:
    """Le fichier de plantages contient-il autre chose que l'en-tete de session ?

    La date du fichier ne prouve RIEN : demarrer() y ecrit une ligne
    d'en-tete a chaque lancement, donc il est toujours "recent". Une premiere
    version s'y fiait et annoncait un plantage a chaque fermeture normale --
    exactement le genre d'affirmation qui fait perdre du temps.

    On cherche donc la section de CE processus, et on regarde si quelque
    chose a ete ecrit apres son en-tete.
    """
    if pid is None or not PLANTAGES.exists():
        return False
    try:
        texte = PLANTAGES.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    marqueur = f"pid {pid} ==="
    position = texte.rfind(marqueur)
    if position < 0:
        return False
    apres = texte[position + len(marqueur):]
    # Ce qui suit jusqu'a la session suivante, s'il y en a une.
    fin = apres.find("\n=== session ")
    if fin >= 0:
        apres = apres[:fin]
    return bool(apres.strip())


def rapport_de_reprise() -> str:
    """Ce qu'il faut dire a l'utilisateur au demarrage. Vide si tout va bien."""
    mortes = sessions_mortes_sans_un_mot()
    if not mortes:
        return ""

    derniere = mortes[-1]
    quand = datetime.fromtimestamp(derniere.get("t", 0)).strftime("%d/%m a %H:%M")
    debut = (f"La session precedente s'est arretee sans passer par la "
             f"fermeture normale ({quand}, lancee depuis "
             f"{derniere.get('origine', '?')}).")

    if _trace_de_plantage(derniere.get("pid")):
        return (debut + f"\n  Une trace de plantage a ete ecrite : "
                        f"{PLANTAGES}")

    suite = ("\n  Aucune trace de plantage : la fenetre a donc ete fermee, ou "
             "le processus arrete de l'exterieur.")
    if len(mortes) > 1:
        suite += f"\n  C'est arrive {len(mortes)} fois cette semaine."
    return debut + suite


def demarrer(origine: str) -> str:
    """Arme les filets, note l'ouverture, et rend le rapport sur la precedente.

    A appeler UNE fois, le plus tot possible : un plantage natif survenu avant
    faulthandler.enable() ne laisse toujours rien.
    """
    global _flux_plantages

    # Le rapport se calcule AVANT d'inscrire la session courante, sinon elle
    # se compterait elle-meme comme une ouverture sans fermeture.
    rapport = rapport_de_reprise()

    try:
        PLANTAGES.parent.mkdir(parents=True, exist_ok=True)
        _flux_plantages = PLANTAGES.open("a", encoding="utf-8", buffering=1)
        _flux_plantages.write(
            f"\n=== session {datetime.now().isoformat(timespec='seconds')} "
            f"pid {os.getpid()} ===\n")
        # all_threads : l'interface tourne sur un fil, la voix et l'index sur
        # d'autres. Une pile unique designerait rarement le coupable.
        faulthandler.enable(file=_flux_plantages, all_threads=True)
    except (OSError, ValueError):
        pass

    _ecrire({"evt": "start", "pid": os.getpid(), "t": time.time(),
             "at": datetime.now().isoformat(timespec="seconds"),
             "origine": origine})
    atexit.register(arret, "fin normale")
    return rapport


def arret(raison: str = "") -> None:
    """Note une fermeture propre. Idempotent : atexit peut doubler l'appel."""
    global _arret_note
    if _arret_note:
        return
    _arret_note = True
    _ecrire({"evt": "exit", "pid": os.getpid(), "t": time.time(),
             "at": datetime.now().isoformat(timespec="seconds"),
             "raison": raison})


def arret_de(pid: int, raison: str) -> None:
    """Note la fermeture d'un AUTRE processus, qu'on s'apprete a tuer.

    Un processus tue de l'exterieur ne peut rien ecrire pour lui-meme. Celui
    qui le tue, lui, sait tres bien ce qu'il fait : c'est a lui de le dire,
    sinon la mort passe pour un plantage.
    """
    _ecrire({"evt": "exit", "pid": int(pid), "t": time.time(),
             "at": datetime.now().isoformat(timespec="seconds"),
             "raison": raison})


def noter_exception(texte: str) -> None:
    """Consigne une exception que personne n'aurait vue autrement.

    Tkinter attrape les erreurs de ses callbacks et les imprime sur la sortie
    d'erreur. Dans une application en mode fenetre, cette sortie n'existe pas :
    le bouton ne fait rien, et il n'y a rien a lire nulle part.
    """
    try:
        PLANTAGES.parent.mkdir(parents=True, exist_ok=True)
        with PLANTAGES.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- exception {datetime.now().isoformat(timespec='seconds')} "
                     f"---\n{texte}\n")
    except OSError:
        pass
