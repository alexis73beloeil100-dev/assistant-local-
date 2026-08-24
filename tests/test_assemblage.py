"""Verifie que les pieces sont bien reliees entre elles.

Les tests de regression figent des defauts connus. Ceux-ci verifient les
contrats : chaque outil est appelable, chaque panneau se construit, chaque
garde-fou refuse ce qu'il doit refuser.

C'est cette serie qui aurait attrape le defaut le plus grave du projet : la
demande de confirmation lisait sur l'entree standard, absente d'une
application fenetree, et toutes les actions plantaient avant d'etre proposees.
"""
from __future__ import annotations

import pytest


# --- Le catalogue d'outils ---------------------------------------------------

def test_chaque_outil_a_un_schema_valide():
    from assistant import llm

    assert len(llm.TOOLS) > 40, "le catalogue s'est vide"
    noms = set()
    for outil in llm.TOOLS:
        schema = outil.schema()
        assert schema["type"] == "function"
        fonction = schema["function"]
        assert fonction["name"] == outil.name
        assert fonction["description"].strip(), f"{outil.name} sans description"
        assert fonction["parameters"]["type"] == "object"
        for requis in fonction["parameters"].get("required", []):
            assert requis in fonction["parameters"]["properties"], (
                f"{outil.name} exige {requis} sans le declarer")
        assert outil.name not in noms, f"{outil.name} en double"
        noms.add(outil.name)


def test_les_outils_qui_agissent_sont_marques():
    """Un outil non marque ne peut pas etre simule pendant les tests.

    C'est ce marquage qui evite qu'un test lance un jeu ou supprime un
    fichier chez l'utilisateur.
    """
    from assistant import llm

    doivent_agir = {
        "executer_commande", "lancer_jeu", "nettoyer", "arreter_processus",
        "desactiver_programme_demarrage", "reactiver_programme_demarrage",
        "redemarrer_service", "vider_cache", "ouvrir_application",
        "fermer_application", "regler_volume", "changer_volume",
        "couper_son", "changer_sortie_audio", "profil_alimentation",
        "verrouiller_session", "mettre_en_veille", "eteindre_ou_redemarrer",
        "mode_jeu", "quitter_mode_jeu", "copier", "enregistrer_capture",
        "ouvrir_dans_explorateur", "annuler_arret",
        "lecture_media", "taper_au_clavier", "ouvrir_reglage_windows",
        "desinstaller_jeu", "oublier",
    }
    marques = {o.name for o in llm.TOOLS if o.effect}
    manquants = doivent_agir - marques
    assert not manquants, f"outils agissants non marques : {manquants}"


def test_un_outil_qui_agit_est_neutralise_en_simulation():
    from assistant import llm

    resultat = llm.dispatch("lancer_jeu", {"nom": "assetto"}, dry_run=True)
    assert resultat.startswith("[simulation]")


def test_un_outil_inconnu_ne_leve_pas():
    from assistant import llm

    assert "inconnu" in llm.dispatch("outil_qui_n_existe_pas", {}).lower()


def test_des_arguments_invalides_ne_levent_pas():
    """Une erreur d'outil doit revenir au modele comme du texte."""
    from assistant import llm

    resultat = llm.dispatch("chercher_fichier", {"parametre_inexistant": 1})
    assert isinstance(resultat, str) and resultat


# --- Les garde-fous ----------------------------------------------------------

def test_un_chemin_protege_est_refuse_meme_avec_un_accord():
    from assistant import safety

    action = safety.Action(
        kind="fichier",
        summary="Supprimer un dossier systeme",
        targets=["C:\\Windows\\System32"],
    )
    with pytest.raises(safety.Refused):
        safety.guard(action, ask=lambda _texte: True)


def test_sans_moyen_de_demander_l_action_est_refusee():
    """Le defaut le plus grave du projet.

    La demande de confirmation lisait sur l'entree standard. Dans une
    application fenetree il n'y en a pas : l'appel levait "lost sys.stdin" et
    l'action plantait. Elle doit desormais etre refusee proprement.
    """
    from assistant import safety

    def impossible(_texte):
        raise RuntimeError("lost sys.stdin")

    action = safety.Action(kind="registre", summary="Action de test",
                           targets=["HKCU\\Test"])
    with pytest.raises(safety.Refused):
        safety.guard(action, ask=impossible)


def test_un_refus_de_l_utilisateur_arrete_l_action():
    from assistant import safety

    action = safety.Action(kind="registre", summary="Action de test",
                           targets=["HKCU\\Test"])
    with pytest.raises(safety.Refused):
        safety.guard(action, ask=lambda _texte: False)


def test_un_accord_laisse_passer():
    from assistant import safety

    action = safety.Action(kind="registre", summary="Action de test",
                           targets=["HKCU\\Test"])
    assert safety.guard(action, ask=lambda _texte: True) is True


def test_les_processus_systeme_ne_sont_jamais_arretes():
    from assistant.skills import fixes

    for nom in ("lsass.exe", "csrss.exe", "explorer.exe", "winlogon.exe"):
        resultat = fixes.arreter_processus(nom, ask=lambda _t: True)
        assert not resultat.ok, nom
        assert "systeme" in resultat.message.lower()


def test_les_services_critiques_ne_sont_jamais_redemarres():
    from assistant.skills import fixes

    for nom in ("RpcSs", "DcomLaunch", "EventLog"):
        resultat = fixes.redemarrer_service(nom, ask=lambda _t: True)
        assert not resultat.ok, nom


# --- Les panneaux ------------------------------------------------------------

