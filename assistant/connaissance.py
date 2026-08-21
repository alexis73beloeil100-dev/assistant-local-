"""Ce que l'assistant apprend de cette machine, en memoire vive uniquement.

La regle, posee par l'utilisateur et non negociable : **rien n'est ecrit sur
le disque**. Cette connaissance vit dans le processus, et disparait avec lui.
A chaque demarrage, elle se reconstruit toute seule.

C'est la meme decision que pour l'index des fichiers (config.PERSIST_INDEX =
False), etendue a tout le reste : materiel, logiciels installes, services,
taches planifiees, ce qui a ete lu pendant la session. Le cout est une
reconstruction au lancement ; le benefice est qu'aucune photographie de la
machine ne subsiste apres la fermeture.

Quatre limites, appliquees ici et pas ailleurs :

  1. Rien sur le disque, jamais. Aucune fonction de ce module n'ouvre un
     fichier en ecriture.
  2. Aucun contenu de fichier n'est conserve. On retient qu'un fichier existe,
     ou qu'il a ete lu, pas ce qu'il contient -- sinon la memoire vive
     finirait par contenir l'integralite des documents ouverts.
  3. Ce qui ressemble a un secret n'est jamais retenu, meme si l'utilisateur
     le dicte. Un mot de passe range en memoire est un mot de passe qui
     ressortira un jour dans une reponse.
  4. Un plafond, avec eviction du plus ancien. Sans lui, une session longue
     ferait gonfler la memoire sans limite.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

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
    return True


def apprendre_lot(sujet: str, paires, source: str = "") -> int:
    """Retient plusieurs faits d'un coup. Rend le nombre effectivement retenu."""
    return sum(1 for cle, valeur in paires
               if apprendre(sujet, cle, valeur, source))


def oublier(sujet: str | None = None) -> int:
    """Efface un sujet, ou tout. L'utilisateur doit pouvoir reprendre la main."""
    with _verrou:
        if sujet is None:
            nombre = len(_faits)
            _faits.clear()
            return nombre
        cibles = [c for c in _faits if c[0] == sujet]
        for cle in cibles:
            del _faits[cle]
        return len(cibles)


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
