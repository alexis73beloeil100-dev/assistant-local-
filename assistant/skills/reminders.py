"""Minuteurs, rappels, et surveillance avec alerte.

Trois choses proches mais distinctes :

  - un MINUTEUR se declenche apres un delai ("dans 20 minutes") ;
  - un RAPPEL se declenche a une heure ("a 21h30") ;
  - une VEILLE surveille une condition et se declenche quand elle devient
    vraie ("quand le telechargement est fini", "si le GPU depasse 80 degres").

Tout vit en memoire et disparait a la fermeture, comme le reste. Un rappel
qui survivrait a l'application supposerait de l'ecrire sur le disque.
"""
from __future__ import annotations

import itertools
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

_compteur = itertools.count(1)
_lock = threading.Lock()
_alertes: dict[int, "Alerte"] = {}

# Intervalle de verification des veilles. Une seconde suffit et ne coute rien
# mesurable ; verifier plus souvent ferait travailler le disque pour rien.
TICK = 1.0


@dataclass
class Alerte:
    numero: int
    genre: str            # "minuteur", "rappel", "veille"
    message: str
    echeance: float | None = None      # horodatage pour minuteur et rappel
    condition: Callable[[], tuple[bool, str]] | None = None
    cree: float = field(default_factory=time.time)
    declenchee: bool = False
    detail: str = ""

    def reste(self) -> float:
        if self.echeance is None:
            return 0.0
        return max(self.echeance - time.time(), 0.0)

    def describe(self) -> str:
        if self.genre == "veille":
            return f"[{self.numero}] veille : {self.message}"
        moment = datetime.fromtimestamp(self.echeance).strftime("%H:%M:%S")
        restant = self.reste()
        if restant > 3600:
            duree = f"{restant / 3600:.1f} h"
        elif restant > 60:
            duree = f"{restant / 60:.0f} min"
        else:
            duree = f"{restant:.0f} s"
        return f"[{self.numero}] {moment} (dans {duree}) : {self.message}"


# --- Analyse des durees -----------------------------------------------------

DUREE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(secondes?|sec|s|minutes?|min|m|heures?|h)\b",
    re.IGNORECASE,
)

MOTS_NOMBRES = {
    "une": 1, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10, "quinze": 15,
    "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
    "soixante": 60, "demi": 0.5,
}


def parse_duree(texte: str) -> float | None:
    """Convertit "20 minutes", "1h30", "trente secondes" en secondes."""
    if not texte:
        return None

    normalise = texte.lower().replace(",", ".")
    for mot, valeur in MOTS_NOMBRES.items():
        normalise = re.sub(rf"\b{mot}\b", str(valeur), normalise)

    # Forme compacte "1h30"
    compact = re.search(r"\b(\d+)\s*h\s*(\d{1,2})\b", normalise)
    if compact:
        return int(compact.group(1)) * 3600 + int(compact.group(2)) * 60

    total = 0.0
    trouve = False
    for valeur, unite in DUREE_RE.findall(normalise):
        nombre = float(valeur)
        unite = unite.lower()
        if unite.startswith("h"):
            total += nombre * 3600
        elif unite.startswith("m") and unite != "s":
            total += nombre * 60
        else:
            total += nombre
        trouve = True
    return total if trouve else None


def parse_heure(texte: str) -> float | None:
    """Convertit "21h30", "9:15" en horodatage du prochain passage."""
    trouve = re.search(r"\b(\d{1,2})\s*[h:]\s*(\d{2})?\b", texte.lower())
    if not trouve:
        return None
    heure = int(trouve.group(1))
    minute = int(trouve.group(2) or 0)
    if heure > 23 or minute > 59:
        return None

    maintenant = datetime.now()
    cible = maintenant.replace(hour=heure, minute=minute, second=0,
                               microsecond=0)
    if cible <= maintenant:
        cible += timedelta(days=1)
    return cible.timestamp()


# --- Conditions surveillees -------------------------------------------------

def condition_gpu(seuil: float) -> Callable[[], tuple[bool, str]]:
    def verifier() -> tuple[bool, str]:
        from assistant.skills import system

        info = system.gpu_info()
        if not info:
            return False, ""
        temp = info.get("temp_c", 0)
        if temp >= seuil:
            return True, f"GPU a {temp:.0f} C (seuil {seuil:.0f})"
        return False, ""

    return verifier


def condition_cpu(seuil: float) -> Callable[[], tuple[bool, str]]:
    def verifier() -> tuple[bool, str]:
        import psutil

        charge = psutil.cpu_percent(interval=None)
        if charge >= seuil:
            return True, f"CPU a {charge:.0f} % (seuil {seuil:.0f})"
        return False, ""

    return verifier


