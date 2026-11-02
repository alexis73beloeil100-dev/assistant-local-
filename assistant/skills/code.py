"""L'atelier de code : lire, chercher, ecrire, annuler, executer.

Il marche sur N'IMPORTE QUEL projet : un jeu Unreal, une application Python,
un site web, un projet Unity... Le projet est un dossier, choisi une fois.
Si ce dossier contient un .uproject, les outils Unreal s'y branchent aussi.

Tout se passe DANS le dossier du projet choisi. Un chemin qui en sort
-- moteur, Windows, un autre projet -- est refuse, meme avec "..".

Chaque ecriture :
  - est montree avant d'etre faite, sous forme de difference ;
  - attend l'accord de l'utilisateur (garde-fou de safety.py) ;
  - garde une copie du fichier d'origine, pour pouvoir l'annuler.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from assistant import config, safety

CREATE_NO_WINDOW = 0x08000000

# Ce qu'Unreal regenere : ni a lire, ni a chercher, ni a modifier.
DOSSIERS_IGNORES = {"binaries", "intermediate", "saved", "deriveddatacache",
                    ".vs", ".git", ".idea", "build", "node_modules",
                    "__pycache__", ".venv", "venv", ".mypy_cache",
                    ".pytest_cache", "dist", "obj", "library", "temp", "logs"}
EXTENSIONS_CODE = (".h", ".hpp", ".cpp", ".c", ".inl", ".cs", ".ini",
                   ".uproject", ".uplugin", ".usf", ".ush", ".json", ".md",
                   ".txt", ".py", ".js", ".jsx", ".ts", ".tsx", ".html",
                   ".css", ".scss", ".vue", ".java", ".kt", ".go", ".rs",
                   ".rb", ".php", ".lua", ".gd", ".shader", ".hlsl", ".glsl",
                   ".toml", ".yaml", ".yml", ".xml", ".cfg", ".bat", ".ps1",
                   ".sh", ".sql", ".csproj", ".sln", ".cmake")
LIGNES_MAX = 400
RESULTATS_MAX = 120
TAILLE_MAX = 2 * 1024 * 1024

SAUVEGARDES = config.DATA_DIR / "sauvegardes_code"
HISTORIQUE = SAUVEGARDES / "historique.json"
MEMOIRE = "ASSISTANT.md"


class HorsProjet(Exception):
    """Chemin refuse : hors du projet, ou projet non choisi."""


# --- Le projet et ses chemins ------------------------------------------------

CLE_DOSSIER = "projet_code"


def racine() -> Path:
    """Le dossier du projet de travail : choisi, sinon celui du projet Unreal."""
    from assistant import settings
    from assistant.skills import unreal

    dossier = settings.get(CLE_DOSSIER)
    if dossier and Path(dossier).is_dir():
        return Path(dossier).resolve()
    projet = unreal.projet_actuel()
    if projet is None:
        raise HorsProjet("Aucun projet choisi : utilise Choisir le projet, "
                         "ou l'outil choisir_projet.")
    return projet.parent.resolve()


def choisir_projet(chemin: str) -> str:
    """Le dossier de travail. S'il contient un .uproject, Unreal suit."""
    from assistant import settings
    from assistant.skills import unreal

    dossier = Path(str(chemin or "").strip().strip('"'))
    if dossier.is_file():
        dossier = dossier.parent
    if not dossier.is_dir():
        return f"{chemin} n'est pas un dossier existant."
    settings.set(CLE_DOSSIER, str(dossier.resolve()))
    message = f"Projet de travail : {dossier.name} ({dossier.resolve()})."
    uprojects = sorted(dossier.glob("*.uproject"))
    if uprojects:
        unreal.choisir_projet(str(uprojects[0]))
        message += f" C'est un projet Unreal : {uprojects[0].name}."
    reperes = [n for n in ("package.json", "pyproject.toml", "requirements.txt",
                           "CMakeLists.txt", "Cargo.toml", "go.mod", "pom.xml",
                           "build.gradle", ".git") if (dossier / n).exists()]
    reperes += [p.name for p in list(dossier.glob("*.sln"))[:2]]
    if reperes:
        message += f" Reperes : {', '.join(reperes)}."
    return message