def test_chaque_panneau_se_construit_sans_lever():
    """Un panneau qui leve laisse l'utilisateur devant un ecran vide."""
    from assistant import panels

    assert len(panels.PANELS) >= 15
    for panneau in panels.PANELS:
        contenu = panels.content(panneau.key)
        assert isinstance(contenu, str)
        assert contenu.strip(), f"{panneau.key} rend un contenu vide"
        assert "Erreur pendant la preparation" not in contenu, panneau.key


def test_les_cles_de_panneaux_sont_uniques():
    from assistant import panels

    cles = [p.key for p in panels.PANELS]
    assert len(cles) == len(set(cles))


def test_l_accueil_propose_des_exemples_cliquables():
    from assistant import panels

    contenu = panels.content("accueil")
    exemples = [l for l in contenu.splitlines() if l.startswith(panels.EXEMPLE)]
    assert len(exemples) >= 8, "l'accueil doit guider un nouvel utilisateur"


# --- Les competences ---------------------------------------------------------

def test_le_catalogue_d_applications_se_construit():
    from assistant.skills import apps

    catalogue = apps.catalogue()
    assert catalogue, "aucune application detectee"
    assert all(a.nom and a.cible for a in catalogue)


def test_la_detection_de_jeux_ne_leve_pas():
    from assistant.skills import games

    for jeu in games.all_games():
        assert jeu.name and jeu.launcher and jeu.game_id


def test_un_fichier_binaire_n_est_pas_lu_comme_du_texte():
    from assistant.skills import content

    assert content.kind("photo.png") == "binaire"
    assert content.kind("notes.txt") == "text"
    assert content.kind("rapport.pdf") == "rich"


def test_une_image_est_reconnue_comme_telle():
    from assistant.skills import vision

    assert vision.is_image("capture.png")
    assert vision.is_image("PHOTO.JPG")
    assert not vision.is_image("document.pdf")


# --- L'autotest --------------------------------------------------------------

def test_l_autotest_couvre_les_points_essentiels():
    from assistant import selftest

    noms = [nom for nom, _fonction, _essentiel in selftest.VERIFICATIONS]
    assert len(noms) >= 10
    essentiels = [nom for nom, _f, essentiel in selftest.VERIFICATIONS if essentiel]
    assert "Releve materiel" in essentiels
    assert "Disques" in essentiels


# --- Le panneau affiche, joint a la conversation -----------------------------
#
# Les panneaux et la conversation s'ignoraient : le modele n'avait aucune idee
# de ce qui etait affiche. Ces contrats verifient que la passerelle tient.

def test_un_panneau_consulte_devient_du_contexte():
    from assistant import panels

    panels._cache["problemes"] = "PROBLEMES DETECTES\n\n  [GRAVE] Disque plein"
    joint = panels.contexte("problemes")

    assert joint is not None
    libelle, contenu = joint
    assert libelle == panels.BY_KEY["problemes"].label
    assert "Disque plein" in contenu


def test_un_panneau_jamais_ouvert_ne_declenche_aucun_calcul():
    """contexte() ne doit lire que le cache.

    Sinon une question sans rapport declencherait un releve materiel de six
    secondes, simplement parce que l'utilisateur a effleure un menu.
    """
    from assistant import panels

    panels._cache.pop("autotest", None)
    assert panels.contexte("autotest") is None


def test_l_accueil_n_est_jamais_joint():
    """C'est un mode d'emploi, pas une donnee sur la machine.

    Ses lignes d'exemple pourraient en plus etre prises pour des consignes.
    """
    from assistant import panels

    panels._cache["accueil"] = "BIENVENUE\n>> Quelle est la configuration ?"
    assert panels.contexte("accueil") is None


def test_un_panneau_trop_long_est_coupe_par_le_bas():
    """Les panneaux mettent l'essentiel en tete : on garde la tete."""
    from assistant import panels

    panels._cache["espace"] = "DEBUT IMPORTANT\n" + ("x" * panels.CONTEXTE_MAX * 2)
    joint = panels.contexte("espace")

    assert joint is not None
    _libelle, contenu = joint
    assert contenu.startswith("DEBUT IMPORTANT")
    assert len(contenu) < panels.CONTEXTE_MAX + 200


def test_le_contexte_est_presente_comme_une_donnee():
    """Un panneau affiche du texte venu d'ailleurs -- noms de fichiers,
    messages du journal Windows. Il ne doit jamais etre lu comme une consigne.
    """
    from assistant import llm

    message = llm.message_de_contexte("Problemes detectes", "  [GRAVE] rien")

    assert message["role"] == "system"
    assert "DONNEE" in message["content"]
    assert message["content"].startswith(llm.CONTEXTE_MARQUEUR)


def test_le_contexte_est_remplace_et_jamais_empile():
    """Cinq questions devant le meme panneau ne doivent pas laisser cinq
    copies de son contenu dans l'historique."""
    from assistant import llm

    convo = [{"role": "system", "content": "regles"}]
    for _ in range(5):
        convo = llm.sans_contexte(convo)
        convo.append(llm.message_de_contexte("Mes jeux", "un jeu"))
        convo.append({"role": "user", "content": "et alors ?"})

    contextes = [m for m in convo
                 if str(m.get("content", "")).startswith(llm.CONTEXTE_MARQUEUR)]
    assert len(contextes) == 1
    assert convo[0]["content"] == "regles", "le message systeme doit survivre"


def test_le_modele_sait_qu_il_peut_se_servir_du_panneau():
    """Sans cette regle, il rappelle l'outil pour retrouver ce qu'il a deja."""
    from assistant import llm

    assert "panneau" in llm.SYSTEM_PROMPT


# --- L'eclairage RGB, toutes marques ------------------------------------------