def condition_processus_termine(nom: str) -> Callable[[], tuple[bool, str]]:
    def verifier() -> tuple[bool, str]:
        import psutil

        for proc in psutil.process_iter(["name"]):
            try:
                if nom.lower() in (proc.info.get("name") or "").lower():
                    return False, ""
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return True, f"{nom} n'est plus en cours d'execution"

    return verifier


def condition_disque_libre(lettre: str, go: float) -> Callable[[], tuple[bool, str]]:
    def verifier() -> tuple[bool, str]:
        import psutil

        try:
            usage = psutil.disk_usage(f"{lettre.rstrip(':')}:\\")
        except OSError:
            return False, ""
        libre = usage.free / 1024**3
        if libre <= go:
            return True, f"{lettre}: n'a plus que {libre:.0f} Go libres"
        return False, ""

    return verifier


def condition_fichier(chemin: str) -> Callable[[], tuple[bool, str]]:
    """Vrai quand le fichier existe ET a cesse de grossir.

    Un telechargement en cours existe deja : tester la seule presence
    declencherait l'alerte des la premiere seconde.
    """
    import os

    etat = {"taille": -1, "stable": 0}

    def verifier() -> tuple[bool, str]:
        if not os.path.exists(chemin):
            etat["taille"] = -1
            etat["stable"] = 0
            return False, ""
        try:
            taille = os.path.getsize(chemin)
        except OSError:
            return False, ""
        if taille == etat["taille"] and taille > 0:
            etat["stable"] += 1
            if etat["stable"] >= 3:
                from assistant.util import human_size

                return True, f"{chemin} termine ({human_size(taille)})"
        else:
            etat["stable"] = 0
        etat["taille"] = taille
        return False, ""

    return verifier


# --- Gestion ----------------------------------------------------------------

_notifier: Callable[[Alerte], None] | None = None
_boucle: threading.Thread | None = None
_arret = threading.Event()


def set_notifier(fn: Callable[[Alerte], None]) -> None:
    """Definit comment prevenir l'utilisateur (fenetre, voix...)."""
    global _notifier
    _notifier = fn


def _boucle_surveillance() -> None:
    while not _arret.is_set():
        time.sleep(TICK)
        maintenant = time.time()
        a_declencher = []

        with _lock:
            for alerte in list(_alertes.values()):
                if alerte.declenchee:
                    continue
                if alerte.echeance is not None and maintenant >= alerte.echeance:
                    alerte.declenchee = True
                    a_declencher.append(alerte)
                elif alerte.condition is not None:
                    try:
                        atteint, detail = alerte.condition()
                    except Exception:  # noqa: BLE001
                        continue
                    if atteint:
                        alerte.declenchee = True
                        alerte.detail = detail
                        a_declencher.append(alerte)

        for alerte in a_declencher:
            if _notifier:
                try:
                    _notifier(alerte)
                except Exception:  # noqa: BLE001
                    pass


def _demarrer_boucle() -> None:
    global _boucle
    if _boucle is not None and _boucle.is_alive():
        return
    _arret.clear()
    _boucle = threading.Thread(target=_boucle_surveillance,
                               name="alertes", daemon=True)
    _boucle.start()


def _ajouter(alerte: Alerte) -> Alerte:
    with _lock:
        _alertes[alerte.numero] = alerte
    _demarrer_boucle()
    return alerte


def minuteur(duree: str, message: str = "") -> str:
    """Cree un minuteur : "dans 20 minutes"."""
    secondes = parse_duree(duree)
    if secondes is None or secondes <= 0:
        return ("Duree incomprise. Exemples : \"20 minutes\", \"1h30\", "
                "\"30 secondes\".")
    if secondes > 24 * 3600:
        return "Au-dela de 24 heures, un minuteur n'a plus de sens."

    alerte = _ajouter(Alerte(
        numero=next(_compteur),
        genre="minuteur",
        message=message or "Minuteur termine",
        echeance=time.time() + secondes,
    ))
    return f"Minuteur regle. {alerte.describe()}"


def rappel(heure: str, message: str = "") -> str:
    """Cree un rappel a une heure precise : "a 21h30"."""
    horodatage = parse_heure(heure)
    if horodatage is None:
        return "Heure incomprise. Exemples : \"21h30\", \"9:15\"."

    alerte = _ajouter(Alerte(
        numero=next(_compteur),
        genre="rappel",
        message=message or "Rappel",
        echeance=horodatage,
    ))
    return f"Rappel enregistre. {alerte.describe()}"


# Mots de liaison d'une phrase francaise : ils ne designent jamais le
# programme surveille.
MOTS_VIDES = {
    "quand", "lorsque", "des", "que", "qu", "le", "la", "les", "l", "un",
    "une", "est", "sera", "aura", "a", "de", "du", "mon", "ma", "mes",
    "ferme", "fermee", "ferme", "termine", "terminee", "fini", "finie",
    "arrete", "arretee", "eteint", "stoppe", "plus", "ne", "n", "pas",
    "previens", "moi", "dis", "quand", "sur", "pc", "telechargement",
}


