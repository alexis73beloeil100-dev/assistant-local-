"""Profil materiel et detection de problemes, sur n'importe quel PC.

Aucune valeur n'est codee pour une machine donnee : tout vient du releve
systeme (probe.ps1). Le logiciel doit decouvrir la configuration de la
machine sur laquelle il est installe, quelle qu'elle soit.

Le releve complet coute environ 7 secondes, dominees par la lecture du
journal d'evenements. Il est donc fait une fois au demarrage, en tache de
fond, puis conserve en memoire pour la duree de la session.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from assistant.util import human_size

def _probe_path() -> Path:
    """Localise probe.ps1, en source comme dans l'executable packagee.

    PyInstaller depose les fichiers de donnees dans _MEIPASS. On teste les
    deux emplacements plutot que de supposer : une erreur ici ferait perdre
    tout le diagnostic materiel, silencieusement.
    """
    voisin = Path(__file__).resolve().parent / "probe.ps1"
    if voisin.is_file():
        return voisin
    base = getattr(sys, "_MEIPASS", None)
    if base:
        embarque = Path(base) / "assistant" / "skills" / "probe.ps1"
        if embarque.is_file():
            return embarque
    return voisin


PROBE = _probe_path()
PROBE_TIMEOUT = 90

# Un peripherique en code 24 est declare mais absent : c'est le cas normal
# des ports PS/2 sur une carte mere moderne, pas une panne.
HARMLESS_DEVICE_CODES = {24}

# Sources d'evenements REELLEMENT actionnables, et rien d'autre.
#
# C'est une liste blanche, volontairement. Une liste noire de bruit ne marche
# pas : Windows en bonne sante ecrit chaque semaine des dizaines d'erreurs
# DCOM, DeviceAssociation, Hyper-V ou Kernel-Boot qui n'ont aucune
# consequence. Les afficher revient a inventer des problemes sur une machine
# qui va bien, et l'utilisateur cesse alors de faire confiance au diagnostic.
#
# Chaque entree : (gravite, seuil d'occurrences, explication, remede).
ACTIONABLE_EVENTS = {
    "disk": (
        "GRAVE", 1,
        "Erreur de lecture ou d'ecriture sur un disque.",
        "Sauvegarde tes donnees et verifie l'etat SMART du disque "
        "immediatement. C'est le signe le plus fiable d'un disque qui lache.",
    ),
    "ntfs": (
        "GRAVE", 1,
        "Erreur de systeme de fichiers.",
        "Lance une verification du disque : chkdsk C: /f dans une invite "
        "administrateur. Peut annoncer un disque defaillant.",
    ),
    # Volsnap et storahci ratent ponctuellement sans que rien n'aille mal :
    # une sauvegarde interrompue, un disque externe debranche. Seule la
    # repetition est significative.
    "volsnap": (
        "A SURVEILLER", 3,
        "Erreurs repetees sur les cliches instantanes (points de restauration).",
        "Generalement un disque sature. Si l'espace libre est correct, "
        "verifie l'etat SMART du disque concerne.",
    ),
    "storahci": (
        "GRAVE", 2,
        "Erreurs repetees du controleur de stockage.",
        "Verifie le cable SATA ou l'etat du disque.",
    ),
    "whea-logger": (
        "GRAVE", 1,
        "Erreur materielle detectee par le processeur.",
        "Souvent un overclocking instable, un profil XMP trop agressif ou une "
        "alimentation insuffisante. Repasse en reglages par defaut pour "
        "confirmer.",
    ),
    "bugcheck": (
        "GRAVE", 1,
        "Ecran bleu.",
        "Le fichier de vidage memoire contient la cause exacte. "
        "C:\\Windows\\Minidump",
    ),
    "kernel-power": (
        "A SURVEILLER", 2,
        "Arret brutal de la machine, sans extinction propre.",
        "Coupure de courant, plantage, ou surchauffe. Si cela se repete, "
        "suspecte l'alimentation ou la temperature.",
    ),
    "microsoft-windows-wer-systemerrorreporting": (
        "A SURVEILLER", 2,
        "Le systeme a redemarre apres une erreur critique.",
        "A rapprocher des ecrans bleus si tu en as constate.",
    ),
}

# Sources connues pour etre bruyantes sur une machine parfaitement saine.
# Documentees ici pour qu'on ne soit pas tente de les rajouter un jour.
KNOWN_NOISE = {
    "microsoft-windows-distributedcom",      # delais d'enregistrement COM
    "microsoft-windows-deviceassociationservice",
    "microsoft-windows-hyper-v-hypervisor",  # normal si Hyper-V est desactive
    "microsoft-windows-kernel-boot",         # messages VBS/hyperviseur
    "service control manager",               # services de jeux qui se relancent
    "application error",                     # un programme qui plante
    "application hang",
    "tpm",                                   # fTPM bavard chez AMD, sans effet
    "microsoft-windows-time-service",
    "microsoft-windows-dhcp-client",
    "microsoft-windows-dns-client",
}

_profile: dict | None = None
_lock = threading.Lock()
_error = ""


# --- Releve -----------------------------------------------------------------

def _powershell() -> str:
    return "powershell.exe"


def collect(force: bool = False) -> dict:
    """Execute le releve systeme et rend le dictionnaire complet."""
    global _profile, _error

    with _lock:
        if _profile is not None and not force:
            return _profile

        if not PROBE.exists():
            _error = f"Script de releve introuvable : {PROBE}"
            return {}

        import tempfile

        # Le releve s'ecrit dans un fichier UTF-8 plutot que sur la sortie
        # standard : l'encodage d'un tuyau Windows detruit les accents des
        # messages du journal systeme.
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            destination = fh.name

        try:
            result = subprocess.run(
                [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(PROBE), "-Destination", destination],
                capture_output=True, text=True, timeout=PROBE_TIMEOUT,
                encoding="utf-8", errors="replace",
                creationflags=0x08000000,  # pas de fenetre de console
            )
            raw = Path(destination).read_text(encoding="utf-8").strip()
        except (subprocess.SubprocessError, OSError) as exc:
            _error = f"Releve impossible : {type(exc).__name__}: {exc}"
            return {}
        finally:
            try:
                Path(destination).unlink()
            except OSError:
                pass

        if not raw:
            _error = f"Releve vide. {(result.stderr or '')[:200]}"
            return {}

        try:
            _profile = json.loads(raw)
        except json.JSONDecodeError as exc:
            _error = f"Releve illisible : {exc}"
            return {}

        _profile["collected_at"] = time.strftime("%Y-%m-%d %H:%M")
        return _profile


def collect_in_background(on_done=None) -> threading.Thread:
    """Lance le releve sans bloquer l'ouverture de la fenetre."""
    def work():
        data = collect()
        if on_done:
            on_done(data)

    thread = threading.Thread(target=work, name="machine-probe", daemon=True)
    thread.start()
    return thread