def projet_nom() -> str:
    try:
        return racine().name
    except HorsProjet:
        return ""


# --- Executer dans le projet ------------------------------------------------------

# Construire et tester : des gestes qu'on refait vingt fois, sans danger pour
# la machine. Ils passent sans fenetre, journalises. Tout le reste demande.
_CONSTRUIRE = re.compile(
    r"^\s*(python3?|py)\s+-m\s+(pytest|unittest|build|compileall)\b|"
    r"^\s*(pytest|tox|nox)\b|"
    r"^\s*(npm|pnpm|yarn)\s+(test|run\s+[\w:-]+|ci|install)\b|"
    r"^\s*(dotnet)\s+(build|test|run|restore)\b|"
    r"^\s*cmake\s+(--build|-S|-B)\b|^\s*(msbuild|ninja|make)\b|"
    r"^\s*cargo\s+(build|test|check|run|clippy)\b|"
    r"^\s*go\s+(build|test|vet|run)\b|"
    r"^\s*(gradle|gradlew|\.[\\/]gradlew|mvn)\b", re.I)
SORTIE_MAX = 200


def executer(commande: str, delai: int = 600, ask=None) -> str:
    """Lance une commande dans le dossier du projet et rend sa sortie."""
    from assistant.skills import shell

    commande = (commande or "").strip()
    if not commande:
        return "Aucune commande."
    try:
        base = racine()
    except HorsProjet as exc:
        return str(exc)
    raison = shell.refus(commande)
    if raison:
        return f"Je refuse cette commande : {raison}."
    routine = bool(_CONSTRUIRE.match(commande)) or shell.lecture_seule(commande)
    action = safety.Action(kind="commande", summary=f"Dans {base.name} : {commande}",
                           targets=[str(base)], reversible=routine,
                           routine=routine)
    try:
        if not safety.guard(action, ask=ask):
            return "Commande refusee."
    except safety.Refused as exc:
        return str(exc)
    if os.name == "nt":
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command", commande]
    else:
        argv = ["sh", "-c", commande]
    debut = time.time()
    try:
        r = subprocess.run(argv, cwd=str(base), capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=max(10, min(int(delai or 600), 3600)),
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return f"Arretee apres {delai} s : la commande ne rendait pas la main."
    except OSError as exc:
        return f"Lancement impossible : {exc}"
    lignes = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).splitlines()
    coupe = len(lignes) > SORTIE_MAX
    if coupe:
        lignes = lignes[:40] + [f"... ({len(lignes) - SORTIE_MAX} lignes) ..."] + lignes[-(SORTIE_MAX - 40):]
    return (f"Code de sortie {r.returncode} en {time.time() - debut:.1f} s"
            + (" (sortie coupee au milieu)" if coupe else "") + "\n"
            + "\n".join(lignes))


def resoudre(chemin: str) -> Path:
    """Chemin absolu DANS le projet, ou HorsProjet."""
    base = racine()
    brut = Path(str(chemin or "").strip().strip('"'))
    cible = (brut if brut.is_absolute() else base / brut).resolve()
    if cible != base and base not in cible.parents:
        raise HorsProjet(f"{chemin} est hors du projet ({base}) : refuse.")
    return cible


def _relatif(chemin: Path) -> str:
    try:
        return str(chemin.relative_to(racine())).replace("\\", "/")
    except (ValueError, HorsProjet):
        return str(chemin)


def _ignore(chemin: Path) -> bool:
    return any(p.lower() in DOSSIERS_IGNORES for p in chemin.parts)


