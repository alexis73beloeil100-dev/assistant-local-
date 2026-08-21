"""Detection et lancement des jeux installes.

Sources, dans l'ordre de fiabilite :
  1. Steam   -> steamapps/libraryfolders.vdf puis les appmanifest_*.acf
  2. Epic    -> C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests/*.item
  3. Ubisoft -> HKLM/SOFTWARE/WOW6432Node/Ubisoft/Launcher/Installs
  4. EA      -> entrees de desinstallation qui pointent vers EA Desktop

Le lancement passe par les URI des launchers (steam://, uplay://, ...) plutot
que par l'executable : c'est ce qui declenche le DRM, les overlays et la
synchro des sauvegardes comme si tu avais clique dans la bibliotheque.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

STEAM_REG = r"HKCU:\Software\Valve\Steam"
EPIC_MANIFESTS = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
UBISOFT_REG = r"HKLM:\SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"

# Entrees Steam qui ne sont pas des jeux.
STEAM_NON_GAMES = {"228980", "1070560", "1391110", "1493710"}  # redists, runtimes


@dataclass
class Game:
    name: str
    launcher: str          # steam / epic / ubisoft / ea / riot
    game_id: str
    install_dir: str = ""
    size_bytes: int = 0
    # Riot ne publie pas d'URI utilisable : on lance son client avec des
    # arguments. Quand exe est renseigne, il prime sur uri.
    exe: str = ""
    args: list[str] = None

    @property
    def uri(self) -> str:
        if self.launcher == "steam":
            return f"steam://rungameid/{self.game_id}"
        if self.launcher == "epic":
            return (
                f"com.epicgames.launcher://apps/{self.game_id}"
                "?action=launch&silent=true"
            )
        if self.launcher == "ubisoft":
            return f"uplay://launch/{self.game_id}/0"
        if self.launcher == "ea":
            return f"origin2://game/launch?offerIds={self.game_id}"
        return self.game_id  # chemin d'executable direct

    def __str__(self) -> str:
        return f"{self.name}  ({self.launcher})"


# --- Normalisation pour la reconnaissance vocale ----------------------------

# La transcription rend rarement les chiffres : "simulator 2" devient
# "simulator deux". On ramene les deux formes a la meme chose.
_NUMBER_WORDS = {
    "zero": "0", "un": "1", "une": "1", "deux": "2", "trois": "3",
    "quatre": "4", "cinq": "5", "six": "6", "sept": "7", "huit": "8",
    "neuf": "9", "dix": "10",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
}


def canon(text: str) -> str:
    """Forme canonique d'un titre : sans accent, sans ponctuation, chiffres unifies."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    words = [_NUMBER_WORDS.get(w, w) for w in text.split()]
    return " ".join(words)


# --- Steam ------------------------------------------------------------------

def _vdf_pairs(text: str) -> list[tuple[str, str]]:
    """Extrait les paires "cle" "valeur" d'un fichier VDF.

    Suffisant ici : on ne cherche que des scalaires a plat, pas la structure.
    """
    return re.findall(r'"([^"]+)"\s*"([^"]*)"', text)


def _steam_path() -> Path | None:
    import winreg

    for hive, key, value in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                path = Path(winreg.QueryValueEx(k, value)[0])
                if path.is_dir():
                    return path
        except OSError:
            continue
    return None


def steam_games() -> list[Game]:
    root = _steam_path()
    if not root:
        return []

    libraries = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for key, value in _vdf_pairs(vdf.read_text(encoding="utf-8", errors="ignore")):
            if key == "path":
                p = Path(value.replace("\\\\", "\\"))
                if p.is_dir() and p not in libraries:
                    libraries.append(p)

    games: list[Game] = []
    seen: set[str] = set()
    for lib in libraries:
        apps = lib / "steamapps"
        if not apps.is_dir():
            continue
        for manifest in apps.glob("appmanifest_*.acf"):
            try:
                pairs = dict(
                    _vdf_pairs(manifest.read_text(encoding="utf-8", errors="ignore"))
                )
            except OSError:
                continue
            appid = pairs.get("appid", "")
            name = pairs.get("name", "")
            if not appid or not name or appid in STEAM_NON_GAMES or appid in seen:
                continue
            seen.add(appid)
            install = pairs.get("installdir", "")
            games.append(
                Game(
                    name=name,
                    launcher="steam",
                    game_id=appid,
                    install_dir=str(apps / "common" / install) if install else "",
                    size_bytes=int(pairs.get("SizeOnDisk", 0) or 0),
                )
            )
    return games


# --- Epic -------------------------------------------------------------------

