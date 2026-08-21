"""Capacite generale : executer une commande Windows.

Aucun catalogue d'outils ne couvrira jamais "n'importe quelle demande". Cette
brique donne acces a tout ce que Windows sait faire, au prix d'une discipline
stricte :

  1. Les commandes de LECTURE (Get-*, query, list) s'executent directement :
     elles ne changent rien, et confirmer chaque "quelle heure est-il" rendrait
     l'assistant insupportable.

  2. Les commandes qui MODIFIENT quelque chose sont affichees telles quelles
     et attendent un accord explicite. L'utilisateur voit le texte exact qui
     va s'executer, pas un resume.

  3. Certaines commandes sont REFUSEES, meme sur accord. Formater un disque,
     supprimer les cliches de restauration, effacer une ruche du registre :
     ce sont des actions dont on ne revient pas, et aucune formulation ne les
     rend acceptables depuis un assistant vocal ou une phrase mal transcrite.

Tout est journalise dans data/logs/actions.jsonl.
"""
from __future__ import annotations

import re
import subprocess

from assistant import safety

CREATE_NO_WINDOW = 0x08000000
TIMEOUT = 120
MAX_SORTIE = 6000

# --- Ce qu'on refuse categoriquement ----------------------------------------
#
# Motifs cherches dans la commande, en minuscules. Chacun designe une action
# irreversible ou destructrice a grande echelle.
INTERDITS = [
    (r"\bformat\s+[a-z]:", "formater un disque"),
    (r"\bdiskpart\b", "diskpart peut effacer une table de partitions"),
    (r"\bclean\s+all\b", "effacement bas niveau d'un disque"),
    (r"vssadmin\s+delete\s+shadows", "suppression des points de restauration"),
    (r"\bwbadmin\s+delete\b", "suppression de sauvegardes"),
    (r"\bcipher\s+/w", "effacement irrecuperable de l'espace libre"),
    (r"\bbcdedit\b", "modification du demarrage de Windows"),
    (r"\bbootrec\b", "reecriture du secteur de demarrage"),
    (r"reg\s+delete\s+hk(lm|ey_local_machine)\s*\\?\s*$", "effacement d'une ruche du registre"),
    (r"remove-item.*(c:\\windows|c:\\program files|\$env:systemroot)",
     "suppression dans un dossier systeme"),
    (r"\bdel\b.*[/-]s.*\bc:\\(windows|program files)", "suppression recursive systeme"),
    (r"rmdir\s+/s\s+/q\s+c:\\", "suppression recursive a la racine du disque"),
    (r"\bmkfs\b|\bdd\s+if=", "commande d'ecriture disque brute"),
    (r"set-executionpolicy\s+unrestricted", "abaissement des protections PowerShell"),
    (r"add-mppreference.*exclusionpath\s*['\"]?c:\\?['\"]?\s*$",
     "exclusion antivirus du disque entier"),
    (r"set-mppreference.*disablerealtimemonitoring\s*\$?true",
     "desactivation de la protection antivirus"),
    (r"\bnet\s+user\s+\S+\s+/add.*\/domain", "creation de compte de domaine"),
    (r"\bcurl\b.*\|\s*(iex|invoke-expression)", "execution d'un script telecharge"),
    (r"invoke-webrequest.*\|\s*(iex|invoke-expression)",
     "execution d'un script telecharge"),
    (r"\bstart-bitstransfer\b.*-source\s+http", "telechargement puis execution"),
]

# --- Ce qui ne modifie rien -------------------------------------------------
#
# Verbes PowerShell et commandes qui se contentent de lire. Tout le reste est
# considere comme modifiant, par defaut : se tromper dans ce sens ne coute
# qu'une confirmation de plus.
LECTURE_SEULE = re.compile(
    r"^\s*(get-|measure-|test-|resolve-|select-|where-|sort-|format-|"
    r"compare-|convertfrom-|convertto-|out-string|show-|find-|"
    r"tasklist|systeminfo|whoami|hostname|ipconfig|ver|date|time|"
    r"wmic\s+\w+\s+get|dir|ls|type|cat|echo|powercfg\s*/(list|query|getactivescheme)|"
    r"driverquery|net\s+(statistics|view|time)|sc\s+query|"
    r"nvidia-smi|chkdsk\s+[a-z]:\s*$|vol|tree)\b",
    re.IGNORECASE,
)