def test_le_pilotage_rgb_ne_connait_aucune_marque():
    """Il doit marcher sur la machine de n'importe qui.

    Lire le profil de RGB Fusion aurait pilote une seule carte mere, d'une
    seule marque. Et ca n'aurait meme pas marche : ce fichier n'a pas bouge
    d'un octet pendant qu'on changeait de mode a l'ecran -- le reglage part
    directement dans le controleur, il n'y a rien a intercepter.
    """
    import inspect

    from assistant.skills import rgb

    source = inspect.getsource(rgb)
    # Aucun chemin ni format proprietaire ne doit servir de cible.
    for interdit in ("Pro1.xml", "GIGABYTE\\RGBFusion", "Pattern_Type",
                     "Area_info"):
        assert interdit not in source, f"{interdit} : pilotage lie a une marque"


def test_les_modes_rgb_sont_decouverts_et_non_listes_en_dur():
    """Chaque materiel offre ses propres modes : les figer serait faux
    partout ailleurs.

    Mesure sur cette machine -- la carte mere en propose sept, la carte
    graphique six, la souris cinq, et aucune liste ne recoupe l'autre.
    """
    import inspect

    from assistant.skills import rgb

    source = inspect.getsource(rgb)
    for en_dur in ("COLOR CYCLE", "Digital Wave", "DOUBLE FLASH",
                   "Spectrum Cycle", "Breathing"):
        assert en_dur not in source


def test_aucun_module_gpl_n_est_importe():
    """Un seul import ramenait la GPLv3 sur le programme entier.

    openrgb-python est sous GPLv3. L'importer, c'est lier : le binaire
    distribue devait alors se transmettre sous GPLv3, avec son code source.
    Le pilotage passe desormais par openrgb_protocole, ecrit pour ce projet.

    Ce test existe parce que la rechute est facile et muette : un `from
    openrgb import ...` ajoute pour depanner marcherait parfaitement -- la
    bibliotheque reste installee dans le .venv -- et remettrait l'obligation
    sans que rien ne signale quoi que ce soit.
    """
    import re
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    coupable = re.compile(r"^\s*(from\s+openrgb|import\s+openrgb)", re.M)

    fautifs = []
    for fichier in (racine / "assistant").rglob("*.py"):
        if coupable.search(fichier.read_text(encoding="utf-8", errors="replace")):
            fautifs.append(str(fichier.relative_to(racine)))

    assert not fautifs, (
        f"openrgb-python (GPLv3) est de nouveau importe par : {fautifs}. "
        "Le programme distribue redevient GPLv3, et le code source doit "
        "repartir avec lui")


def test_le_client_rgb_maison_lit_les_champs_que_le_pilotage_utilise():
    """Le protocole binaire a piege QUATRE fois un client ecrit a la main.

    Le pire : le nombre de LED ressortait a zero sans lever d'erreur. Or sans
    lui, impossible d'ecrire les couleurs -- et changer le mode ne suffit pas
    sur une carte mere. La souris et la carte graphique suivaient, la carte
    mere restait muette. Deux peripheriques sur trois, ce qui ressemblait a un
    probleme de materiel plutot qu'a une erreur d'analyse.

    Sans materiel sous la main, on ne peut pas rejouer un echange. Ce qu'on
    verifie ici, c'est que les champs dont rgb.py se sert existent bien et
    qu'aucun renommage ne les a fait disparaitre en silence -- l'autre facon
    d'obtenir un zero qui ne leve rien.
    """
    from assistant.skills import openrgb_protocole as protocole

    for champ in ("index", "nom", "genre", "modes", "mode_actif", "nb_leds",
                  "couleurs"):
        assert champ in protocole.Materiel.__dataclass_fields__, (
            f"Materiel.{champ} a disparu : rgb.py s'en sert")

    for champ in ("index", "nom", "drapeaux", "vitesse", "vitesse_min",
                  "vitesse_max", "luminosite", "luminosite_min",
                  "luminosite_max", "mode_couleur", "couleurs_max", "brut"):
        assert champ in protocole.Mode.__dataclass_fields__, (
            f"Mode.{champ} a disparu : rgb.py s'en sert")

    # Les valeurs relevees sur l'enumeration du SDK. Les ecrire de memoire
    # avait mis la luminosite au bit 7 au lieu du bit 4 : rien ne plantait,
    # un curseur apparaissait juste la ou il n'avait rien a faire.
    assert protocole.A_VITESSE == 1
    assert protocole.A_LUMINOSITE == 16
    assert protocole.A_COULEUR_PAR_LED == 32
    assert protocole.A_COULEUR_DE_MODE == 64
    assert protocole.COULEUR_PAR_LED == 1
    assert protocole.COULEUR_DE_MODE == 2


def test_le_serveur_rgb_est_lance_en_administrateur():
    """L'ecriture sur le bus SMBus l'exige, la lecture non.

    C'est ce qui faisait repondre la souris et la carte graphique -- USB et
    bus interne, sans restriction -- pendant que la carte mere restait muette.
    """
    import inspect

    from assistant.skills import rgb

    source = inspect.getsource(rgb.demarrer_serveur)
    assert "RunAs" in source


def test_une_couleur_se_donne_par_son_nom_ou_en_hexadecimal():
    from assistant.skills import rgb

    assert "rouge" in rgb.COULEURS and "bleu" in rgb.COULEURS
    import pytest as _pytest

    with _pytest.raises(ValueError):
        rgb._couleur("mauve-turquoise")


def test_les_logiciels_concurrents_sont_signales():
    """Deux programmes sur le meme controleur font clignoter l'eclairage au
    hasard. Le savoir evite une heure de recherche."""
    from assistant.skills import rgb

    assert len(rgb.CONCURRENTS) >= 6, "plusieurs marques doivent etre couvertes"
    assert isinstance(rgb.concurrents_actifs(), list)


