"""Etat de la machine et diagnostics de lenteur.

Le principe directeur : une moyenne cache les problemes. Un processus qui
sature un seul coeur d'un Ryzen 8 coeurs n'apparait qu'a 12 % de CPU global,
alors qu'il peut rendre la machine desagreable. On regarde donc toujours le
detail par coeur et par processus, jamais la seule moyenne.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field

import psutil

from assistant import config
from assistant.util import human_size

# Empeche Windows d'ouvrir une console pour les programmes appeles en fond.
CREATE_NO_WINDOW = 0x08000000

# Un processus au-dela de ce seuil occupe l'essentiel d'un coeur. Volontairement
# sous 100 % : un processus qui oscille autour de 90 gene autant qu'un a 100,
# et l'echantillonnage de psutil bruite la mesure de quelques points.
CORE_SATURATION = 70.0

# Pseudo-processus qui comptabilisent le temps *inoccupe* : les inclure dans un
# classement CPU donne un premier de la liste a 1300 %, ce qui ne veut rien dire.
NOT_REAL_LOAD = {"system idle process", "idle"}

# En dessous de cette taille, une partition est un volume systeme (reserve au
# demarrage, recuperation) : son espace libre n'a aucune signification.
MIN_MEANINGFUL_DISK = 50 * 1024**3

# Processus connus pour saturer un coeur sans raison, avec le remede.
KNOWN_OFFENDERS = {
    "audiodg.exe": (
        "Moteur audio Windows. Quand il tourne a fond en continu, c'est "
        "presque toujours un effet audio active sur le peripherique de sortie. "
        "Remede : Parametres son > proprietes du peripherique > desactiver "
        "les ameliorations audio / l'audio spatial."
    ),
    "searchindexer.exe": (
        "Indexation Windows Search. Pic normal apres une grosse copie, "
        "anormal s'il dure des heures."
    ),
    "wmiprvse.exe": (
        "Fournisseur WMI. Une boucle infinie ici vient souvent d'un logiciel "
        "de monitoring materiel (RGB, ventilation)."
    ),
    "msmpeng.exe": (
        "Antivirus Defender. Exclure les dossiers de projets Unreal et les "
        "bibliotheques de jeux fait gagner enormement en compilation."
    ),
    "dwm.exe": (
        "Compositeur de bureau. Une charge continue vient souvent d'un ecran "
        "en frequence variable ou d'un pilote graphique instable."
    ),
}


@dataclass
class Snapshot:
    cpu_overall: float
    cpu_per_core: list[float]
    ram_used: int
    ram_total: int
    ram_percent: float
    disks: list[dict] = field(default_factory=list)
    gpu: dict | None = None
    top_cpu: list[dict] = field(default_factory=list)
    top_ram: list[dict] = field(default_factory=list)
    uptime_hours: float = 0.0


def gpu_info() -> dict | None:
    """Etat du GPU via nvidia-smi. None si absent (machine AMD/Intel)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    query = (
        "name,temperature.gpu,utilization.gpu,memory.used,memory.total,"
        "power.draw,clocks.current.graphics"
    )
    try:
        out = subprocess.run(
            [exe, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, check=True,
            # Sans ce drapeau, nvidia-smi ouvre une fenetre de console a
            # chaque appel. Invisible depuis un terminal, tres visible depuis
            # l'application : le releve GPU est refait au demarrage, a chaque
            # ouverture de "Etat en direct" et a chaque diagnostic.
            creationflags=CREATE_NO_WINDOW,
        ).stdout.strip().splitlines()[0]
    except (subprocess.SubprocessError, OSError, IndexError):
        return None

    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 7:
        return None

    def num(value: str) -> float:
        try:
            return float(value)
        except ValueError:
            return 0.0

    return {
        "name": parts[0],
        "temp_c": num(parts[1]),
        "usage_percent": num(parts[2]),
        "vram_used_mb": num(parts[3]),
        "vram_total_mb": num(parts[4]),
        "power_w": num(parts[5]),
        "clock_mhz": num(parts[6]),
    }


def snapshot(sample_seconds: float = 1.0) -> Snapshot:
    """Photographie de la machine.

    psutil a besoin de deux mesures espacees pour donner un pourcentage CPU
    qui veut dire quelque chose : le premier appel amorce, le second mesure.
    """
    psutil.cpu_percent(percpu=True)
    for proc in psutil.process_iter():
        try:
            proc.cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(sample_seconds)

    per_core = psutil.cpu_percent(percpu=True)
    mem = psutil.virtual_memory()

    procs = []
    for proc in psutil.process_iter(["name", "pid", "memory_info"]):
        try:
            cpu = proc.cpu_percent()
            info = proc.info
            if (info.get("name") or "").lower() in NOT_REAL_LOAD:
                continue
            procs.append(
                {
                    "name": info.get("name") or "?",
                    "pid": info.get("pid"),
                    "cpu": round(cpu, 1),
                    "ram": (info.get("memory_info").rss if info.get("memory_info") else 0),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        if usage.total < MIN_MEANINGFUL_DISK:
            continue
        disks.append(
            {
                "drive": part.device.rstrip("\\"),
                "total": usage.total,
                "free": usage.free,
                "percent": usage.percent,
            }
        )

    return Snapshot(
        cpu_overall=round(sum(per_core) / max(len(per_core), 1), 1),
        cpu_per_core=[round(c, 1) for c in per_core],
        ram_used=mem.used,
        ram_total=mem.total,
        ram_percent=mem.percent,
        disks=disks,
        gpu=gpu_info(),
        top_cpu=sorted(procs, key=lambda p: p["cpu"], reverse=True)[:8],
        top_ram=sorted(procs, key=lambda p: p["ram"], reverse=True)[:8],
        uptime_hours=round((time.time() - psutil.boot_time()) / 3600, 1),
    )


def core_hogs(sample_seconds: float = 2.0) -> list[dict]:
    """Processus qui saturent un coeur entier.

    C'est le diagnostic qu'une moyenne CPU ne peut pas donner : sur 16
    threads, un processus a 100 % d'un coeur ne pese que 6 % du total.
    """
    psutil.cpu_percent()
    watched = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            proc.cpu_percent()
            watched.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(sample_seconds)

    hogs = []
    for proc in watched:
        try:
            cpu = proc.cpu_percent()
            name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if cpu < CORE_SATURATION or name.lower() in NOT_REAL_LOAD:
            continue
        hogs.append(
            {
                "name": name,
                "pid": proc.pid,
                "cpu_of_one_core": round(cpu, 1),
                "cores_equivalent": round(cpu / 100, 2),
                "known": KNOWN_OFFENDERS.get(name.lower(), ""),
            }
        )
    return sorted(hogs, key=lambda h: h["cpu_of_one_core"], reverse=True)


def _detailler_demarrage(nom: str, commande: str, source: str) -> dict:
    """Complete une entree de demarrage avec ce qu'on peut en apprendre.

    Le nom d'une entree de registre ne dit souvent rien ("RzAppEngine").
    L'executable vise, son editeur, sa taille et son existence reelle
    permettent a l'utilisateur de decider s'il peut la desactiver.
    """
    import os
    import re as _re

    chemin = ""
    trouve = _re.search(r'"([^"]+\.exe)"|(\S+\.exe)', commande, _re.IGNORECASE)
    if trouve:
        chemin = (trouve.group(1) or trouve.group(2) or "").strip('"')

    existe = bool(chemin) and os.path.isfile(chemin)
    # Les applications du Microsoft Store vivent dans WindowsApps, un dossier
    # que Windows protege : Python n'y voit rien meme quand le fichier existe.
    # Le dire "introuvable" serait faux et inquietant.
    protege = bool(chemin) and not existe and "windowsapps" in chemin.lower()
    taille = 0
    if existe:
        try:
            taille = os.path.getsize(chemin)
        except OSError:
            taille = 0
    # L'editeur est renseigne apres coup, en un seul appel pour toute la
    # liste : le demander fichier par fichier lancait quatorze processus
    # PowerShell et le panneau mettait quinze secondes a s'ouvrir.
    editeur = ""

    return {
        "name": nom,
        "command": commande,
        "source": source,
        "exe": chemin,
        "exists": existe,
        "size": taille,
        "publisher": editeur,
        "protected": protege,
        "running": _tourne(chemin),
    }


def _editeurs(chemins: list[str]) -> dict[str, str]:
    """Editeur declare de plusieurs fichiers, en UN seul appel.

    Lancer un processus PowerShell par fichier coutait environ une seconde
    chacun : sur quatorze programmes de demarrage, le panneau mettait quinze
    secondes a s'afficher. Ici tout passe dans un appel, sous la seconde.
    """
    chemins = [c for c in chemins if c]
    if not chemins:
        return {}

    liste = ",".join("'" + c.replace("'", "''") + "'" for c in chemins)
    commande = (
        f"@({liste}) | ForEach-Object {{ "
        "$i = Get-Item -LiteralPath $_ -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ p = $_; c = if ($i) "
        "{ $i.VersionInfo.CompanyName } else { '' } } } | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             commande],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=0x08000000,
        )
        brut = (completed.stdout or "").strip()
        if not brut:
            return {}
        import json

        donnees = json.loads(brut)
        if isinstance(donnees, dict):
            donnees = [donnees]
        return {d.get("p", ""): (d.get("c") or "").strip() for d in donnees}
    except (subprocess.SubprocessError, OSError, ValueError):
        return {}


def _tourne(chemin: str) -> bool:
    """Le programme est-il en cours d'execution maintenant ?"""
    if not chemin:
        return False
    cible = os.path.basename(chemin).lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info.get("name") or "").lower() == cible:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def startup_items() -> list[dict]:
    """Programmes lances au demarrage de Windows (registre + dossier Demarrage)."""
    import winreg
    from pathlib import Path

    items = []
    reg_roots = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM32"),
    ]
    for hive, path, label in reg_roots:
        try:
            with winreg.OpenKey(hive, path) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    items.append(_detailler_demarrage(name, str(value), label))
        except OSError:
            continue

    startup_dir = Path.home() / (
        r"AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"
    )
    if startup_dir.is_dir():
        for entry in startup_dir.iterdir():
            if entry.name.lower() != "desktop.ini":
                items.append(_detailler_demarrage(
                    entry.stem, str(entry), "Dossier Demarrage"))

    editeurs = _editeurs([i["exe"] for i in items if i.get("exists")])
    for item in items:
        item["publisher"] = editeurs.get(item.get("exe", ""), "")
    return items


def network_rates(sample_seconds: float = 0.6) -> dict:
    """Debit reseau instantane, en octets par seconde.

    Deux mesures espacees : un compteur cumulatif ne dit rien tout seul.
    """
    avant = psutil.net_io_counters()
    time.sleep(sample_seconds)
    apres = psutil.net_io_counters()
    return {
        "recu": (apres.bytes_recv - avant.bytes_recv) / sample_seconds,
        "envoye": (apres.bytes_sent - avant.bytes_sent) / sample_seconds,
        "total_recu": apres.bytes_recv,
        "total_envoye": apres.bytes_sent,
    }


def disk_rates(sample_seconds: float = 0.6) -> dict:
    """Activite disque instantanee."""
    avant = psutil.disk_io_counters()
    if avant is None:
        return {}
    time.sleep(sample_seconds)
    apres = psutil.disk_io_counters()
    return {
        "lecture": (apres.read_bytes - avant.read_bytes) / sample_seconds,
        "ecriture": (apres.write_bytes - avant.write_bytes) / sample_seconds,
    }


def _barre(pourcent: float, largeur: int = 20) -> str:
    """Petite barre en texte : un chiffre seul se compare mal a dix autres."""
    rempli = int(round(max(0.0, min(pourcent, 100.0)) / 100 * largeur))
    return "#" * rempli + "." * (largeur - rempli)


def report(sample_seconds: float = 1.0) -> str:
    """Etat detaille de la machine, tel qu'on le lit dans le panneau."""
    snap = snapshot(sample_seconds)
    L = ["ETAT DE LA MACHINE EN DIRECT", ""]

    # --- Processeur, coeur par coeur
    L.append("PROCESSEUR")
    L.append("-" * 10)
    L.append(f"  Charge globale   {snap.cpu_overall:5.1f} %   "
             f"{_barre(snap.cpu_overall)}")
    try:
        frequence = psutil.cpu_freq()
        if frequence and frequence.current:
            L.append(f"  Frequence        {frequence.current / 1000:.2f} GHz")
    except Exception:  # noqa: BLE001
        pass
    L.append("")
    for index, charge in enumerate(snap.cpu_per_core):
        alerte = "  <-- sature" if charge >= CORE_SATURATION else ""
        L.append(f"    coeur {index:<2} {charge:5.1f} %  {_barre(charge, 24)}{alerte}")

    # --- Memoire
    L.append("")
    L.append("MEMOIRE")
    L.append("-" * 7)
    L.append(f"  Utilisee         {snap.ram_percent:5.1f} %   "
             f"{_barre(snap.ram_percent)}")
    L.append(f"                   {human_size(snap.ram_used)} sur "
             f"{human_size(snap.ram_total)}")
    L.append(f"  Libre            {human_size(snap.ram_total - snap.ram_used)}")
    try:
        echange = psutil.swap_memory()
        if echange.total:
            L.append(f"  Fichier d'echange {echange.percent:.0f} %   "
                     f"{human_size(echange.used)} sur {human_size(echange.total)}")
    except Exception:  # noqa: BLE001
        pass

    # --- Carte graphique
    if snap.gpu:
        g = snap.gpu
        L.append("")
        L.append("CARTE GRAPHIQUE")
        L.append("-" * 15)
        L.append(f"  {g['name']}")
        L.append(f"  Charge           {g['usage_percent']:5.1f} %   "
                 f"{_barre(g['usage_percent'])}")
        vram = 100 * g["vram_used_mb"] / max(g["vram_total_mb"], 1)
        L.append(f"  Memoire video    {vram:5.1f} %   {_barre(vram)}")
        L.append(f"                   {g['vram_used_mb']:.0f} Mo sur "
                 f"{g['vram_total_mb']:.0f} Mo")
        L.append(f"  Temperature      {g['temp_c']:.0f} C")
        L.append(f"  Consommation     {g['power_w']:.0f} W")
        if g.get("clock_mhz"):
            L.append(f"  Frequence        {g['clock_mhz']:.0f} MHz")

    # --- Disques
    L.append("")
    L.append("DISQUES")
    L.append("-" * 7)
    for d in snap.disks:
        occupe = d["percent"]
        L.append(f"  {d['drive']:<4} {occupe:5.1f} % occupe  {_barre(occupe)}")
        L.append(f"       {human_size(d['free'])} libres sur "
                 f"{human_size(d['total'])}")
    activite = disk_rates()
    if activite:
        L.append(f"  Activite         lecture {human_size(activite['lecture'])}/s   "
                 f"ecriture {human_size(activite['ecriture'])}/s")

    # --- Reseau
    reseau = network_rates()
    L.append("")
    L.append("RESEAU")
    L.append("-" * 6)
    L.append(f"  Debit            recu {human_size(reseau['recu'])}/s   "
             f"envoye {human_size(reseau['envoye'])}/s")
    L.append(f"  Depuis l'allumage  recu {human_size(reseau['total_recu'])}   "
             f"envoye {human_size(reseau['total_envoye'])}")

    # --- Processus
    L.append("")
    L.append("PROCESSUS LES PLUS GOURMANDS")
    L.append("-" * 28)
    L.append("  Par processeur")
    for p in snap.top_cpu[:8]:
        L.append(f"     {p['cpu']:6.1f} %  {human_size(p['ram']):>10}  "
                 f"{p['name']}  (pid {p['pid']})")
    L.append("")
    L.append("  Par memoire")
    for p in snap.top_ram[:8]:
        L.append(f"     {human_size(p['ram']):>10}  {p['cpu']:5.1f} %  "
                 f"{p['name']}  (pid {p['pid']})")

    try:
        total = len(psutil.pids())
        L.append("")
        L.append(f"  {total} processus au total")
    except Exception:  # noqa: BLE001
        pass

    L.append("")
    L.append(f"  Machine allumee depuis {snap.uptime_hours} h")
    return "\n".join(L)


def diagnose() -> str:
    """Cherche activement ce qui ralentit la machine, et le dit en clair."""
    findings = []

    hogs = core_hogs()
    for h in hogs:
        line = (
            f"  [!] {h['name']} occupe {h['cores_equivalent']} coeur(s) en continu "
            f"({h['cpu_of_one_core']} % d'un coeur, pid {h['pid']})"
        )
        if h["known"]:
            line += f"\n      -> {h['known']}"
        findings.append(line)

    snap = snapshot(0.5)
    for d in snap.disks:
        if d["total"] < MIN_MEANINGFUL_DISK:
            continue
        if d["free"] < 20 * 1024**3:
            findings.append(
                f"  [!] {d['drive']} n'a plus que {human_size(d['free'])} libres. "
                "Windows et les jeux se degradent nettement sous 20 Go."
            )

    if snap.ram_percent > 88:
        findings.append(
            f"  [!] RAM a {snap.ram_percent:.0f} %. Le systeme va commencer a "
            "swapper sur le disque, ce qui se sent immediatement."
        )

    if snap.gpu and snap.gpu["temp_c"] > 83:
        findings.append(
            f"  [!] GPU a {snap.gpu['temp_c']:.0f} C : la carte va se brider. "
            "Verifie le flux d'air et les courbes de ventilation."
        )

    if snap.uptime_hours > 168:
        findings.append(
            f"  [.] Machine allumee depuis {snap.uptime_hours / 24:.0f} jours. "
            "Un redemarrage libere souvent de la memoire fragmentee."
        )

    starts = startup_items()
    if len(starts) > 12:
        findings.append(
            f"  [.] {len(starts)} programmes se lancent au demarrage. "
            "Demande-moi la liste pour faire le tri."
        )

    if not findings:
        return "Rien d'anormal. Aucun coeur sature, disques et memoire au vert."
    return "Diagnostic :\n" + "\n".join(findings)
