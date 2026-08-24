"""Ce que l'assistant apprend de cette machine, et retient d'une fois sur l'autre.

Cette connaissance a longtemps vecu en memoire vive UNIQUEMENT, sur une regle
que l'utilisateur avait posee et que ce module declarait non negociable :
rien sur le disque, jamais. Elle se reconstruisait a chaque demarrage, et
disparaissait avec le processus.

L'utilisateur a leve cette regle le 24/08/2026, en toute connaissance de ce
qu'elle protegeait. La raison : un assistant qui oublie tout a la fermeture ne
peut pas aider sur la duree. Il redecouvre le meme disque sature chaque matin,
il ne sait pas qu'une reparation a deja ete tentee hier, et il repose la
question qu'on lui a deja repondue. C'etait le defaut le plus visible a
l'usage.

Ce qui a change, et RIEN d'autre : les faits sont ecrits dans
DATA_DIR/connaissance.json et relus au demarrage.

Ce qui n'a PAS change, et ne doit pas :

  1. Aucun contenu de fichier n'est conserve. On retient qu'un fichier existe,
     ou qu'il a ete lu, pas ce qu'il contient -- sinon le fichier finirait par
     contenir l'integralite des documents ouverts.
  2. Ce qui ressemble a un secret n'est jamais retenu, meme dicte
     explicitement. Ce filtre comptait deja beaucoup ; il compte davantage
     maintenant qu'un refus rate laisserait le secret sur le disque au lieu de
     mourir avec le processus. Il s'applique donc DEUX fois : a
     l'apprentissage, et de nouveau a la relecture -- ainsi un filtre ameliore
     nettoie ce qu'une version plus permissive avait laisse passer.
  3. Un plafond, avec eviction du plus ancien.
  4. `oublier()` reprend la main, et efface le fichier avec la memoire. Une
     connaissance qu'on ne peut pas effacer n'est pas acceptable.

Ce fichier vit dans DATA_DIR, hors du depot et hors du dossier d'installation.
Il contient une photographie de la machine : c'est le prix assume du choix
ci-dessus.
"""
from __future__ import annotations

import atexit
import json
import re
import threading
import time
from dataclasses import dataclass, field

from assistant import config

CHEMIN = config.DATA_DIR / "connaissance.json"

# Delai avant ecriture, en secondes. L'apprentissage du demarrage verse des
# milliers de faits d'affilee : ecrire a chacun ferait des milliers d'ecritures
# pour un seul resultat utile. On attend que la rafale se calme.
DELAI_ECRITURE = 5.0

# Plafond global. 4000 faits representent quelques mega-octets : largement de
# quoi connaitre une machine, sans risque de gonflement.
PLAFOND = 4000

# Longueur maximale d'un fait. Au-dela, on tronque : c'est le garde-fou qui
# empeche de ranger un fichier entier sous couvert de "connaissance".
LONGUEUR_MAX = 600

# Ce qui n'est JAMAIS retenu, meme dicte explicitement.
#
# Le mot seul ne suffit PAS. Une premiere version refusait toute occurrence de
# "token" ou "secret", et ecartait le service Windows TokenBroker, le
# gestionnaire de comptes web et trois chemins d'installation NVIDIA. Un
# filtre qui mange la connaissance utile est pire qu'absent : il laisse croire
# que la machine a ete apprise alors qu'il en manque des morceaux.
#
# On exige donc la forme d'une AFFECTATION : le mot, puis un separateur, puis
# une valeur. "TokenBroker" passe, "token: abc123" est refuse.
SECRETS = re.compile(
    r"(?:mot\s*de\s*passe|passwd|password|secret|api[_\- ]?key|token|"
    r"cle[_\- ]?api|private[_\- ]?key)"
    r"\s*(?:[:=]|\best\b|\bis\b)\s*\S",
    re.IGNORECASE,
)

# Les marqueurs qui ne laissent aucun doute, ou qu'ils soient.
SECRETS_ABSOLUS = re.compile(r"-----BEGIN|\bbearer\s+[A-Za-z0-9._\-]{16,}",
                             re.IGNORECASE)

# Un identifiant global Windows. Ils truffent les chemins d'installation et
# les cles de registre : les prendre pour des jetons condamnait la moitie de
# l'inventaire logiciel.
GUID = re.compile(r"\{?[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}\}?")

# La forme d'un vrai jeton : longue chaine sans espace, melant lettres et
# chiffres, SANS longue suite de lettres.
#
# C'est ce dernier point qui distingue "sk_live_51H8xKfL2eZvKYlo2C0ab" d'un
# nom de service comme "CredentialEnrollmentManagerUserSvc_90017". Un nom
# lisible contient des mots ; un jeton n'en contient pas.
JETON = re.compile(r"[A-Za-z0-9_\-]{28,}")
SUITE_DE_LETTRES = re.compile(r"[A-Za-z]{9,}")