def _lire_texte(chemin: Path) -> str:
    if chemin.stat().st_size > TAILLE_MAX:
        raise ValueError(f"{chemin.name} depasse {TAILLE_MAX // 1024} Ko.")
    brut = chemin.read_bytes()
    for codage in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            texte = brut.decode(codage)
            if codage == "utf-16" and not brut.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return texte
        except UnicodeDecodeError:
            continue
    return brut.decode("utf-8", errors="replace")


# --- Lire et chercher ----------------------------------------------------------

def arborescence(dossier: str = "", profondeur: int = 3) -> str:
    try:
        base = resoudre(dossier)
    except HorsProjet as exc:
        return str(exc)
    if not base.is_dir():
        return f"{dossier} n'est pas un dossier du projet."
    profondeur = max(1, min(int(profondeur or 3), 6))
    lignes = [f"{_relatif(base) or '.'}/"]
    compte = 0

    def parcourir(d: Path, niveau: int) -> None:
        nonlocal compte
        try:
            enfants = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for e in enfants:
            if e.name.lower() in DOSSIERS_IGNORES or compte >= 600:
                continue
            compte += 1
            lignes.append("  " * niveau + e.name + ("/" if e.is_dir() else ""))
            if e.is_dir() and niveau < profondeur:
                parcourir(e, niveau + 1)

    parcourir(base, 1)
    if compte >= 600:
        lignes.append("  ... (coupe a 600 entrees : precise un sous-dossier)")
    return "\n".join(lignes)


def lire_code(chemin: str, debut: int = 1, fin: int = 0) -> str:
    """Le fichier avec ses numeros de ligne, par tranches de 400 lignes."""
    try:
        cible = resoudre(chemin)
        texte = _lire_texte(cible)
    except (HorsProjet, ValueError) as exc:
        return str(exc)
    except OSError:
        return f"{chemin} introuvable dans le projet."
    lignes = texte.splitlines()
    debut = max(1, int(debut or 1))
    fin = int(fin or 0) or min(len(lignes), debut + LIGNES_MAX - 1)
    fin = min(fin, len(lignes), debut + LIGNES_MAX - 1)
    corps = [f"{n:>5}  {lignes[n - 1]}" for n in range(debut, fin + 1)]
    suite = (f"\n... {len(lignes) - fin} ligne(s) de plus : relis avec "
             f"debut={fin + 1}") if fin < len(lignes) else ""
    return (f"{_relatif(cible)} ({len(lignes)} lignes)\n" + "\n".join(corps)
            + suite)


def chercher_code(motif: str, regex: bool = False, dossier: str = "") -> str:
    """Chaque ligne du code du projet qui contient le motif."""
    try:
        base = resoudre(dossier)
    except HorsProjet as exc:
        return str(exc)
    try:
        test = re.compile(motif if regex else re.escape(motif), re.I)
    except re.error as exc:
        return f"Expression invalide : {exc}"
    trouves, fichiers = [], set()
    for f in base.rglob("*"):
        if (not f.is_file() or _ignore(f.relative_to(base))
                or f.suffix.lower() not in EXTENSIONS_CODE):
            continue
        try:
            texte = _lire_texte(f)
        except (OSError, ValueError):
            continue
        for n, ligne in enumerate(texte.splitlines(), 1):
            if test.search(ligne):
                trouves.append(f"{_relatif(f)}:{n}: {ligne.strip()[:200]}")
                fichiers.add(f)
                if len(trouves) >= RESULTATS_MAX:
                    break
        if len(trouves) >= RESULTATS_MAX:
            break
    if not trouves:
        return f"Aucune occurrence de « {motif} » dans le code du projet."
    entete = f"{len(trouves)} occurrence(s) dans {len(fichiers)} fichier(s)"
    if len(trouves) >= RESULTATS_MAX:
        entete += f" (arret a {RESULTATS_MAX} : affine la recherche)"
    return entete + " :\n" + "\n".join(trouves)


# --- Ecrire --------------------------------------------------------------------