def test_les_services_critiques_de_windows_ne_sont_jamais_arretes():
    """Une recherche par motif attrapait MSiSCSI et msiserver -- l'initiateur
    iSCSI et le programme d'installation -- parce que leur nom commence comme
    MSI. Arreter l'un ou l'autre casse la session."""
    from assistant.skills import rgb

    for critique in ("MSiSCSI", "msiserver", "RpcSs", "DcomLaunch"):
        assert critique in rgb.JAMAIS_TOUCHER
        assert critique not in rgb.SERVICES_CONCURRENTS


def test_les_deux_numeros_de_version_ne_divergent_pas():
    """Le numero de version vit a DEUX endroits, et rien ne les reliait.

    assistant/__init__.py sert a la fenetre et a l'autotest ; installateur.iss
    sert a l'entree "Applications installees" de Windows. Les laisser diverger
    donne le pire cas : une application qui s'annonce 1.0.1 dans sa fenetre et
    1.0.0 dans le panneau de configuration, sans que personne sache laquelle
    est vraie.
    """
    import re
    from pathlib import Path

    from assistant import __version__

    racine = Path(__file__).resolve().parent.parent
    iss = (racine / "installateur.iss").read_text(encoding="utf-8", errors="replace")
    trouve = re.search(r'#define\s+MaVersion\s+"([^"]+)"', iss)

    assert trouve, "installateur.iss ne definit plus MaVersion"
    assert trouve.group(1) == __version__, (
        f"installateur.iss annonce {trouve.group(1)} alors que le paquet "
        f"annonce {__version__}")


def test_l_executable_annonce_sa_version():
    """Clic droit > Proprietes sur AssistantLocal.exe n'affichait AUCUNE
    version : l'installateur annoncait 1.0.1 et le programme ne disait rien.

    Le numero doit etre LU dans assistant/__init__.py, pas recopie dans le
    .spec : un troisieme endroit a tenir d'accord a la main finirait par
    diverger, comme installateur.iss avait failli le faire.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    spec = (racine / "AssistantLocal.spec").read_text(encoding="utf-8",
                                                      errors="replace")

    assert "version=_version_info" in spec, (
        "EXE() ne recoit aucun fichier d'informations de version")
    assert "__version__" in spec, (
        "le .spec doit lire le numero dans assistant/__init__.py")
    # Le numero ne doit apparaitre nulle part en dur dans le .spec.
    from assistant import __version__

    assert f'"{__version__}"' not in spec and f"'{__version__}'" not in spec, (
        "le numero de version est recopie en dur dans le .spec")


def test_l_installateur_dit_qu_il_ferme_l_application():
    """Constate en marche reelle le 22/08 : une instance lancee depuis un
    AUTRE dossier a ete fermee par l'installation. Le Gestionnaire de
    redemarrage de Windows identifie les processus par leur module, pas par
    leur chemin.

    C'est le defaut d'Inno Setup 6 et c'est le comportement voulu -- sans lui
    une mise a jour ecraserait des fichiers en cours d'utilisation. Mais un
    comportement voulu qui n'est ecrit nulle part se decouvre en le subissant.
    """
    from pathlib import Path

    iss = (Path(__file__).resolve().parent.parent / "installateur.iss").read_text(
        encoding="utf-8", errors="replace")

    assert "CloseApplications=yes" in iss


def test_la_notice_previent_pour_un_dossier_trop_profond():
    """Mesure du 22/08 : le chemin interne le plus long du bundle fait 110
    caracteres. Avec la limite de 260 de Windows, un dossier d'installation
    au-dela de ~145 caracteres fait echouer la copie des fichiers les plus
    enfouis -- constate pour de vrai, avec un retour en arriere propre.

    Le seuil annonce doit rester coherent avec ce que le bundle contient
    reellement : si un paquet plus profond arrive un jour, la notice ment.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    notice = (racine / "installateur_infos.txt").read_text(encoding="utf-8",
                                                           errors="replace")
    assert "145" in notice and "profonds" in notice

    dist = racine / "dist" / "AssistantLocal"
    if not dist.is_dir():
        return          # rien a verifier tant que l'application n'est pas construite

    plus_long = max((len(str(f.relative_to(dist)))
                     for f in dist.rglob("*") if f.is_file()), default=0)
    assert 145 + plus_long < 260, (
        f"le chemin interne le plus long fait {plus_long} caracteres : "
        "le seuil de 145 annonce dans la notice n'est plus tenable")


def test_l_empreinte_publiee_correspond_a_l_installateur():
    """Le 22/08, l'empreinte publiee designait un installateur compile une
    heure et demie plus tot : produite a la main une fois, jamais refaite, et
    trois recompilations l'ont laissee derriere sans que rien ne le signale.

    Une empreinte qui ne correspond pas est PIRE que pas d'empreinte : celui
    qui la verifie conclut que le fichier a ete altere en chemin.
    """
    import hashlib
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    exe = racine / "installateur" / "Installer_AssistantLocal.exe"
    somme = exe.with_suffix(exe.suffix + ".sha256")

    if not exe.is_file() or not somme.is_file():
        return          # rien a verifier tant que rien n'est publie

    digest = hashlib.sha256()
    with exe.open("rb") as fh:
        for bloc in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(bloc)

    publie = somme.read_text(encoding="utf-8").split()[0].lower()
    assert publie == digest.hexdigest(), (
        "l'empreinte publiee ne correspond plus a l'installateur : "
        "republie avec outils/publier.py")