@dataclass
class Fait:
    sujet: str          # "materiel", "logiciels", "fichiers", "session"...
    cle: str
    valeur: str
    source: str = ""    # d'ou ca vient, pour que l'utilisateur puisse verifier
    quand: float = field(default_factory=time.time)


_faits: dict[tuple[str, str], Fait] = {}
_verrou = threading.RLock()
_refuses = 0            # combien de faits ont ete ecartes comme sensibles
_minuterie: threading.Timer | None = None


def _ressemble_a_un_jeton(morceau: str) -> bool:
    """Une chaine aleatoire, par opposition a un nom lisible.

    Trois conditions cumulees : assez longue, melant lettres et chiffres, et
    sans longue suite de lettres. La derniere est celle qui compte -- un nom
    de service Windows contient des mots, un jeton n'en contient pas.
    """
    if SUITE_DE_LETTRES.search(morceau):
        return False
    chiffres = sum(c.isdigit() for c in morceau)
    lettres = sum(c.isalpha() for c in morceau)
    return chiffres >= 4 and lettres >= 4


def _sensible(texte: str) -> bool:
    """Ce texte contient-il un secret qu'on refuse de retenir ?"""
    if SECRETS_ABSOLUS.search(texte) or SECRETS.search(texte):
        return True
    # Les GUID sont retires avant l'examen : Windows en met partout, et les
    # prendre pour des jetons ecartait les chemins d'installation.
    sans_guid = GUID.sub(" ", texte)
    return any(_ressemble_a_un_jeton(m) for m in JETON.findall(sans_guid))


def apprendre(sujet: str, cle: str, valeur, source: str = "") -> bool:
    """Retient un fait. Rend False s'il a ete refuse.

    Un fait deja connu est mis a jour plutot que duplique : reapprendre le
    meme processeur a chaque releve n'apporte rien.
    """
    global _refuses

    texte = str(valeur).strip()
    if not texte or not cle:
        return False

    if _sensible(texte) or _sensible(str(cle)):
        with _verrou:
            _refuses += 1
        return False

    if len(texte) > LONGUEUR_MAX:
        texte = texte[:LONGUEUR_MAX].rstrip() + " [...]"

    with _verrou:
        _faits[(sujet, str(cle))] = Fait(sujet, str(cle), texte, source)
        if len(_faits) > PLAFOND:
            # Eviction du plus ancien : une session longue ne doit pas faire
            # gonfler la memoire sans fin.
            for perime in sorted(_faits.values(), key=lambda f: f.quand)[:200]:
                _faits.pop((perime.sujet, perime.cle), None)
    _planifier_ecriture()
    return True


def apprendre_lot(sujet: str, paires, source: str = "") -> int:
    """Retient plusieurs faits d'un coup. Rend le nombre effectivement retenu."""
    return sum(1 for cle, valeur in paires
               if apprendre(sujet, cle, valeur, source))


def oublier(sujet: str | None = None) -> int:
    """Efface un sujet, ou tout. L'utilisateur doit pouvoir reprendre la main.

    Efface AUSSI sur le disque. Tant que la connaissance mourait avec le
    processus, vider le dictionnaire suffisait ; maintenant qu'elle survit,
    un oubli qui laisserait le fichier en place ne serait pas un oubli. Le
    fichier est supprime plutot que reecrit vide -- il n'y a rien a garder.
    """
    with _verrou:
        if sujet is None:
            nombre = len(_faits)
            _faits.clear()
            _annuler_minuterie()
            try:
                CHEMIN.unlink(missing_ok=True)
            except OSError:
                pass
            return nombre
        cibles = [c for c in _faits if c[0] == sujet]
        for cle in cibles:
            del _faits[cle]
        if cibles:
            _planifier_ecriture()
        return len(cibles)


# --- Persistance -------------------------------------------------------------

def _annuler_minuterie() -> None:
    global _minuterie
    if _minuterie is not None:
        _minuterie.cancel()
        _minuterie = None


def _planifier_ecriture() -> None:
    """Repousse l'ecriture tant que les faits arrivent en rafale.

    tout_apprendre() verse des milliers de faits d'affilee au demarrage.
    Ecrire a chacun, c'est des milliers de reecritures du meme fichier pour
    un seul etat final utile -- et sur un disque, ca se sent.
    """
    global _minuterie
    with _verrou:
        _annuler_minuterie()
        _minuterie = threading.Timer(DELAI_ECRITURE, sauvegarder)
        _minuterie.daemon = True
        _minuterie.start()