def _difference(avant: str, apres: str, nom: str) -> str:
    lignes = list(difflib.unified_diff(
        avant.splitlines(), apres.splitlines(), f"a/{nom}", f"b/{nom}",
        lineterm="", n=2))
    if len(lignes) > 160:
        lignes = lignes[:160] + [f"... ({len(lignes) - 160} lignes de plus)"]
    return "\n".join(lignes)


def _historique() -> list[dict]:
    try:
        return json.loads(HISTORIQUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _noter(entree: dict) -> int:
    SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    historique = _historique()
    entree["numero"] = (historique[-1]["numero"] + 1) if historique else 1
    historique.append(entree)
    HISTORIQUE.write_text(json.dumps(historique[-500:], ensure_ascii=False,
                                     indent=1), encoding="utf-8")
    return entree["numero"]


def _sauvegarder(cible: Path) -> str:
    SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    copie = SAUVEGARDES / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time_ns() % 1e6)}-{cible.name}"
    shutil.copy2(cible, copie)
    return str(copie)


def _ecrire(cible: Path, texte: str, fin_de_ligne: str) -> None:
    cible.parent.mkdir(parents=True, exist_ok=True)
    with cible.open("w", encoding="utf-8", newline=fin_de_ligne) as fh:
        fh.write(texte)


def modifier_fichier(chemin: str, ancien: str, nouveau: str,
                     tout: bool = False, ask=None) -> str:
    """Remplace un passage exact. Il doit etre unique, sauf `tout`."""
    try:
        cible = resoudre(chemin)
        avant = _lire_texte(cible)
    except (HorsProjet, ValueError) as exc:
        return str(exc)
    except OSError:
        return f"{chemin} introuvable : pour un nouveau fichier, creer_fichier."
    if not ancien:
        return "Le passage a remplacer est vide."
    # Le modele ecrit en \n ; le fichier peut etre en \r\n.
    fin = "\r\n" if "\r\n" in avant else "\n"
    norm = avant.replace("\r\n", "\n")
    ancien_n, nouveau_n = ancien.replace("\r\n", "\n"), nouveau.replace("\r\n", "\n")
    nombre = norm.count(ancien_n)
    if nombre == 0:
        return (f"Passage introuvable dans {_relatif(cible)} : relis le fichier "
                "avec lire_code et recopie le passage exactement, espaces "
                "compris.")
    if nombre > 1 and not tout:
        return (f"Le passage apparait {nombre} fois dans {_relatif(cible)} : "
                "ajoute du contexte pour qu'il soit unique, ou demande de "
                "tout remplacer.")
    apres = norm.replace(ancien_n, nouveau_n) if tout else norm.replace(
        ancien_n, nouveau_n, 1)
    if apres == norm:
        return "Rien ne change : le nouveau texte est identique."
    diff = _difference(norm, apres, _relatif(cible))
    action = safety.Action(
        kind="code", summary=f"Modifier {_relatif(cible)}",
        targets=[str(cible)], reversible=True, details=diff)
    try:
        if not safety.guard(action, ask=ask):
            return "Modification refusee : rien n'a ete ecrit."
    except safety.Refused as exc:
        return str(exc)
    copie = _sauvegarder(cible)
    _ecrire(cible, apres, fin)
    numero = _noter({"genre": "modification", "fichier": str(cible),
                     "copie": copie, "quand": time.strftime("%Y-%m-%d %H:%M:%S")})
    return f"Modifie : {_relatif(cible)} (modification n°{numero}).\n{diff}"