def _nom_de_programme(phrase: str) -> str:
    """Extrait le nom du programme d'une phrase en francais.

    On ecarte les mots de liaison plutot que de prendre le dernier mot :
    "quand notepad est ferme" designe notepad. On privilegie ensuite un mot
    qui correspond a un processus reellement en cours, ce qui leve les
    ambiguites restantes.
    """
    import unicodedata

    brut = unicodedata.normalize("NFKD", phrase.lower())
    brut = "".join(c for c in brut if not unicodedata.combining(c))
    # On coupe aussi sur le trait d'union : "previens-moi" reste sinon un
    # seul mot, absent de la liste des mots vides, et se fait prendre pour le
    # nom du programme.
    mots = [m for m in re.split(r"[^a-z0-9._]+", brut) if m]
    candidats = [m for m in mots if m not in MOTS_VIDES and len(m) > 2]
    if not candidats:
        return ""

    try:
        import psutil

        en_cours = set()
        for proc in psutil.process_iter(["name"]):
            try:
                nom = (proc.info.get("name") or "").lower()
                if nom:
                    en_cours.add(nom.removesuffix(".exe"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for mot in candidats:
            if mot in en_cours or any(mot in n for n in en_cours):
                return mot
    except Exception:  # noqa: BLE001
        pass

    return candidats[0]


def veille(quoi: str, message: str = "") -> str:
    """Surveille une condition et previent quand elle devient vraie."""
    demande = quoi.lower()

    condition = None
    libelle = quoi

    temperature = re.search(r"(\d+)\s*(?:degres?|°|c\b)", demande)
    if "gpu" in demande and temperature:
        seuil = float(temperature.group(1))
        condition = condition_gpu(seuil)
        libelle = f"GPU au-dessus de {seuil:.0f} C"
    elif "cpu" in demande or "processeur" in demande:
        pourcent = re.search(r"(\d+)\s*%", demande)
        seuil = float(pourcent.group(1)) if pourcent else 90.0
        condition = condition_cpu(seuil)
        libelle = f"CPU au-dessus de {seuil:.0f} %"
    elif "disque" in demande or "espace" in demande:
        lettre = re.search(r"\b([c-z]):", demande)
        go = re.search(r"(\d+)\s*go", demande)
        condition = condition_disque_libre(
            lettre.group(1) if lettre else "C", float(go.group(1)) if go else 20.0)
        libelle = "espace disque bas"
    elif re.search(r"[a-z]:\\", quoi, re.IGNORECASE):
        chemin = re.search(r"([a-z]:\\[^\"']+)", quoi, re.IGNORECASE)
        condition = condition_fichier(chemin.group(1).strip())
        libelle = f"fichier {chemin.group(1)[:50]} termine"
    else:
        # On cherche le nom du programme, pas le dernier mot de la phrase :
        # "quand notepad est ferme" designe notepad, pas "ferme".
        mot = _nom_de_programme(quoi)
        if mot:
            condition = condition_processus_termine(mot)
            libelle = f"{mot} termine"

    if condition is None:
        return ("Condition incomprise. Exemples : \"quand le GPU depasse 80 "
                "degres\", \"quand steam est ferme\", \"quand C: passe sous "
                "20 Go\".")

    alerte = _ajouter(Alerte(
        numero=next(_compteur),
        genre="veille",
        message=message or f"Condition atteinte : {libelle}",
        condition=condition,
    ))
    return f"Veille active : {libelle}. Numero {alerte.numero}."


def liste() -> str:
    with _lock:
        actives = [a for a in _alertes.values() if not a.declenchee]
        passees = [a for a in _alertes.values() if a.declenchee]

    if not actives and not passees:
        return ("Aucun minuteur ni alerte.\n\n"
                "Exemples : \"minuteur 20 minutes\", \"rappelle-moi a 21h30\", "
                "\"previens-moi quand le GPU depasse 80 degres\".")

    lignes = []
    if actives:
        lignes.append(f"{len(actives)} en cours :")
        for alerte in sorted(actives, key=lambda a: a.echeance or 0):
            lignes.append("  " + alerte.describe())
    if passees:
        lignes.append("")
        lignes.append(f"{len(passees)} deja declenchee(s) :")
        for alerte in passees[-5:]:
            lignes.append(f"  [{alerte.numero}] {alerte.message}")
    lignes.append("")
    lignes.append("Dis \"annule le minuteur 2\" pour en retirer un.")
    return "\n".join(lignes)


def annuler(numero: int | None = None) -> str:
    with _lock:
        if numero is None:
            combien = len([a for a in _alertes.values() if not a.declenchee])
            _alertes.clear()
            return f"{combien} alerte(s) annulee(s)."
        alerte = _alertes.pop(int(numero), None)
    if alerte is None:
        return f"Aucune alerte numero {numero}."
    return f"Alerte {numero} annulee ({alerte.message})."
