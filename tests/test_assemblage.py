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


def test_le_pilotage_rgb_passe_par_le_sdk_officiel():
    """Le protocole binaire a piege QUATRE fois un client ecrit a la main.

    Le pire : le nombre de LED ressortait a zero sans lever d'erreur. Or sans
    lui, impossible d'ecrire les couleurs -- et changer le mode ne suffit pas
    sur une carte mere. La souris et la carte graphique suivaient, la carte
    mere restait muette. Deux peripheriques sur trois, ce qui ressemblait a un
    probleme de materiel plutot qu'a une erreur d'analyse.
    """
    import inspect

    from assistant.skills import rgb

    source = inspect.getsource(rgb._client)
    assert "OpenRGBClient" in source, "le SDK officiel doit etre utilise"


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

    # Et l'outil qui doit partir, lui, doit bien etre la.
    assert (livre / "OpenRGB" / "OpenRGB.exe").is_file(), (
        "OpenRGB n'est plus embarque : l'eclairage cessera de fonctionner "
        "dans la version installee, en silence")


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