def test_publier_produit_les_deux_ensemble():
    """La seule facon de tenir l'installateur et son empreinte ensemble est de
    ne jamais les produire separement."""
    import inspect

    from outils import publier

    source = inspect.getsource(publier.main)
    assert source.index("subprocess.run([str(iscc)") < source.index("empreinte(SORTIE)")
    assert "arbre_propre()" in source


def test_la_note_de_reprise_annonce_le_vrai_nombre_de_tests():
    """La note ouvre sur "N tests au vert". Ce chiffre a ete faux trois fois :
    ecrit a la main, il vieillit a chaque test ajoute, et une note de reprise
    dont le premier chiffre est faux perd la confiance qu'on lui accorde pour
    tout le reste.

    Le test compare a ce que pytest collecte reellement.
    """
    import re
    import subprocess
    import sys
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    # La note est une piece de travail locale : elle parle de cette machine,
    # de ses disques de sauvegarde et de ce qui s'est dit en session. Elle ne
    # part pas dans le depot. Sans ce garde-fou, la suite virait au rouge sur
    # tout clone frais -- et un depot public qui s'ouvre sur deux tests casses
    # ne donne envie a personne de lire le reste.
    if not (racine / "REPRISE.md").is_file():
        import pytest
        pytest.skip("REPRISE.md absent : note locale, hors depot")
    note = (racine / "REPRISE.md").read_text(encoding="utf-8", errors="replace")

    annonces = {int(n) for n in re.findall(r"\*\*(\d+) tests au vert\*\*", note)}
    assert annonces, "la note n'annonce plus de nombre de tests"

    resultat = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q", "--collect-only"],
        cwd=racine, capture_output=True, text=True, timeout=300,
    )
    trouve = re.search(r"(\d+) tests? collected", resultat.stdout or "")
    assert trouve, "impossible de compter les tests"
    reel = int(trouve.group(1))

    assert annonces == {reel}, (
        f"la note annonce {sorted(annonces)} test(s), pytest en collecte {reel}")


def test_la_note_de_reprise_ne_declare_pas_fait_ce_qui_ne_l_est_pas():
    """Le chantier de l'annulation est annonce comme ouvert. S'il venait a
    etre termine sans que la note change, la session suivante le referait --
    ou pire, croirait a une garantie inexistante."""
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    # La note est une piece de travail locale : elle parle de cette machine,
    # de ses disques de sauvegarde et de ce qui s'est dit en session. Elle ne
    # part pas dans le depot. Sans ce garde-fou, la suite virait au rouge sur
    # tout clone frais -- et un depot public qui s'ouvre sur deux tests casses
    # ne donne envie a personne de lire le reste.
    if not (racine / "REPRISE.md").is_file():
        import pytest
        pytest.skip("REPRISE.md absent : note locale, hors depot")
    note = (racine / "REPRISE.md").read_text(encoding="utf-8", errors="replace")

    fini = (racine / "assistant" / "annulation.py").exists()
    annonce_ouvert = "annulation" in note.lower() and "absent" in note.lower()

    assert fini != annonce_ouvert or not fini, (
        "assistant/annulation.py existe maintenant : la note doit cesser de "
        "presenter ce chantier comme ouvert")


def test_la_sauvegarde_restaure_avant_de_remplacer():
    """Une sauvegarde qu'on n'a jamais restauree n'est pas une sauvegarde,
    c'est un fichier dont on espere quelque chose. Le script doit prouver que
    le nouveau bundle redonne le depot AVANT de supprimer le precedent."""
    import inspect

    from outils import sauvegarder

    source = inspect.getsource(sauvegarder.refaire_le_bundle)
    assert source.index('"clone"') < source.index("anciens"), (
        "le bundle doit etre restaure avant que l'ancien soit touche")
    assert "unlink" in source and "ancien conserve" in source, (
        "un bundle qui ne se restaure pas ne doit pas remplacer le precedent")


def test_la_sauvegarde_relit_le_depot_distant():
    """git push peut rendre 0 sans que la tete distante ait bouge. On relit
    l'etat au lieu de croire le compte-rendu -- meme regle que partout."""
    import inspect

    from outils import sauvegarder

    source = inspect.getsource(sauvegarder.pousser_sur_h)
    assert "rev-parse" in source and "tete()" in source


def test_le_produit_livre_n_embarque_pas_son_outillage():
    """La regle du .spec balayait outils/ en entier. Ecrite pour transporter
    OpenRGB, elle ramassait les six scripts de developpement, qui partaient
    chez l'utilisateur.

    Le vrai cout n'etait pas les 43 Ko : toucher a l'un d'eux rendait
    l'executable "perime" alors que le produit n'avait pas bouge d'un octet.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    livre = racine / "dist" / "AssistantLocal" / "_internal" / "outils"
    if not livre.is_dir():
        return          # rien a verifier tant que l'application n'est pas construite

    scripts = [f.name for f in livre.rglob("*.py")]
    assert not scripts, (
        f"des scripts de developpement sont livres : {scripts}")

    # Et OpenRGB, lui, ne doit PLUS etre la : il s'installe a part depuis le
    # 23/08. Voir test_licences.py, qui garde la meme frontiere cote licence.
    assert not (livre / "OpenRGB").exists(), (
        "OpenRGB est revenu dans le paquet : l'application redistribue de "
        "nouveau un binaire GPLv2")


def test_l_application_n_importe_jamais_l_outillage():
    """C'est ce qui rend l'exclusion ci-dessus sans danger. Si un jour
    assistant/ importait outils/, l'executable se construirait sans erreur et
    echouerait a l'execution -- le piege habituel de PyInstaller."""
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    for fichier in (racine / "assistant").rglob("*.py"):
        texte = fichier.read_text(encoding="utf-8", errors="replace")
        assert "from outils" not in texte and "import outils" not in texte, (
            f"{fichier.name} importe outils/, qui n'est plus embarque")