# Enchainements qui permettraient de cacher une commande modifiante derriere
# une commande de lecture.
ENCHAINEMENT = re.compile(r"[;&|]{1,2}|\bthen\b", re.IGNORECASE)


def refus(commande: str) -> str | None:
    """Rend la raison du refus, ou None si la commande est recevable."""
    aplati = " ".join(commande.lower().split())
    for motif, raison in INTERDITS:
        if re.search(motif, aplati):
            return raison
    return None


def lecture_seule(commande: str) -> bool:
    """La commande se contente-t-elle de lire ?

    Un enchainement (`;`, `&&`, `|`) suffit a la disqualifier : "Get-Date;
    Remove-Item ..." commence par un verbe de lecture mais ne l'est pas.
    Le pipe vers un formateur est la seule exception tolerable.
    """
    # "(Get-CimInstance ...).Caption" est une lecture : la parenthese
    # ouvrante ne doit pas la faire passer pour une commande modifiante.
    debut = commande.strip().lstrip("(").lstrip()
    if not LECTURE_SEULE.match(debut):
        return False
    for morceau in re.split(r"[;&]{1,2}", commande)[1:]:
        if morceau.strip():
            return False
    for morceau in commande.split("|")[1:]:
        if not re.match(r"^\s*(select-|sort-|format-|measure-|out-string|"
                        r"where-|convertto-|findstr|more|head|tail)\b",
                        morceau.strip(), re.IGNORECASE):
            return False
    return True


def _executer(commande: str) -> tuple[bool, str]:
    try:
        resultat = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", commande],
            capture_output=True, text=True, timeout=TIMEOUT,
            encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, f"La commande a depasse {TIMEOUT} secondes et a ete arretee."
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"

    sortie = ((resultat.stdout or "") + (resultat.stderr or "")).strip()
    if len(sortie) > MAX_SORTIE:
        sortie = sortie[:MAX_SORTIE] + "\n[... sortie tronquee]"
    return resultat.returncode == 0, sortie or "(aucune sortie)"


def run(commande: str, but: str = "", ask=None) -> str:
    """Execute une commande Windows, avec le garde-fou qui convient.

    `but` explique en francais ce que la commande cherche a obtenir : c'est
    ce que l'utilisateur lit avant de decider, et c'est ce qui reste dans le
    journal.
    """
    commande = (commande or "").strip()
    if not commande:
        return "Aucune commande fournie."

    raison = refus(commande)
    if raison:
        return (
            f"Je refuse cette commande : {raison}.\n"
            f"  {commande}\n"
            "C'est une action dont on ne revient pas. Si tu la veux vraiment, "
            "lance-la toi-meme depuis une invite administrateur, en sachant "
            "ce que tu fais."
        )

    if lecture_seule(commande):
        ok, sortie = _executer(commande)
        entete = "" if ok else "[la commande a signale une erreur]\n"
        return f"{entete}{sortie}"

    action = safety.Action(
        kind="commande",
        summary=but or "Executer une commande Windows",
        targets=[commande],
        reversible=False,
        details="Cette commande peut modifier la machine. Lis-la avant "
                "d'accepter : c'est le texte exact qui sera execute.",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    ok, sortie = _executer(commande)
    entete = "Commande executee.\n" if ok else "La commande a echoue.\n"
    return entete + sortie


def explique() -> str:
    """Ce que la capacite generale autorise et refuse, en clair."""
    return "\n".join([
        "COMMANDES WINDOWS",
        "",
        "L'assistant peut executer n'importe quelle commande Windows, ce qui",
        "lui permet de repondre a des demandes qu'aucun outil dedie ne couvre.",
        "",
        "  Lecture (Get-*, tasklist, ipconfig, systeminfo...)",
        "      executee directement, elle ne change rien",
        "",
        "  Modification (tout le reste)",
        "      la commande exacte t'est montree, et attend ton accord",
        "",
        f"  Refus definitif ({len(INTERDITS)} motifs)",
        "      formatage, diskpart, suppression des points de restauration,",
        "      effacement de ruches du registre, desactivation de l'antivirus,",
        "      execution de scripts telecharges, suppression dans Windows/",
        "      ou Program Files. Meme avec ton accord.",
        "",
        "Tout est journalise dans data/logs/actions.jsonl, accepte comme refuse.",
    ])