def creer_fichier(chemin: str, contenu: str, ask=None) -> str:
    try:
        cible = resoudre(chemin)
    except HorsProjet as exc:
        return str(exc)
    if cible.exists():
        return (f"{_relatif(cible)} existe deja : utilise modifier_fichier "
                "pour le changer.")
    if _ignore(cible.relative_to(racine())):
        return "Ce dossier est regenere par Unreal : rien n'y est ecrit."
    texte = contenu.replace("\r\n", "\n")
    apercu = "\n".join(f"+{l}" for l in texte.splitlines()[:120])
    action = safety.Action(
        kind="code", summary=f"Creer {_relatif(cible)}",
        targets=[str(cible)], reversible=True, details=apercu)
    try:
        if not safety.guard(action, ask=ask):
            return "Creation refusee : rien n'a ete ecrit."
    except safety.Refused as exc:
        return str(exc)
    _ecrire(cible, texte, "\r\n")
    numero = _noter({"genre": "creation", "fichier": str(cible), "copie": "",
                     "quand": time.strftime("%Y-%m-%d %H:%M:%S")})
    return (f"Cree : {_relatif(cible)}, {len(texte.splitlines())} lignes "
            f"(modification n°{numero}).")


def historique(nombre: int = 15) -> str:
    entrees = _historique()[-max(1, int(nombre or 15)):]
    if not entrees:
        return "Aucune modification de code enregistree."
    lignes = ["Dernieres modifications de code (annulables) :"]
    for e in reversed(entrees):
        etat = " [annulee]" if e.get("annulee") else ""
        lignes.append(f"  n°{e['numero']}  {e['quand']}  {e['genre']:<12} "
                      f"{e['fichier']}{etat}")
    return "\n".join(lignes)