def test_le_fichier_d_empreinte_se_lit_hors_de_windows():
    """Le format sha256sum est "empreinte espace etoile nomdufichier". Ecrit
    avec des fins de ligne Windows, le retour chariot se colle au NOM :
    sha256sum -c cherche un fichier appele "...exe\r", ne le trouve pas, et
    repond FAILED open or read.

    Sous Linux, macOS ou Git Bash, le destinataire conclut a une corruption --
    exactement le contraire de ce que ce fichier sert a prouver. Et
    Get-FileHash sous Windows n'y voit rien, ce qui rend le defaut invisible
    depuis la machine qui publie.
    """
    import inspect
    from pathlib import Path

    from outils import publier

    source = inspect.getsource(publier.main)
    # On cherche l'ARGUMENT, pas sa valeur. Ecrire le caractere de
    # retour a la ligne dans ce test revient a comparer un vrai saut
    # de ligne au TEXTE du code source : c'est ce qui a fait echouer
    # la premiere version.
    assert "newline=" in source, (
        "le fichier d'empreinte doit etre ecrit en fins de ligne Unix")

    somme = (Path(__file__).resolve().parent.parent / "installateur"
             / "Installer_AssistantLocal.exe.sha256")
    if somme.is_file():
        assert b"\r" not in somme.read_bytes(), (
            "le fichier d'empreinte publie contient un retour chariot")

def test_la_sauvegarde_constate_le_push_github_au_lieu_de_le_croire():
    """Un push qui rend 0 ne prouve pas que le depot distant a bouge.

    Meme regle que pour H:, et pour la meme raison : on relit la tete du
    depot en ligne. Un push peut reussir sur une autre branche que celle
    qu'on croit -- ce qui est arrive le 23/08 en renommant master en main.
    """
    import inspect

    from outils import sauvegarder

    source = inspect.getsource(sauvegarder.pousser_sur_github)
    assert "ls-remote" in source, "le push n'est pas verifie"
    assert "tete()" in source, "la tete distante n'est comparee a rien"

    # Et surtout : elle doit etre APPELEE. Ecrite mais jamais branchee, la
    # fonction a laisse le script annoncer "les trois copies sont au meme
    # point" pendant que GitHub restait en arriere -- exactement la panne
    # silencieuse qu'elle etait censee supprimer.
    principal = inspect.getsource(sauvegarder.main)
    assert "pousser_sur_github()" in principal, (
        "pousser_sur_github existe mais main() ne l'appelle pas")


def test_le_nom_de_branche_n_est_ecrit_qu_une_fois():
    """Il l'etait cinq fois, et le renommage master -> main les a toutes
    cassees d'un coup.

    Le pire n'etait pas l'echec : tete() ne verifie pas le code de retour de
    git, donc le script aurait compare une chaine vide a une chaine vide et
    annonce que les copies etaient au meme point. Une sauvegarde qui se
    declare faite sans l'etre.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    source = (racine / "outils" / "sauvegarder.py").read_text(encoding="utf-8")

    assert 'BRANCHE = "main"' in source
    lignes_en_dur = [l for l in source.splitlines()
                     if '"master"' in l or '"main"' in l and "BRANCHE =" not in l]
    assert not lignes_en_dur, (
        f"le nom de branche est de nouveau ecrit en dur : {lignes_en_dur}")


def test_livrer_publie_avant_de_regenerer_le_manifeste():
    """Le manifeste est un fichier SUIVI : le regenerer salit l'arbre.

    La premiere version de livrer.py verifiait l'arbre au demarrage, puis le
    salissait elle-meme a l'etape suivante en regenerant le manifeste. Trois
    lignes plus loin, publier.py refusait de publier -- correctement, et
    apres quatre minutes de construction perdues.

    Les deux etapes lisent dist/ sans le modifier : leur ordre est libre du
    point de vue du contenu, et contraint du point de vue de git.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    source = (racine / "livrer.py").read_text(encoding="utf-8")

    place_arbre = source.index("if not arbre_propre():")
    place_construction = source.index('titre(n, etapes, "Executable")')
    assert place_arbre < place_construction, (
        "l'arbre doit etre verifie avant de construire")

    place_publier = source.index('titre(n, etapes, "Installateur")')
    place_manifeste = source.index('titre(n, etapes, "Manifeste du paquet")')
    assert place_publier < place_manifeste, (
        "le manifeste salit l'arbre : il doit venir APRES publier.py")

    assert "commiter_le_manifeste()" in source, (
        "sans ce commit, sauvegarder.py refusera l'arbre sale a son tour")