def ready() -> bool:
    return _profile is not None


# --- Presentation -----------------------------------------------------------

def _age_jours(date_texte: str | None) -> int | None:
    """Nombre de jours depuis une date au format AAAA-MM-JJ."""
    if not date_texte:
        return None
    from datetime import date

    try:
        annee, mois, jour = (int(x) for x in date_texte.split("-"))
        return (date.today() - date(annee, mois, jour)).days
    except (ValueError, TypeError):
        return None


def _bloc(titre: str) -> list[str]:
    return ["", titre, "-" * len(titre)]


def profile() -> str:
    """Fiche technique complete de la machine.

    Volontairement detaillee : quand on demande "ma configuration", on attend
    ce qu'un technicien releverait, pas trois lignes. Chaque section ne
    s'affiche que si la machine a quelque chose a y mettre -- un fixe n'a pas
    de batterie, une machine sans carte dediee n'a pas de pilote a dater.
    """
    data = collect()
    if not data:
        return _error or "Releve indisponible."

    os_ = data.get("os", {})
    machine = data.get("machine", {})
    cpu = data.get("cpu", {})

    L = ["CONFIGURATION DE LA MACHINE"]

    # --- Machine
    L += _bloc("MACHINE")
    fabricant = f"{machine.get('manufacturer','?')} {machine.get('model','')}".strip()
    L.append(f"  Modele         {fabricant}")
    L.append(f"  Carte mere     {machine.get('board','?')}")
    bios_age = _age_jours(machine.get("bios_date"))
    bios = f"{machine.get('bios','?')}  du {machine.get('bios_date','?')}"
    if bios_age is not None:
        bios += f"  ({bios_age // 30} mois)"
    L.append(f"  BIOS           {bios}")

    # --- Processeur
    L += _bloc("PROCESSEUR")
    L.append(f"  Modele         {str(cpu.get('name') or '?').strip()}")
    L.append(f"  Coeurs         {cpu.get('cores','?')} physiques, "
             f"{cpu.get('threads','?')} logiques")
    if cpu.get("max_mhz"):
        actuel = cpu.get("current_mhz") or 0
        ligne = f"  Frequence      {cpu['max_mhz'] / 1000:.2f} GHz nominale"
        if actuel:
            ligne += f", {actuel / 1000:.2f} GHz a l'instant"
        L.append(ligne)

    # --- Memoire
    L += _bloc("MEMOIRE")
    ram = data.get("ram") or []
    total = sum(m.get("capacity_gb") or 0 for m in ram)
    L.append(f"  Installee      {total or machine.get('ram_gb','?')} Go")

    slots = data.get("memory_slots") or {}
    if slots.get("total"):
        libres = (slots["total"] or 0) - (slots.get("utilises") or 0)
        ligne = (f"  Emplacements   {slots.get('utilises','?')} occupes sur "
                 f"{slots['total']}")
        if libres > 0:
            ligne += f", {libres} libre(s)"
        if slots.get("max_gb"):
            ligne += f"  (max {slots['max_gb']} Go)"
        L.append(ligne)

    for module in ram:
        vitesse = module.get("speed_mhz") or 0
        nominale = module.get("max_mhz") or 0
        detail = f"{vitesse} MHz" if vitesse else "? MHz"
        if nominale and vitesse and vitesse < nominale * 0.95:
            detail += f"  (bridee, la barrette accepte {nominale})"
        L.append(f"  {str(module.get('slot','?')):<14} "
                 f"{module.get('capacity_gb','?')} Go a {detail}")
        if module.get("part"):
            L.append(f"                 reference {module['part']}")

    # --- Graphique
    L += _bloc("GRAPHIQUE")
    for carte in data.get("gpu") or []:
        L.append(f"  Carte          {carte.get('name','?')}")
        age = _age_jours(carte.get("driver_date"))
        pilote = f"{carte.get('driver','?')}  du {carte.get('driver_date','?')}"
        if age is not None:
            pilote += f"  ({age} jours)"
            if age > 365:
                pilote += "  -- ancien"
        L.append(f"  Pilote         {pilote}")

    for mode in data.get("resolutions") or []:
        L.append(f"  Affichage      {mode.get('resolution','?')} a "
                 f"{mode.get('hz','?')} Hz")

    ecrans = data.get("monitors") or []
    for ecran in ecrans:
        pouces = ecran.get("pouces")
        taille = f"  {pouces} pouces" if pouces else ""
        L.append(f"  Ecran          {ecran.get('nom','?')}{taille}")

    # --- Stockage
    L += _bloc("STOCKAGE")
    volumes = {v.get("letter"): v for v in (data.get("volumes") or [])}
    par_disque: dict[int, list] = {}
    for partition in data.get("disk_layout") or []:
        par_disque.setdefault(partition.get("disque"), []).append(partition)

    for index, disque in enumerate(data.get("physical_disks") or []):
        # On rattache par le numero que Windows donne au disque, pas par
        # l'ordre d'enumeration : les deux ne coincident pas, et s'y fier
        # affichait C: sur le disque SATA alors qu'il vit sur le NVMe.
        numero = disque.get("numero")
        if numero is None:
            numero = index
        etat = disque.get("health", "?")
        marque = "" if str(etat).lower() == "healthy" else f"  <-- {etat}"
        L.append(f"  Disque {numero}       {disque.get('name','?')}")
        detail = (f"                 {disque.get('size_gb','?')} Go  "
                  f"{disque.get('media','?')}  {disque.get('bus','?')}  "
                  f"etat {etat}{marque}")
        L.append(detail)
        usure = disque.get("wear_percent")
        temp = disque.get("temperature")
        extras = []
        if isinstance(usure, (int, float)):
            extras.append(f"usure {usure} %")
        if isinstance(temp, (int, float)):
            extras.append(f"{temp} C")
        if extras:
            L.append("                 " + ", ".join(extras))

        for partition in par_disque.get(numero, []):
            lettre = partition.get("lettre")
            vol = volumes.get(lettre, {})
            libre = vol.get("free_gb") or 0
            taille = vol.get("size_gb") or partition.get("taille") or 1
            # Les partitions systeme de quelques centaines de Mo n'apprennent
            # rien et brouillent la lecture.
            if taille < 20:
                continue
            part = 100 * libre / taille if taille else 0
            etiquette = vol.get("label") or ""
            L.append(f"                 {lettre}:  {libre:.0f} Go libres sur "
                     f"{taille:.0f} Go  ({part:.0f} % libre)  {etiquette}".rstrip())

    # Volumes qu'on n'a pas su rattacher a un disque physique.
    rattaches = {p.get("lettre") for liste in par_disque.values() for p in liste}
    for lettre, vol in volumes.items():
        if lettre in rattaches or (vol.get("size_gb") or 0) < 20:
            continue
        L.append(f"  Volume {lettre}:      {vol.get('free_gb',0):.0f} Go libres "
                 f"sur {vol.get('size_gb',0):.0f} Go  {vol.get('label','')}".rstrip())

    # --- Reseau
    reseaux = data.get("network") or []
    if reseaux:
        L += _bloc("RESEAU")
        for carte in reseaux:
            L.append(f"  {str(carte.get('nom','?')):<14} "
                     f"{carte.get('type','?')}")
            details = []
            if carte.get("ip"):
                details.append(f"IP {carte['ip']}")
            if carte.get("vitesse"):
                details.append(str(carte["vitesse"]))
            if carte.get("mac"):
                details.append(f"MAC {carte['mac']}")
            if details:
                L.append("                 " + "   ".join(details))

    # --- Windows
    L += _bloc("WINDOWS")
    L.append(f"  Edition        {os_.get('caption','?')}")
    L.append(f"  Version        {os_.get('version','?')}  "
             f"build {os_.get('build','?')}  {os_.get('architecture','')}")
    activation = data.get("activation")
    if activation:
        L.append(f"  Activation     {activation}")
    installe = os_.get("installed")
    age_install = _age_jours(installe)
    ligne = f"  Installe le    {installe or '?'}"
    if age_install is not None:
        ligne += f"  (il y a {age_install} jours)"
    L.append(ligne)
    heures = data.get("uptime_hours")
    demarrage = f"  Demarre le     {os_.get('last_boot','?')}"
    if isinstance(heures, (int, float)):
        demarrage += (f"  (allume depuis {heures / 24:.1f} jours)"
                      if heures >= 24 else f"  (allume depuis {heures} h)")
    L.append(demarrage)

    # --- Batterie
    batterie = data.get("battery") or {}
    if batterie.get("charge") is not None:
        L += _bloc("BATTERIE")
        L.append(f"  Charge         {batterie['charge']} %")

    L.append("")
    L.append(f"Releve du {data.get('collected_at','?')}. "
             "Bouton Actualiser pour refaire la mesure.")
    return "\n".join(L)