def epic_games() -> list[Game]:
    if not EPIC_MANIFESTS.is_dir():
        return []
    games = []
    for item in EPIC_MANIFESTS.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
        except (json.JSONDecodeError, OSError):
            continue
        name = data.get("DisplayName", "")
        app = data.get("AppName", "")
        # Les DLC et modules partagent le manifeste du jeu parent.
        if not name or not app or data.get("bIsIncompleteInstall"):
            continue
        if data.get("AppCategories") and "games" not in [
            c.lower() for c in data.get("AppCategories", [])
        ]:
            continue
        games.append(
            Game(
                name=name,
                launcher="epic",
                game_id=app,
                install_dir=data.get("InstallLocation", ""),
                size_bytes=int(data.get("InstallSize", 0) or 0),
            )
        )
    return games


# --- Ubisoft ----------------------------------------------------------------

def ubisoft_games() -> list[Game]:
    import winreg

    games = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs"
        ) as root:
            i = 0
            while True:
                try:
                    game_id = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, game_id) as k:
                        install = winreg.QueryValueEx(k, "InstallDir")[0]
                except OSError:
                    continue
                install = install.replace("/", "\\").rstrip("\\")
                # Ubisoft ne stocke pas le titre : le nom du dossier est
                # ce qu'on a de plus proche.
                games.append(
                    Game(
                        name=Path(install).name,
                        launcher="ubisoft",
                        game_id=game_id,
                        install_dir=install,
                    )
                )
    except OSError:
        pass
    return games


# --- EA ---------------------------------------------------------------------

def ea_games() -> list[Game]:
    """Jeux EA declares dans les entrees de desinstallation.

    L'EA app n'expose pas de manifeste lisible : on retombe sur le registre
    de desinstallation, ce qui donne le titre et le dossier mais pas
    toujours l'identifiant d'offre necessaire au lancement par URI.
    """
    import winreg

    games = []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as root:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            publisher = _reg_get(k, "Publisher")
                            name = _reg_get(k, "DisplayName")
                            install = _reg_get(k, "InstallLocation")
                    except OSError:
                        continue
                    if not name or "electronic arts" not in publisher.lower():
                        continue
                    if "ea app" in name.lower() or "origin" in name.lower():
                        continue
                    games.append(
                        Game(name=name, launcher="ea", game_id=sub, install_dir=install)
                    )
        except OSError:
            continue
    return games


# --- Riot -------------------------------------------------------------------

RIOT_INSTALLS = Path(r"C:\ProgramData\Riot Games\RiotClientInstalls.json")

# Le dossier d'installation ne donne pas l'identifiant produit attendu par le
# client Riot : cette table fait le lien.
RIOT_PRODUCTS = {
    "valorant": ("valorant", "VALORANT"),
    "league of legends": ("league_of_legends", "League of Legends"),
    "teamfight tactics": ("bacon", "Teamfight Tactics"),
    "legends of runeterra": ("bacon", "Legends of Runeterra"),
}


def riot_games() -> list[Game]:
    if not RIOT_INSTALLS.exists():
        return []
    try:
        data = json.loads(RIOT_INSTALLS.read_text(encoding="utf-8", errors="ignore"))
    except (json.JSONDecodeError, OSError):
        return []

    client = data.get("rc_default") or data.get("rc_live") or ""
    client = client.replace("/", "\\")
    if not client or not Path(client).exists():
        return []

    games = []
    for install_path in data.get("associated_client", {}):
        folder = install_path.replace("/", "\\").rstrip("\\")
        # "C:\Riot Games\VALORANT\live" -> on cherche "valorant" dans le chemin
        product = label = None
        for needle, (pid, title) in RIOT_PRODUCTS.items():
            if needle in folder.lower():
                product, label = pid, title
                break
        if not product:
            continue
        games.append(
            Game(
                name=label,
                launcher="riot",
                game_id=product,
                install_dir=folder,
                exe=client,
                args=[f"--launch-product={product}", "--launch-patchline=live"],
            )
        )
    return games


def _reg_get(key, name: str) -> str:
    import winreg

    try:
        return str(winreg.QueryValueEx(key, name)[0])
    except OSError:
        return ""


# --- Agregation -------------------------------------------------------------

def all_games(refresh: bool = False) -> list[Game]:
    """Tous les jeux detectes, dedoublonnes par titre canonique."""
    games: list[Game] = []
    for source in (steam_games, epic_games, ubisoft_games, ea_games, riot_games):
        try:
            games.extend(source())
        except Exception:
            # Un launcher casse ne doit pas empecher les autres de repondre.
            continue

    unique: dict[str, Game] = {}
    for g in games:
        key = canon(g.name)
        # Steam gagne : c'est la source qui a le vrai titre et le vrai poids.
        if key not in unique or g.launcher == "steam":
            unique[key] = g
    return sorted(unique.values(), key=lambda g: g.name.lower())