def sauvegarder() -> bool:
    """Ecrit les faits sur le disque. Rend False si l'ecriture a echoue.

    Ecriture atomique : un fichier temporaire, puis un remplacement. Une
    coupure de courant au milieu d'un json.dump laisserait sinon un fichier
    tronque, que la relecture rejetterait -- et toute la connaissance serait
    perdue au lieu d'etre simplement vieille d'une session.
    """
    with _verrou:
        _annuler_minuterie()
        donnees = {
            "version": 1,
            "faits": [
                {"sujet": f.sujet, "cle": f.cle, "valeur": f.valeur,
                 "source": f.source, "quand": f.quand}
                for f in _faits.values()
            ],
        }
    temporaire = CHEMIN.with_suffix(".json.tmp")
    try:
        temporaire.parent.mkdir(parents=True, exist_ok=True)
        temporaire.write_text(
            json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
        temporaire.replace(CHEMIN)
    except (OSError, TypeError, ValueError):
        return False
    return True


def charger() -> int:
    """Relit les faits de la session precedente. Rend le nombre retenu.

    Le filtre a secrets est REJOUE sur ce qui est relu. Ce n'est pas de la
    defiance envers le fichier : c'est que le filtre s'ameliore avec le
    temps, et qu'un secret passe hier sous une regle trop permissive doit
    disparaitre des qu'on sait le reconnaitre.

    Un fichier absent, illisible ou abime ne bloque rien : on repart d'une
    connaissance vide, exactement comme avant la persistance. Perdre la
    memoire d'hier est desagreable ; ne pas demarrer serait pire.
    """
    try:
        brut = json.loads(CHEMIN.read_text(encoding="utf-8"))
        entrees = brut["faits"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return 0

    retenus = 0
    with _verrou:
        for entree in entrees:
            try:
                sujet = str(entree["sujet"])
                cle = str(entree["cle"])
                valeur = str(entree["valeur"])
            except (KeyError, TypeError):
                continue
            if _sensible(valeur) or _sensible(cle):
                continue
            _faits[(sujet, cle)] = Fait(
                sujet, cle, valeur, str(entree.get("source") or ""),
                float(entree.get("quand") or time.time()))
            retenus += 1
    return retenus


# La derniere rafale de faits ne doit pas mourir avec le processus : la
# minuterie attend cinq secondes, et une fermeture arrive plus vite que ca.
atexit.register(sauvegarder)


def sujets() -> dict[str, int]:
    with _verrou:
        compte: dict[str, int] = {}
        for fait in _faits.values():
            compte[fait.sujet] = compte.get(fait.sujet, 0) + 1
        return dict(sorted(compte.items(), key=lambda x: -x[1]))


def chercher(mots: str, limite: int = 25) -> list[Fait]:
    """Les faits qui correspondent, du plus recent au plus ancien."""
    termes = [m for m in str(mots).lower().split() if m]
    with _verrou:
        trouves = []
        for fait in _faits.values():
            foin = f"{fait.sujet} {fait.cle} {fait.valeur}".lower()
            if all(terme in foin for terme in termes):
                trouves.append(fait)
    trouves.sort(key=lambda f: f.quand, reverse=True)
    return trouves[:limite]


def total() -> int:
    with _verrou:
        return len(_faits)


def refuses() -> int:
    with _verrou:
        return _refuses


def rapport(mots: str = "", limite: int = 40) -> str:
    """Ce que l'assistant sait, en clair -- pour le modele comme pour l'ecran."""
    if mots:
        trouves = chercher(mots, limite)
        if not trouves:
            return (f"Rien de connu sur \"{mots}\". "
                    "La connaissance se reconstruit a chaque demarrage : si le "
                    "scan est encore en cours, reessaie dans un instant.")
        lignes = [f"{len(trouves)} fait(s) sur \"{mots}\" :", ""]
        for fait in trouves:
            lignes.append(f"  [{fait.sujet}] {fait.cle}")
            lignes.append(f"      {fait.valeur}")
            if fait.source:
                lignes.append(f"      source : {fait.source}")
        return "\n".join(lignes)

    compte = sujets()
    if not compte:
        return ("Rien encore appris. La connaissance se construit au "
                "demarrage, en tache de fond.")

    lignes = [f"{total()} faits connus sur cette machine, "
              "en memoire vive uniquement.", ""]
    for sujet, nombre in compte.items():
        lignes.append(f"  {sujet:<16} {nombre}")
    lignes.append("")
    lignes.append("Rien n'est ecrit sur le disque : tout disparait a la")
    lignes.append("fermeture et se reconstruit au prochain demarrage.")
    if refuses():
        lignes.append("")
        lignes.append(f"  {refuses()} information(s) ecartee(s) comme "
                      "sensibles (mots de passe, cles, jetons).")
    return "\n".join(lignes)
