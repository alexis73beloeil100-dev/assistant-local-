"""Panneaux d'information : les donnees deja connues, affichees directement.

La configuration de la machine, ses problemes, les jeux, l'espace disque sont
releves au demarrage et tenus en memoire. Les faire passer par le modele de
langage pour qu'il les reformule serait deux fois absurde : c'est lent, et un
modele qui recopie des chiffres finit toujours par en deformer un.

Le modele reste indispensable pour les questions libres. Pour ce qui est
deja su, on affiche.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Panel:
    key: str
    label: str
    subtitle: str
    build: Callable[[], str]
    # True = le contenu peut changer d'une seconde a l'autre (charge CPU),
    # donc on le recalcule a chaque ouverture au lieu de le garder en cache.
    live: bool = False
    # Nom d'un panneau interactif : il affiche de vrais widgets (cases a
    # cocher, boutons) au lieu de texte. Le texte reste utilisable par le
    # modele de langage, l'interface prend l'autre chemin.
    interactif: str = ""



# Les lignes precedees de ce marqueur sont cliquables dans la fenetre : un
# clic les envoie comme si l'utilisateur les avait tapees. C'est ce qui evite
# a quelqu'un qui decouvre l'application de rester devant un champ vide sans
# savoir quel vocabulaire elle comprend.
EXEMPLE = ">> "


def _accueil() -> str:
    from assistant.skills import games, hardware

    lignes = [
        "BIENVENUE",
        "",
        "Cet assistant connait ta machine et agit dessus. Tout tourne en",
        "local : rien de ce que tu dis ou de ce qu'il lit ne quitte ce PC.",
        "",
    ]

    # On montre ce qu'il a deja appris de CETTE machine : c'est plus
    # convaincant qu'une promesse, et ca prouve que le relevé a fonctionne.
    resume = hardware.summary()
    if resume and "en cours" not in resume:
        lignes += ["  Il a deja relevé :", f"    {resume}", ""]
    try:
        nombre = len(games.all_games())
        if nombre:
            lignes += [f"    {nombre} jeux installes, tous launchers confondus", ""]
    except Exception:  # noqa: BLE001
        pass

    lignes += [
        "",
        "DEUX FACONS DE S'EN SERVIR",
        "",
        "  1. Les menus a gauche, pour consulter. Un clic, affichage immediat.",
        "  2. La conversation, pour demander. Tape, ou clique le bouton Parler",
        "     puis reclique sur Terminer quand tu as fini de parler.",
        "",
        "",
        "ESSAIE — clique une ligne, elle part comme si tu l'avais tapee",
        "",
        "  Connaitre la machine",
        f"{EXEMPLE}Quelle est la configuration de ce PC ?",
        f"{EXEMPLE}Y a-t-il des problemes sur mon PC ?",
        f"{EXEMPLE}Pourquoi mon PC rame ?",
        "",
        "  Trouver des fichiers",
        f"{EXEMPLE}Qu'est-ce qui prend le plus de place sur mon disque ?",
        f"{EXEMPLE}Qu'est-ce qu'il y a sur mon Bureau ?",
        f"{EXEMPLE}Trouve mes fichiers modifies aujourd'hui",
        "",
        "  Piloter le PC",
        f"{EXEMPLE}Monte le son a 50 pour cent",
        f"{EXEMPLE}Ouvre le gestionnaire des taches",
        f"{EXEMPLE}Quelle est mon adresse IP ?",
        "",
        "  Jeux",
        f"{EXEMPLE}Quels jeux sont installes ?",
        f"{EXEMPLE}Prepare-moi pour jouer",
        "",
        "  Ne pas oublier",
        f"{EXEMPLE}Mets un minuteur de 20 minutes",
        f"{EXEMPLE}Previens-moi quand le GPU depasse 80 degres",
        "",
        "",
        "CE QU'IL NE FERA JAMAIS SANS TE DEMANDER",
        "",
        "  Lire ta machine, tes fichiers, ton materiel : il le fait librement.",
        "  Modifier quoi que ce soit : il te montre l'action et attend ton",
        "  accord. Pour une commande Windows, tu vois le texte exact.",
        "",
        "  Certaines choses sont refusees meme si tu insistes : formater un",
        "  disque, effacer les points de restauration, couper l'antivirus.",
        "",
        "  Tout est ecrit dans le menu \"Journal des actions\", accepte comme",
        "  refuse.",
        "",
        "",
        "SI QUELQUE CHOSE NE MARCHE PAS",
        "",
        "  Ouvre le menu \"Autotest\" : il verifie onze points et dit, pour",
        "  chacun, ce qui manque et quoi faire.",
        "",
        "  Le micro n'ecrit rien ? Clique \"Tester le micro\" en bas a gauche.",
        "  S'il affiche \"muet\", choisis-en un autre dans la liste au-dessus.",
    ]
    return "\n".join(lignes)


def _configuration() -> str:
    from assistant.skills import hardware

    return hardware.profile()


def _problemes() -> str:
    from assistant.skills import hardware

    return hardware.problems()


def _etat() -> str:
    from assistant.skills import system

    return system.report()


def _lenteurs() -> str:
    from assistant.skills import system

    return system.diagnose()


def _jeux() -> str:
    from assistant.skills import games
    from assistant.util import human_size

    trouves = games.all_games()
    if not trouves:
        return ("Aucun jeu detecte.\n\n"
                "Sont reconnus : Steam, Epic, Ubisoft, EA et Riot.\n"
                "Si un jeu manque, c'est que son launcher n'expose pas son "
                "installation la ou l'assistant regarde.")

    total = sum(j.size_bytes for j in trouves)
    L = ["JEUX INSTALLES", ""]
    L.append(f"  {len(trouves)} jeux" +
             (f", {human_size(total)} au total" if total else ""))

    par_launcher: dict[str, list] = {}
    for jeu in trouves:
        par_launcher.setdefault(jeu.launcher, []).append(jeu)

    for launcher, jeux in sorted(par_launcher.items()):
        poids = sum(j.size_bytes for j in jeux)
        L.append("")
        entete = f"{launcher.upper()}  ({len(jeux)} jeux"
        entete += f", {human_size(poids)})" if poids else ")"
        L.append(entete)
        L.append("-" * len(entete))
        for jeu in sorted(jeux, key=lambda j: -j.size_bytes):
            taille = human_size(jeu.size_bytes) if jeu.size_bytes else "taille inconnue"
            L.append(f"  {jeu.name}")
            L.append(f"      {taille}")
            if jeu.install_dir:
                L.append(f"      {jeu.install_dir}")
            L.append(f"      identifiant {jeu.game_id}")

    L.append("")
    L.append("Dis \"lance <nom>\" pour en demarrer un, ou \"mode jeu avec "
             "<nom>\" pour")
    L.append("preparer la machine avant de lancer.")
    return "\n".join(L)


def _espace() -> str:
    from assistant.index import db
    from assistant.skills import cleanup, files

    if not db.is_ready():
        return ("Le scan des fichiers est encore en cours.\n"
                "Cette page sera disponible dans quelques secondes.")

    morceaux = [files.index_status(), ""]
    morceaux.append(cleanup.report())
    return "\n".join(morceaux)


def _fichiers() -> str:
    from assistant.index import db, watcher
    from assistant.skills import files
    from assistant.util import human_size

    if not db.is_ready():
        return ("Le scan des fichiers est encore en cours.\n"
                "Cette page sera disponible dans quelques secondes.")

    L = ["CONNAISSANCE DES FICHIERS", ""]
    L.append(files.index_status())
    L.append("")
    L.append("  " + watcher.status())
    L.append("")
    L.append("  Rien n'est ecrit sur le disque : cet index vit en memoire vive")
    L.append("  et disparait a la fermeture de l'application.")

    # Repartition par type : ce qui compose vraiment un disque.
    conn = db.connect()
    try:
        types = conn.execute(
            "SELECT ext, COUNT(*) AS n, SUM(size) AS poids FROM files "
            "WHERE is_dir = 0 AND ext != '' GROUP BY ext "
            "ORDER BY poids DESC LIMIT 15"
        ).fetchall()
        dossiers = conn.execute(
            "SELECT parent, COUNT(*) AS n FROM files WHERE is_dir = 0 "
            "GROUP BY parent ORDER BY n DESC LIMIT 10"
        ).fetchall()
        par_disque = conn.execute(
            "SELECT drive, COUNT(*) AS n, SUM(size) AS poids FROM files "
            "WHERE is_dir = 0 GROUP BY drive ORDER BY poids DESC"
        ).fetchall()
    except Exception:  # noqa: BLE001
        types, dossiers, par_disque = [], [], []
    finally:
        conn.close()

    if par_disque:
        L += ["", "REPARTITION PAR DISQUE", "-" * 22]
        for ligne in par_disque:
            L.append(f"  {ligne['drive']:<4} {ligne['n']:>9,} fichiers   "
                     f"{human_size(ligne['poids'] or 0):>12}".replace(",", " "))

    if types:
        L += ["", "TYPES DE FICHIERS LES PLUS LOURDS", "-" * 33]
        for ligne in types:
            L.append(f"  .{str(ligne['ext']):<10} {ligne['n']:>8,} fichiers   "
                     f"{human_size(ligne['poids'] or 0):>12}".replace(",", " "))

    if dossiers:
        L += ["", "DOSSIERS QUI CONTIENNENT LE PLUS DE FICHIERS", "-" * 44]
        for ligne in dossiers:
            L.append(f"  {ligne['n']:>7,} fichiers   {ligne['parent'][:78]}"
                     .replace(",", " "))

    L += ["", "MODIFIES RECEMMENT", "-" * 18, files.recent(limit=15)]
    return "\n".join(L)


def _espace() -> str:
    from assistant.index import db
    from assistant.skills import cleanup, files
    from assistant.util import human_size

    if not db.is_ready():
        return ("Le scan des fichiers est encore en cours.\n"
                "Cette page sera disponible dans quelques secondes.")

    L = ["ESPACE DISQUE", ""]

    # Etat reel des volumes, avant de parler de ce qu'on peut recuperer.
    try:
        import psutil

        from assistant import config

        for racine in config.SCAN_ROOTS:
            usage = psutil.disk_usage(racine)
            occupe = usage.percent
            barre = "#" * int(occupe / 5) + "." * (20 - int(occupe / 5))
            L.append(f"  {racine[:2]}  {occupe:5.1f} % occupe  {barre}")
            L.append(f"      {human_size(usage.free)} libres sur "
                     f"{human_size(usage.total)}")
    except Exception:  # noqa: BLE001
        pass

    L += ["", files.index_status(), ""]

    # Ce qui pese, dossier de premier niveau par dossier de premier niveau.
    conn = db.connect()
    try:
        from assistant import config

        for racine in config.SCAN_ROOTS:
            gros = db.dir_sizes(conn, racine, limit=12)
            if not gros:
                continue
            titre = f"CE QUI PESE SUR {racine[:2]}"
            L += ["", titre, "-" * len(titre)]
            total = sum(r["total"] for r in gros) or 1
            for ligne in gros:
                part = 100 * ligne["total"] / total
                barre = "#" * int(part / 5)
                L.append(f"  {human_size(ligne['total']):>12}  {part:5.1f} % "
                         f"{barre:<20} {ligne['bucket']}")
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()

    L += ["", "", cleanup.report()]
    return "\n".join(L)


def _demarrage() -> str:
    from assistant.skills import fixes, system
    from assistant.util import human_size

    items = system.startup_items()
    actifs = sum(1 for i in items if i.get("running"))
    manquants = [i for i in items
                 if i.get("exe") and not i.get("exists")
                 and not i.get("protected")]

    L = ["PROGRAMMES LANCES AVEC WINDOWS", ""]
    L.append(f"  {len(items)} entrees, dont {actifs} en cours d'execution")
    if manquants:
        L.append(f"  {len(manquants)} pointent vers un fichier absent")
    L.append("")

    for item in items:
        etat = "en cours" if item.get("running") else "arrete"
        L.append(f"  {item['name']}   [{etat}]")
        if item.get("publisher"):
            L.append(f"      editeur      {item['publisher']}")
        if item.get("exe"):
            note = ""
            if not item.get("exists"):
                note = ("   (dossier protege, non verifiable)"
                        if item.get("protected")
                        else "   (INTROUVABLE : entree orpheline, sans effet)")
            L.append(f"      fichier      {item['exe']}{note}")
            if item.get("exists") and item.get("size"):
                L.append(f"      taille       {human_size(item['size'])}")
        L.append(f"      origine      {item['source']}")
        L.append("")

    L.append(fixes.desactivations())
    L.append("")
    L.append("Dis \"desactive <nom> au demarrage\" pour en retirer un.")
    L.append("La commande exacte est conservee : c'est reversible a tout moment.")
    return "\n".join(L)


def _autotest() -> str:
    from assistant import selftest

    return selftest.report()


def _correctifs() -> str:
    from assistant.skills import fixes

    return fixes.disponibles()



def _controle() -> str:
    from assistant.skills import control

    return control.status()


def _applications() -> str:
    from assistant.skills import apps

    return apps.liste()


def _alertes() -> str:
    from assistant.skills import reminders

    return "\n".join([
        "MINUTEURS ET SURVEILLANCES",
        "",
        reminders.liste(),
        "",
        "Ce que l'assistant sait surveiller :",
        "  la temperature du GPU        \"previens-moi si le GPU depasse 80 degres\"",
        "  la charge du processeur      \"previens-moi si le CPU depasse 90 %\"",
        "  l'espace disque              \"previens-moi quand C: passe sous 20 Go\"",
        "  la fin d'un programme        \"previens-moi quand steam est ferme\"",
        "  la fin d'un telechargement   \"previens-moi quand C:\\...\\fichier.zip est fini\"",
    ])


def _mode_jeu() -> str:
    from assistant.skills import gamemode

    return gamemode.apercu()


def _notes() -> str:
    from assistant.skills import desk

    return "\n".join([
        desk.notes(limite=30),
        "",
        "Dis \"note ...\" pour en ajouter une, \"mes notes\" pour les relire.",
    ])


def _commandes() -> str:
    from assistant.skills import shell

    return shell.explique()


def _journal() -> str:
    from assistant import safety

    entrees = safety.history(40)
    if not entrees:
        return ("Aucune action enregistree.\n\n"
                "Toute modification de la machine est journalisee ici, "
                "acceptee comme refusee.")

    acceptees = sum(1 for e in entrees if e.get("verdict", "").startswith("accepte"))
    refusees = len(entrees) - acceptees

    lignes = [
        "JOURNAL DES ACTIONS",
        "",
        f"  {len(entrees)} derniere(s) action(s) : {acceptees} acceptee(s), "
        f"{refusees} refusee(s)",
        "",
    ]
    for entree in reversed(entrees):
        verdict = entree.get("verdict", "?")
        marque = "OK " if verdict.startswith("accepte") else "NON"
        lignes.append(f"  [{marque}] {entree.get('at','')}  "
                      f"[{entree.get('kind','')}] {entree.get('summary','')}")
        for cible in (entree.get("targets") or [])[:3]:
            lignes.append(f"          {str(cible)[:96]}")
    lignes.append("")
    lignes.append("Fichier complet : data/logs/actions.jsonl")
    return "\n".join(lignes)


PANELS: list[Panel] = [
    Panel("accueil", "Par ou commencer",
          "ce qu'il sait faire, avec des exemples", _accueil),
    Panel("configuration", "Ma configuration",
          "carte mere, CPU, RAM, GPU, disques, Windows", _configuration),
    Panel("problemes", "Problemes detectes",
          "disques, materiel, journal Windows", _problemes),
    Panel("etat", "Etat en direct",
          "charge CPU par coeur, RAM, GPU, processus", _etat, live=True),
    Panel("lenteurs", "Pourquoi ca rame",
          "ce qui sature la machine maintenant", _lenteurs, live=True),
    Panel("jeux", "Mes jeux", "tous launchers confondus", _jeux),
    Panel("espace", "Espace disque", "ce qui prend de la place", _espace),
    Panel("fichiers", "Mes fichiers", "index et surveillance", _fichiers),
    Panel("demarrage", "Demarrage de Windows",
          "cocher ce qui se lance avec la session", _demarrage,
          interactif="startup"),
    Panel("correctifs", "Ce que je peux reparer",
          "actions disponibles", _correctifs),
    Panel("controle", "Controle du PC",
          "volume, sortie audio, alimentation", _controle, live=True),
    Panel("applications", "Mes applications",
          "tout ce qui peut etre ouvert", _applications),
    Panel("modejeu", "Mode jeu",
          "preparer la machine avant de jouer", _mode_jeu, live=True),
    Panel("alertes", "Minuteurs et alertes",
          "rappels et surveillances", _alertes, live=True),
    Panel("notes", "Mes notes", "ce que tu as dicte", _notes, live=True),
    Panel("commandes", "Commandes Windows",
          "ce qui est autorise et refuse", _commandes),
    Panel("journal", "Journal des actions",
          "tout ce qui a ete fait ou refuse", _journal, live=True),
    Panel("autotest", "Autotest", "verifier que tout fonctionne", _autotest),
]

BY_KEY = {p.key: p for p in PANELS}

# Contenus deja calcules, pour que la deuxieme ouverture soit instantanee.
_cache: dict[str, str] = {}


def content(key: str, force: bool = False) -> str:
    panel = BY_KEY.get(key)
    if panel is None:
        return f"Panneau inconnu : {key}"
    if panel.live or force or key not in _cache:
        try:
            _cache[key] = panel.build()
        except Exception as exc:  # noqa: BLE001
            return f"Erreur pendant la preparation : {type(exc).__name__}: {exc}"
    return _cache[key]


def is_ready(key: str) -> bool:
    """Le panneau est-il deja calcule ? Evite d'afficher "Preparation" pour
    rien quand le contenu est en cache."""
    return key in _cache


def prime(keys: list[str] | None = None) -> None:
    """Prepare les panneaux a l'avance, pour qu'ils s'ouvrent sans attendre."""
    for panel in PANELS:
        if panel.live:
            continue
        if keys and panel.key not in keys:
            continue
        try:
            _cache[panel.key] = panel.build()
        except Exception:  # noqa: BLE001
            continue


def invalidate(key: str | None = None) -> None:
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)