def find(query: str, games: list[Game] | None = None) -> list[tuple[float, Game]]:
    """Classe les jeux par ressemblance avec une requete parlee.

    Trois signaux combines : titre exact, requete contenue dans le titre
    (pour "euro truck" -> "Euro Truck Simulator 2"), et distance d'edition
    pour absorber les erreurs de transcription.
    """
    games = games if games is not None else all_games()
    q = canon(query)
    if not q:
        return []

    scored = []
    for g in games:
        name = canon(g.name)
        if name == q:
            score = 1.0
        elif q in name:
            # Bonus si la requete couvre une grande part du titre.
            score = 0.80 + 0.15 * (len(q) / max(len(name), 1))
        elif all(word in name for word in q.split()):
            score = 0.75
        else:
            score = difflib.SequenceMatcher(None, q, name).ratio()
        scored.append((round(score, 3), g))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for item in scored if item[0] >= 0.45]


def uri_desinstallation(jeu: "Game") -> str:
    """L'URI qui ouvre la desinstallation du launcher, si elle existe.

    Chaque launcher gere ses propres fichiers : passer par lui plutot que par
    Windows garantit que la bibliotheque reste coherente et que le jeu peut
    etre reinstalle sans retelecharger ce qui reste sur le disque.
    """
    if jeu.launcher == "steam":
        return f"steam://uninstall/{jeu.game_id}"
    if jeu.launcher == "epic":
        return f"com.epicgames.launcher://apps/{jeu.game_id}?action=uninstall"
    if jeu.launcher == "ubisoft":
        return f"uplay://uninstall/{jeu.game_id}"
    return ""


def desinstaller(nom: str, ask=None) -> str:
    """Ouvre la desinstallation du jeu, apres accord explicite.

    On n'efface RIEN nous-memes. Supprimer les fichiers a la main laisserait
    le launcher persuade que le jeu est installe, et la reinstallation
    echouerait de facon incomprehensible. On ouvre donc la desinstallation
    officielle, et c'est elle qui agit.

    Contrairement a la frappe au clavier, celle-ci demande confirmation : on
    parle de dizaines de gigaoctets a retelecharger.
    """
    from assistant import safety

    correspondances = find(nom)
    if not correspondances:
        return f"Aucun jeu installe ne ressemble a \"{nom}\"."
    if len(correspondances) > 1 and correspondances[1][0] > correspondances[0][0] - 0.08:
        options = ", ".join(g.name for _, g in correspondances[:4])
        return f"Plusieurs jeux correspondent : {options}. Lequel ?"

    jeu = correspondances[0][1]
    taille = (f"{jeu.size_bytes / 1e9:.1f} Go"
              if jeu.size_bytes else "taille inconnue")

    action = safety.Action(
        kind="jeu",
        summary=f"Desinstaller {jeu.name} ({taille})",
        targets=[f"jeu: {jeu.name} — {jeu.launcher}"],
        reversible=False,
        details=f"Le desinstalleur de {jeu.launcher} va s'ouvrir. "
                f"Reinstaller demandera de retelecharger {taille}.",
    )
    try:
        safety.guard(action, ask=ask)
    except safety.Refused as exc:
        return str(exc)

    uri = uri_desinstallation(jeu)
    try:
        if uri:
            os.startfile(uri)
            return (f"Desinstallation de {jeu.name} ouverte dans "
                    f"{jeu.launcher}. Confirme dans sa fenetre.")
        subprocess.Popen(["explorer.exe", "ms-settings:appsfeatures"])
        return (f"{jeu.launcher} ne propose pas de desinstallation directe. "
                "J'ai ouvert la liste des applications installees : "
                f"cherches-y {jeu.name}.")
    except OSError as exc:
        return f"Ouverture impossible : {exc}"


def launch(query: str) -> tuple[bool, str]:
    """Lance le jeu qui correspond le mieux.

    Renvoie (succes, message). En cas d'ambiguite reelle (deux candidats
    proches), ne lance rien et rend la liste : lancer le mauvais jeu par
    erreur de transcription est plus penible que de redemander.
    """
    matches = find(query)
    if not matches:
        return False, f"Aucun jeu installe ne ressemble a \"{query}\"."

    best_score, best = matches[0]
    if len(matches) > 1 and matches[1][0] > best_score - 0.08:
        options = ", ".join(g.name for _, g in matches[:4])
        return False, f"Plusieurs jeux correspondent : {options}. Lequel ?"

    try:
        if best.exe:
            subprocess.Popen([best.exe, *(best.args or [])])
        else:
            os.startfile(best.uri)
    except OSError as exc:
        return False, f"Echec du lancement de {best.name} : {exc}"
    return True, f"Lancement de {best.name} via {best.launcher}."