def test_livrer_constate_l_installateur_au_lieu_de_le_croire():
    """Verifier que le fichier existe ne prouve rien : il en traine toujours
    un, celui de la livraison precedente.

    Ce qui prouve quelque chose, c'est qu'il soit plus RECENT que
    l'executable qu'il est cense contenir.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    source = (racine / "livrer.py").read_text(encoding="utf-8")

    assert "INSTALLATEUR.stat().st_mtime < EXE.stat().st_mtime" in source, (
        "livrer.py doit comparer les dates, pas se contenter d'un is_file()")


def test_le_lisez_moi_calcule_l_empreinte_sur_la_copie_envoyee():
    """L'empreinte doit venir du fichier que la personne recevra.

    La reprendre de la sortie de publier.py certifierait l'original : si la
    copie echoue a moitie, le LISEZ-MOI annoncerait une empreinte qui ne
    correspond pas au fichier joint, et la verification qu'il demande
    echouerait chez le destinataire sans que personne comprenne pourquoi.
    """
    import inspect

    from outils import dossier_a_envoyer

    source = inspect.getsource(dossier_a_envoyer.construire)
    place_copie = source.index("shutil.copy2")
    place_empreinte = source.index("empreinte(copie)")
    assert place_copie < place_empreinte, (
        "l'empreinte est calculee avant la copie")

def test_livrer_rejoue_la_suite_complete_avant_de_distribuer():
    """Changer de numero de version rendait toute livraison impossible.

    Deux tests exigent un manifeste pour la version courante -- bonne regle :
    sans lui, on ne sait plus ce que les gens ont installe. Mais ce manifeste
    ne peut naitre qu'APRES la construction, puisqu'il decrit le paquet reel.

    Le 23/08, le passage en 1.0.3 a donc echoue a l'etape 1 sur 8 : les tests
    reclamaient un fichier que seule l'etape 4 pouvait ecrire. La livraison ne
    pouvait pas demarrer, et rien dans le message d'echec ne disait pourquoi.

    Les deux sont ecartes du pre-vol et rejoues au complet apres le
    manifeste. Ce test verifie que le second passage existe, et qu'il tombe
    AVANT tout ce qui distribue : dossier du Bureau, sauvegardes,
    installation.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    source = (racine / "livrer.py").read_text(encoding="utf-8")

    place_manifeste = source.index('titre(n, etapes, "Manifeste du paquet")')
    place_complets = source.index('titre(n, etapes, "Tests (complets)")')
    place_bureau = source.index('titre(n, etapes, "Dossier du Bureau")')

    assert place_manifeste < place_complets, (
        "la suite complete doit venir apres le manifeste, sinon elle echoue "
        "sur les deux tests qui le reclament")
    assert place_complets < place_bureau, (
        "rien ne doit etre distribue avant que la suite complete soit verte")

    for nom in ("test_partir_de_la_version_courante_est_refuse",
                "test_le_manifeste_de_la_version_publiee_est_versionne"):
        assert nom in source, (
            f"{nom} n'est plus ecarte du pre-vol : un changement de version "
            "rendra la livraison impossible")