# --- Diagnostic -------------------------------------------------------------

def _severity_sort(items: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    ordre = {"GRAVE": 0, "A SURVEILLER": 1, "INFO": 2}
    return sorted(items, key=lambda x: ordre.get(x[0], 3))


def problems() -> str:
    """Passe la machine en revue et rapporte ce qui ne va pas.

    Les regles sont generiques : elles s'appliquent a n'importe quelle
    configuration, sans rien savoir a l'avance du materiel installe.
    """
    data = collect()
    if not data:
        return _error or "Releve indisponible."

    trouve: list[tuple[str, str, str]] = []

    # --- disques : le seul poste ou une panne detruit des donnees
    for disque in data.get("physical_disks") or []:
        etat = str(disque.get("health") or "").lower()
        nom = disque.get("name", "disque")
        if etat and etat != "healthy":
            trouve.append((
                "GRAVE",
                f"Disque {nom} : etat {disque.get('health')}",
                "Sauvegarde tes donnees maintenant. Un disque signale comme "
                "degrade par Windows peut lacher sans autre avertissement.",
            ))
        usure = disque.get("wear_percent")
        if isinstance(usure, (int, float)) and usure > 80:
            trouve.append((
                "A SURVEILLER",
                f"Disque {nom} use a {usure} %",
                "Les cellules d'un SSD ont une duree de vie limitee. "
                "Au-dela de 80 %, prevois son remplacement.",
            ))
        temp = disque.get("temperature")
        if isinstance(temp, (int, float)) and temp > 70:
            trouve.append((
                "A SURVEILLER",
                f"Disque {nom} a {temp} C",
                "Un NVMe qui depasse 70 C se bride. Verifie le dissipateur "
                "et le flux d'air.",
            ))

    # --- espace libre
    for vol in data.get("volumes") or []:
        taille = vol.get("size_gb") or 0
        libre = vol.get("free_gb") or 0
        if taille < 20:          # partition systeme, sans signification
            continue
        part = 100 * libre / taille
        if libre < 10 or part < 5:
            trouve.append((
                "GRAVE",
                f"Volume {vol.get('letter')}: presque plein "
                f"({libre:.0f} Go libres, {part:.0f} %)",
                "Windows a besoin d'espace pour le fichier d'echange et les "
                "mises a jour. En dessous de ce seuil, le systeme devient "
                "instable.",
            ))
        elif libre < 25 or part < 10:
            trouve.append((
                "A SURVEILLER",
                f"Volume {vol.get('letter')}: bientot plein "
                f"({libre:.0f} Go libres, {part:.0f} %)",
                "Demande-moi ce qui prend de la place, je peux faire le tri.",
            ))
        if str(vol.get("health") or "").lower() not in ("healthy", ""):
            trouve.append((
                "GRAVE",
                f"Volume {vol.get('letter')}: etat {vol.get('health')}",
                "Lance une verification du disque (chkdsk).",
            ))

    # --- memoire : une barrette sous sa vitesse nominale est frequent
    ram = data.get("ram") or []
    lents = [m for m in ram
             if m.get("speed_mhz") and m.get("max_mhz")
             and m["speed_mhz"] < m["max_mhz"] * 0.95]
    if lents:
        module = lents[0]
        trouve.append((
            "INFO",
            f"RAM a {module['speed_mhz']} MHz alors qu'elle peut monter a "
            f"{module['max_mhz']} MHz",
            "Le profil XMP / EXPO n'est pas active dans le BIOS. Tu perds "
            "des performances que tu as deja payees.",
        ))

    capacites = {m.get("capacity_gb") for m in ram if m.get("capacity_gb")}
    if len(capacites) > 1:
        trouve.append((
            "INFO",
            f"Barrettes de tailles differentes ({', '.join(f'{c} Go' for c in sorted(capacites))})",
            "Le double canal fonctionne en mode degrade sur la partie non "
            "appariee. Sans gravite, mais c'est de la bande passante perdue.",
        ))

    # --- processeur bride
    cpu = data.get("cpu", {})
    if cpu.get("max_mhz") and cpu.get("current_mhz"):
        if cpu["current_mhz"] < cpu["max_mhz"] * 0.6:
            trouve.append((
                "A SURVEILLER",
                f"CPU a {cpu['current_mhz']} MHz sur {cpu['max_mhz']} possibles",
                "Bridage thermique, mode d'economie d'energie, ou limite "
                "d'alimentation. Verifie le mode de gestion de l'alimentation "
                "de Windows.",
            ))

    # --- peripheriques en erreur
    casses = [d for d in (data.get("bad_devices") or [])
              if d.get("code") not in HARMLESS_DEVICE_CODES]
    for device in casses[:5]:
        trouve.append((
            "A SURVEILLER",
            f"Peripherique en erreur : {device.get('name')} (code "
            f"{device.get('code')})",
            "Pilote absent, en conflit, ou materiel qui ne demarre pas. "
            "Voir le Gestionnaire de peripheriques.",
        ))

    # --- journal d'evenements : uniquement ce qui est actionnable
    #
    # On ne rapporte QUE les sources de ACTIONABLE_EVENTS, et seulement
    # au-dela de leur seuil. Tout le reste est ignore en silence : une
    # machine saine produit en permanence des erreurs DCOM, Hyper-V ou TPM
    # qui ne veulent rien dire, et les afficher revient a inventer des
    # problemes sur un PC qui va bien.
    for evenement in (data.get("events") or []):
        source = str(evenement.get("source") or "").lower()
        nombre = evenement.get("count") or 0

        regle = None
        for cle, valeur in ACTIONABLE_EVENTS.items():
            if cle in source:
                regle = valeur
                break
        if regle is None:
            continue

        gravite, seuil, explication, remede = regle
        if nombre < seuil:
            continue

        trouve.append((
            gravite,
            f"{nombre} erreur(s) {evenement.get('source')} en 7 jours "
            f"(derniere : {evenement.get('last')}) - {explication}",
            remede,
        ))

    # --- etat general de Windows
    if data.get("reboot_pending"):
        trouve.append((
            "INFO",
            "Un redemarrage est en attente",
            "Des mises a jour ne s'appliqueront qu'apres redemarrage. Cela "
            "explique quantite de comportements erratiques.",
        ))

    defender = data.get("defender") or {}
    if defender.get("realtime") is False:
        trouve.append((
            "GRAVE",
            "Protection en temps reel desactivee",
            "La machine n'est pas protegee.",
        ))
    age = defender.get("signature_age")
    if isinstance(age, (int, float)) and age > 7:
        trouve.append((
            "A SURVEILLER",
            f"Signatures antivirus vieilles de {age:.0f} jours",
            "Lance une mise a jour de la protection.",
        ))

    # Un reglage perfectible n'est pas une panne. Les melanger ferait
    # ressembler une machine saine a une machine malade.
    problemes = [item for item in trouve if item[0] != "INFO"]
    optimisations = [item for item in trouve if item[0] == "INFO"]

    lignes = []
    if not problemes:
        lignes.append("Aucun probleme detecte.")
        lignes.append("Disques, materiel et Windows sont sains. Les erreurs "
                      "courantes du journal Windows (DCOM, Hyper-V, TPM...) "
                      "sont ignorees volontairement : une machine en bon etat "
                      "en produit en permanence sans consequence.")
    else:
        problemes = _severity_sort(problemes)
        graves = sum(1 for g, _, _ in problemes if g == "GRAVE")
        lignes.append(
            f"{len(problemes)} probleme(s)"
            + (f", dont {graves} grave(s)" if graves else "")
            + " :"
        )
        lignes.append("")
        for gravite, titre, remede in problemes:
            lignes.append(f"  [{gravite}] {titre}")
            lignes.append(f"      -> {remede}")
            lignes.append("")

    if optimisations:
        lignes.append("")
        lignes.append("Ce ne sont pas des pannes, mais tu peux y gagner :")
        lignes.append("")
        for _gravite, titre, remede in optimisations:
            lignes.append(f"  {titre}")
            lignes.append(f"      -> {remede}")
            lignes.append("")

    return "\n".join(lignes).rstrip()


def summary() -> str:
    """Resume d'une ligne, pour l'affichage compact de la barre laterale."""
    data = collect()
    if not data:
        return "releve en cours"
    cpu = str(data.get("cpu", {}).get("name") or "").strip()
    gpu = (data.get("gpu") or [{}])[0].get("name", "")
    ram = data.get("machine", {}).get("ram_gb", "?")
    return f"{cpu} | {ram} Go | {gpu}"