def annuler(numero: int = 0, ask=None) -> str:
    """Remet un fichier comme avant la modification n° (la derniere si 0)."""
    entrees = _historique()
    candidates = [e for e in entrees if not e.get("annulee")
                  and (not numero or e["numero"] == int(numero))]
    if not candidates:
        return "Aucune modification correspondante a annuler."
    e = candidates[-1]
    cible = Path(e["fichier"])
    if e["genre"] == "creation":
        resume = f"Supprimer {cible.name}, cree par la modification n°{e['numero']} (part a la Corbeille)"
    else:
        resume = f"Remettre {cible.name} comme avant la modification n°{e['numero']}"
    action = safety.Action(kind="code", summary=resume, targets=[str(cible)],
                           reversible=True)
    try:
        if not safety.guard(action, ask=ask):
            return "Annulation refusee."
    except safety.Refused as exc:
        return str(exc)
    try:
        if e["genre"] == "creation":
            if cible.exists():
                from send2trash import send2trash

                send2trash(str(cible))
        else:
            shutil.copy2(e["copie"], cible)
    except OSError as exc:
        return f"Annulation impossible : {exc}"
    for x in entrees:
        if x["numero"] == e["numero"]:
            x["annulee"] = True
    HISTORIQUE.write_text(json.dumps(entrees, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    safety.noter_annulation(str(e["numero"]), resume, True)
    return f"Annule : modification n°{e['numero']} ({cible.name})."


# --- Plan et memoire du projet ------------------------------------------------------

_plan: list[tuple[str, bool]] = []


def plan(etapes: list | None = None, faites: list | None = None) -> str:
    """Ecrit (etapes) ou coche (faites, numeros a partir de 1) le plan."""
    global _plan
    if etapes:
        _plan = [(str(e).strip(), False) for e in etapes if str(e).strip()]
    for n in faites or []:
        try:
            i = int(n) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(_plan):
            _plan[i] = (_plan[i][0], True)
    if not _plan:
        return "Aucun plan en cours."
    faits = sum(1 for _e, ok in _plan if ok)
    lignes = [f"Plan ({faits}/{len(_plan)}) :"]
    lignes += [f"  [{'x' if ok else ' '}] {n}. {e}"
               for n, (e, ok) in enumerate(_plan, 1)]
    return "\n".join(lignes)


def memoire_projet(ajout: str = "") -> str:
    """Lit ASSISTANT.md, ou y ajoute une note datee."""
    try:
        fichier = racine() / MEMOIRE
    except HorsProjet as exc:
        return str(exc)
    if ajout.strip():
        entete = "" if fichier.exists() else (
            "# Notes de l'assistant sur ce projet\n\n"
            "Relues au debut de chaque session. Modifiables a la main.\n\n")
        with fichier.open("a", encoding="utf-8") as fh:
            fh.write(f"{entete}- {time.strftime('%d/%m/%Y')} : {ajout.strip()}\n")
        return f"Note ajoutee a {MEMOIRE}."
    if not fichier.exists():
        return f"Pas encore de {MEMOIRE} dans ce projet."
    return _lire_texte(fichier)[-6000:]


def memoire_pour_le_modele() -> str:
    """Le contenu d'ASSISTANT.md a joindre au contexte, ou ""."""
    try:
        fichier = racine() / MEMOIRE
        return _lire_texte(fichier)[-4000:] if fichier.exists() else ""
    except (HorsProjet, OSError, ValueError):
        return ""


# --- Git ----------------------------------------------------------------------------

def _git(*args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(racine()), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout,
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except HorsProjet as exc:
        return 1, str(exc)
    except FileNotFoundError:
        return 1, "Git n'est pas installe sur ce PC."
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"Git a echoue : {exc}"
    return r.returncode, (r.stdout + r.stderr).strip()


def git_etat() -> str:
    code, sortie = _git("status", "--short", "--branch")
    if code:
        return sortie if "not a git repository" not in sortie else (
            "Ce projet n'est pas sous Git.")
    _c, stat = _git("diff", "--stat")
    return sortie + ("\n\n" + stat if stat else "")


def git_difference(chemin: str = "") -> str:
    args = ["diff"] + (["--", chemin] if chemin else [])
    code, sortie = _git(*args)
    if code:
        return sortie
    if not sortie:
        return "Aucune difference non enregistree."
    return sortie[:12000] + ("\n... (coupe)" if len(sortie) > 12000 else "")


def git_enregistrer(message: str, ask=None) -> str:
    """git add -A puis commit, apres accord."""
    message = (message or "").strip()
    if not message:
        return "Il faut un message de commit."
    code, etat = _git("status", "--short")
    if code:
        return etat
    if not etat:
        return "Rien a enregistrer."
    action = safety.Action(kind="git", summary=f"Commit : {message}",
                           targets=etat.splitlines()[:20], reversible=True)
    try:
        if not safety.guard(action, ask=ask):
            return "Commit annule."
    except safety.Refused as exc:
        return str(exc)
    code, sortie = _git("add", "-A")
    if code:
        return sortie
    code, sortie = _git("commit", "-m", message)
    return sortie


# --- Ce qui manquait pour avoir les memes outils qu'un assistant de code -------

def trouver_fichiers(motif: str, dossier: str = "") -> str:
    """Les fichiers dont le chemin correspond a un motif (ex. **/*Arme*.h)."""
    try:
        base = resoudre(dossier)
    except HorsProjet as exc:
        return str(exc)
    motif = (motif or "*").strip().replace("\\", "/")
    trouves = []
    for f in base.glob(motif if "/" in motif or "**" in motif else f"**/{motif}"):
        if f.is_file() and not _ignore(f.relative_to(base)):
            trouves.append(f)
    if not trouves:
        return f"Aucun fichier ne correspond a « {motif} »."
    trouves.sort(key=lambda f: -f.stat().st_mtime)
    lignes = [f"{len(trouves)} fichier(s), du plus recemment modifie au plus ancien :"]
    lignes += [f"  {_relatif(f)}" for f in trouves[:RESULTATS_MAX]]
    if len(trouves) > RESULTATS_MAX:
        lignes.append(f"  ... et {len(trouves) - RESULTATS_MAX} autres")
    return "\n".join(lignes)


def ecrire_fichier(chemin: str, contenu: str, ask=None) -> str:
    """Remplace tout le contenu d'un fichier existant, difference montree."""
    try:
        cible = resoudre(chemin)
        avant = _lire_texte(cible)
    except (HorsProjet, ValueError) as exc:
        return str(exc)
    except OSError:
        return creer_fichier(chemin, contenu, ask=ask)
    fin = "\r\n" if "\r\n" in avant else "\n"
    norm, apres = avant.replace("\r\n", "\n"), contenu.replace("\r\n", "\n")
    if norm == apres:
        return "Rien ne change : le contenu est identique."
    diff = _difference(norm, apres, _relatif(cible))
    action = safety.Action(kind="code", summary=f"Reecrire {_relatif(cible)}",
                           targets=[str(cible)], reversible=True, details=diff)
    try:
        if not safety.guard(action, ask=ask):
            return "Reecriture refusee : rien n'a ete ecrit."
    except safety.Refused as exc:
        return str(exc)
    copie = _sauvegarder(cible)
    _ecrire(cible, apres, fin)
    numero = _noter({"genre": "modification", "fichier": str(cible),
                     "copie": copie, "quand": time.strftime("%Y-%m-%d %H:%M:%S")})
    return f"Reecrit : {_relatif(cible)} (modification n°{numero}).\n{diff}"


def modifier_plusieurs(chemin: str, remplacements: list, ask=None) -> str:
    """Plusieurs remplacements dans un fichier, en une seule validation.

    Tout ou rien : si un seul passage est introuvable ou ambigu, rien n'est
    ecrit. Chaque remplacement s'applique au resultat du precedent.
    """
    try:
        cible = resoudre(chemin)
        avant = _lire_texte(cible)
    except (HorsProjet, ValueError) as exc:
        return str(exc)
    except OSError:
        return f"{chemin} introuvable."
    fin = "\r\n" if "\r\n" in avant else "\n"
    texte = avant.replace("\r\n", "\n")
    for n, r in enumerate(remplacements or [], 1):
        ancien = str((r or {}).get("ancien", "")).replace("\r\n", "\n")
        nouveau = str((r or {}).get("nouveau", "")).replace("\r\n", "\n")
        nombre = texte.count(ancien) if ancien else 0
        if nombre != 1:
            return (f"Remplacement n°{n} : passage {'introuvable' if not nombre else f'present {nombre} fois'}"
                    f" dans {_relatif(cible)}. Rien n'a ete ecrit.")
        texte = texte.replace(ancien, nouveau, 1)
    norm = avant.replace("\r\n", "\n")
    if texte == norm:
        return "Rien ne change."
    diff = _difference(norm, texte, _relatif(cible))
    action = safety.Action(kind="code",
                           summary=f"Modifier {_relatif(cible)} ({len(remplacements)} passages)",
                           targets=[str(cible)], reversible=True, details=diff)
    try:
        if not safety.guard(action, ask=ask):
            return "Modification refusee : rien n'a ete ecrit."
    except safety.Refused as exc:
        return str(exc)
    copie = _sauvegarder(cible)
    _ecrire(cible, texte, fin)
    numero = _noter({"genre": "modification", "fichier": str(cible),
                     "copie": copie, "quand": time.strftime("%Y-%m-%d %H:%M:%S")})
    return f"Modifie : {_relatif(cible)} (modification n°{numero}).\n{diff}"


# Commandes longues lancees en fond : serveur de developpement, surveillance,
# compilation d'une heure. On les suit sans bloquer la conversation.
_en_fond: dict[int, dict] = {}


def lancer_en_fond(commande: str, ask=None) -> str:
    import threading

    try:
        base = racine()
    except HorsProjet as exc:
        return str(exc)
    from assistant.skills import shell

    raison = shell.refus(commande)
    if raison:
        return f"Je refuse cette commande : {raison}."
    routine = bool(_CONSTRUIRE.match(commande))
    action = safety.Action(kind="commande", summary=f"En fond, dans {base.name} : {commande}",
                           targets=[str(base)], reversible=routine, routine=routine)
    try:
        if not safety.guard(action, ask=ask):
            return "Commande refusee."
    except safety.Refused as exc:
        return str(exc)
    argv = (["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-Command", commande] if os.name == "nt" else ["sh", "-c", commande])
    proc = subprocess.Popen(argv, cwd=str(base), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace",
                            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    numero = max(_en_fond, default=0) + 1
    suivi = {"proc": proc, "commande": commande, "lignes": [], "debut": time.time()}

    def lire():
        for ligne in proc.stdout:
            suivi["lignes"].append(ligne.rstrip())
            del suivi["lignes"][:-2000]

    threading.Thread(target=lire, daemon=True).start()
    _en_fond[numero] = suivi
    return f"Lance en fond, n°{numero} : {commande}. Suis-le avec sortie_en_fond."


def sortie_en_fond(numero: int = 0, lignes: int = 60) -> str:
    if not _en_fond:
        return "Aucune commande en fond."
    if not numero:
        lignes_etat = []
        for n, s in _en_fond.items():
            code_fin = s["proc"].poll()
            etat = "en cours" if code_fin is None else f"finie (code {code_fin})"
            lignes_etat.append(f"n°{n}  {etat}  {int(time.time() - s['debut'])} s  "
                               f"{s['commande']}")
        return "\n".join(lignes_etat)
    suivi = _en_fond.get(int(numero))
    if suivi is None:
        return f"Pas de commande en fond n°{numero}."
    etat = suivi["proc"].poll()
    entete = (f"n°{numero} {'en cours' if etat is None else f'finie, code {etat}'}, "
              f"{int(time.time() - suivi['debut'])} s : {suivi['commande']}")
    return entete + "\n" + "\n".join(suivi["lignes"][-max(5, int(lignes)):])


def arreter_en_fond(numero: int) -> str:
    suivi = _en_fond.get(int(numero))
    if suivi is None:
        return f"Pas de commande en fond n°{numero}."
    if suivi["proc"].poll() is None:
        suivi["proc"].terminate()
        try:
            suivi["proc"].wait(timeout=10)
        except subprocess.TimeoutExpired:
            suivi["proc"].kill()
    return f"Commande n°{numero} arretee."


def point_du_projet() -> str:
    """Ou en est le projet, en un seul appel : de quoi repondre sans inventer."""
    try:
        base = racine()
    except HorsProjet as exc:
        return str(exc)
    from assistant.skills import unreal

    morceaux = [f"PROJET {base.name} ({base})"]
    projet_ue = unreal.projet_actuel()
    if projet_ue is not None and projet_ue.parent.resolve() == base:
        morceaux.append(unreal.resume_projet())
    else:
        recents = []
        for f in base.rglob("*"):
            if (f.is_file() and not _ignore(f.relative_to(base))
                    and f.suffix.lower() in EXTENSIONS_CODE):
                try:
                    recents.append((f.stat().st_mtime, f))
                except OSError:
                    continue
        recents.sort(key=lambda x: -x[0])
        morceaux.append("Activite recente (fichiers modifies) :\n" + "\n".join(
            f"  {time.strftime('%d/%m/%Y %H:%M', time.localtime(t))}  {_relatif(f)}"
            for t, f in recents[:12]) if recents else "Aucun fichier de code.")
        code_git, journal = _git("log", "-8", "--date=format:%d/%m/%Y",
                                 "--pretty=format:  %ad  %s")
        if not code_git and journal:
            morceaux.append("Derniers enregistrements Git :\n" + journal)
    morceaux.append("Git, maintenant :\n" + git_etat())
    morceaux.append(plan())
    notes = memoire_pour_le_modele()
    morceaux.append("Notes du projet (ASSISTANT.md) :\n" + (notes[-2000:] if notes else "aucune"))
    morceaux.append(historique(5))
    if _en_fond:
        morceaux.append("Commandes en fond :\n" + sortie_en_fond(0))
    return "\n\n".join(morceaux)