def test_livrer_publie_la_release_apres_avoir_pousse_sur_github():
    """Une Release etiquette un commit : GitHub doit deja l'avoir recu.

    Publier avant l'etape des sauvegardes -- celle qui pousse sur GitHub --
    echoue en 422 "target_commitish is invalid", le meme message que donne un
    SHA court. Deux causes, un seul message : l'ordre doit etre garanti ici
    plutot que redecouvert a chaque livraison ratee.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    source = (racine / "livrer.py").read_text(encoding="utf-8")

    place_sauvegardes = source.index('titre(n, etapes, "Sauvegardes")')
    place_release = source.index('titre(n, etapes, "Release GitHub")')
    assert place_sauvegardes < place_release, (
        "la Release doit venir APRES le push : GitHub ne peut etiqueter "
        "que ce qu'il a recu")


def test_livrer_appelle_vraiment_la_publication():
    """Une fonction qui existe et que personne n'appelle ne fait rien.

    Le defaut s'est deja produit ici : pousser sur GitHub etait ecrit dans
    sauvegarder.py, et main() ne l'appelait pas. Le script annoncait des
    sauvegardes completes pendant que la copie en ligne prenait du retard.

    Ecrire outils/publier_release.py sans le brancher dans livrer.py
    reproduirait exactement ce defaut, avec le meme silence.
    """
    from pathlib import Path

    racine = Path(__file__).resolve().parent.parent
    assert (racine / "outils" / "publier_release.py").is_file()

    source = (racine / "livrer.py").read_text(encoding="utf-8")
    assert '"publier_release.py"' in source, (
        "livrer.py n'appelle pas l'outil de publication")

    # Le compte d'etapes doit suivre, sinon l'affichage annonce "8/9" pour la
    # derniere etape et laisse croire qu'il en manque une.
    assert "etapes = (10" in source, (
        "le nombre d'etapes n'a pas suivi l'ajout de la Release")


def test_les_notes_de_version_ne_sont_pas_inventees():
    """Un script qui redige les notes finit par ecrire "corrections diverses".

    Meme raison que pour les messages de commit, que livrer.py refuse
    d'inventer : les notes disent a quelqu'un d'exterieur ce qui a change.
    Elles se lisent dans notes_de_version/<version>.md, et leur absence
    arrete la publication au lieu de produire une Release vide de sens.
    """
    import inspect
    from pathlib import Path

    from outils import publier_release

    source = inspect.getsource(publier_release.publier)
    assert "notes_de_version" in inspect.getsource(publier_release), (
        "les notes doivent venir d'un fichier, pas du script")
    assert "Elles se redigent" in source, (
        "l'absence de notes doit s'expliquer, pas echouer sechement")

    racine = Path(__file__).resolve().parent.parent
    from assistant import __version__
    attendu = racine / "notes_de_version" / f"{__version__}.md"
    assert attendu.is_file(), (
        f"les notes de la version courante manquent : {attendu}")


# --- Reparer Windows : sfc et DISM ------------------------------------------

def test_les_commandes_de_reparation_windows_sont_orthographiees_juste():
    """Une lettre de travers, et la commande ne repare rien sans le dire.

    sfc et DISM ne renvoient pas d'erreur lisible sur un drapeau inconnu :
    ils affichent leur aide et rendent la main. Dans une fenetre qui se ferme
    apres coup, cela ressemble trait pour trait a une reparation qui s'est
    bien passee.

    Ces deux chaines sont donc figees ici. "/RestoreHealth" en particulier
    s'ecrit sans espace et sans tiret, contrairement a ce que la plupart des
    pages web recopient de travers.
    """
    from assistant.skills import fixes

    assert fixes.SFC == "sfc /scannow"
    assert fixes.DISM == "DISM /Online /Cleanup-Image /RestoreHealth"


def test_un_refus_ne_lance_aucune_reparation_windows(monkeypatch):
    """Refuser doit vraiment tout arreter, pas seulement changer le message.

    Ces deux commandes reecrivent des fichiers systeme et durent jusqu'a une
    demi-heure. Un refus qui laisserait passer l'execution serait le pire
    defaut possible de ce module.
    """
    from assistant.skills import fixes

    lancements = []
    monkeypatch.setattr(fixes, "_lancer_en_admin",
                        lambda *a: lancements.append(a) or (True, ""))

    for fonction in (fixes.verifier_fichiers_systeme,
                     fixes.reparer_image_windows):
        resultat = fonction(ask=lambda _texte: False)
        assert not resultat.ok
        assert lancements == [], "une reparation a ete lancee malgre le refus"


def test_les_reparations_windows_ne_se_declarent_pas_reversibles(monkeypatch):
    """On ne defait pas un fichier repare.

    Le garde-fou traite `routine` et `reversible` ensemble : une action
    irreversible pose toujours la question, meme si quelqu'un la marquait un
    jour comme geste courant. Encore faut-il qu'elle soit declaree pour ce
    qu'elle est.
    """
    from assistant import safety
    from assistant.skills import fixes

    vues = []
    monkeypatch.setattr(safety, "guard",
                        lambda action, ask=None: vues.append(action) or True)
    monkeypatch.setattr(fixes, "_lancer_en_admin", lambda *a: (True, ""))

    fixes.verifier_fichiers_systeme()
    fixes.reparer_image_windows()

    assert len(vues) == 2
    for action in vues:
        assert action.reversible is False
        assert action.routine is False, (
            "une reparation systeme ne doit jamais passer sans etre annoncee")


def test_la_reparation_windows_ne_bloque_pas_l_assistant():
    """Une demi-heure d'attente bloquee, et la commande vocale est perdue.

    sfc dure de cinq a quinze minutes, DISM jusqu'a trente. Attendre leur fin
    dans le processus de l'assistant gelerait la fenetre et laisserait une
    question vocale sans reponse pendant tout ce temps.

    Ce test exigeait aussi une console VISIBLE, au motif qu'une reparation
    cachee se fait interrompre. L'exigence est INVERSEE depuis le 24/08/2026,
    a la demande de l'utilisateur : une fenetre noire par action, sur une
    application qui en enchaine, donne l'impression d'un bricolage. Il l'a dit
    avant meme d'avoir fini de les essayer.

    Ce qui motivait la console reste vrai, et c'est pour cela qu'elle n'a pas
    ete simplement supprimee : la progression est rapatriee dans le panneau,
    qui relit le journal. Le test qui le verifie est
    test_le_panneau_suit_le_journal_au_lieu_d_attendre.
    """
    import ast
    import inspect
    import textwrap

    from assistant.skills import fixes

    # Le CODE seul : la docstring nomme ces pieges pour les expliquer, et
    # l'inspecter reviendrait a interdire d'en parler.
    #
    # Le retrait passe par ast. `inspect.getdoc` dedente la docstring, donc la
    # soustraire du source brut ne retire rien -- faux negatif verifie.
    arbre = ast.parse(textwrap.dedent(inspect.getsource(fixes._lancer_en_admin)))
    corps = arbre.body[0].body[1:]          # [0] est la docstring
    code = "\n".join(ast.unparse(noeud) for noeud in corps)

    assert "-Wait" not in code, (
        "attendre la fin gelerait l'assistant pendant une demi-heure")
    assert "WindowStyle Hidden" in code, (
        "la console noire est revenue : la progression se suit dans le "
        "panneau, plus dans une fenetre")
    assert "-Verb RunAs" in code, "sfc et DISM exigent l'elevation"

    # Le fichier doit survivre a l'appel : on ne l'attend pas.
    assert "TemporaryDirectory(" not in code, (
        "un dossier temporaire serait efface avant que cmd lise le script")


def test_le_catalogue_annonce_les_deux_reparations_windows():
    """Un correctif que personne ne sait demander n'existe pas.

    disponibles() est ce que l'assistant recite quand on lui demande ce qu'il
    sait reparer. Y ajouter une capacite sans l'y annoncer revient a ne pas
    l'avoir ecrite.
    """
    from assistant.skills import fixes

    catalogue = fixes.disponibles()
    assert "sfc" in catalogue
    assert "DISM" in catalogue
    assert "reversibles" in catalogue, (
        "le catalogue annoncait tout comme reversible : ces deux-la ne le sont pas")


def test_les_deux_reparations_windows_sont_exposees_au_modele():
    """Ecrite mais pas branchee, une fonction ne sert a rien.

    Le defaut s'est deja produit dans ce projet : pousser sur GitHub existait
    dans sauvegarder.py et main() ne l'appelait pas. Une capacite absente de
    TOOLS est invisible pour le modele, donc introuvable a la voix.
    """
    from assistant import llm

    noms = {t.name for t in llm.TOOLS}
    assert "verifier_fichiers_systeme" in noms
    assert "reparer_image_windows" in noms

    dism = next(t for t in llm.TOOLS if t.name == "reparer_image_windows")
    assert "sfc" in dism.description.lower(), (
        "le modele doit savoir que DISM ne se lance qu'apres un echec de sfc")
