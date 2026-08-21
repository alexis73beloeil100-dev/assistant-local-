"""Produit la note de reprise en PDF, sur le Bureau.

Destinee a la session suivante -- humaine ou assistante -- pour qu'elle
reprenne sans rien perdre ni rien refaire. Le PDF se lit sans outil, se
transporte, et s'imprime : c'est ce qui manque a REPRISE.md quand on n'a pas
le depot sous la main.

Le contenu est ecrit ici plutot que genere depuis REPRISE.md : le document
Markdown est un journal de bord detaille, le PDF est une note d'une poignee
de pages qui va a l'essentiel. Les deux ont leur usage.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (HRFlowable, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

RACINE = Path(__file__).resolve().parent.parent

# Sobre et lisible a l'impression : ce document se consulte en travaillant,
# parfois sur papier.
ENCRE = colors.HexColor("#14181D")
GRIS = colors.HexColor("#5C6672")
ACCENT = colors.HexColor("#0C6E7D")
ROUGE = colors.HexColor("#B03A2E")
VERT = colors.HexColor("#2E7D4F")
TRAIT = colors.HexColor("#D6DBE0")
FOND = colors.HexColor("#F2F5F6")


def styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "titre": ParagraphStyle(
            "titre", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, textColor=ENCRE, alignment=TA_LEFT,
            spaceAfter=2),
        "sous_titre": ParagraphStyle(
            "sous_titre", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, leading=15, textColor=GRIS, spaceAfter=10),
        "section": ParagraphStyle(
            "section", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=13, leading=17, textColor=ACCENT,
            spaceBefore=16, spaceAfter=6),
        "sous_section": ParagraphStyle(
            "sous_section", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=14, textColor=ENCRE,
            spaceBefore=10, spaceAfter=3),
        "corps": ParagraphStyle(
            "corps", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=14, textColor=ENCRE, spaceAfter=6),
        "note": ParagraphStyle(
            "note", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=9, leading=13, textColor=GRIS, spaceAfter=6,
            leftIndent=8),
        "code": ParagraphStyle(
            "code", parent=base["Normal"], fontName="Courier",
            fontSize=8.5, leading=12, textColor=ENCRE,
            backColor=FOND, borderPadding=6, spaceBefore=4, spaceAfter=8),
        "puce": ParagraphStyle(
            "puce", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=14, textColor=ENCRE,
            leftIndent=12, bulletIndent=3, spaceAfter=3),
    }


def tableau(donnees: list[list[str]], largeurs: list[float],
            s: dict) -> Table:
    """Tableau a filets fins, sans quadrillage lourd."""
    contenu = [[Paragraph(cellule, s["corps"]) for cellule in ligne]
               for ligne in donnees]
    table = Table(contenu, colWidths=largeurs, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, TRAIT),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def mesures() -> dict:
    """Chiffres relevés sur le depot, pour ne rien affirmer de memoire."""
    infos = {}
    try:
        fichiers = list((RACINE / "assistant").rglob("*.py"))
        infos["fichiers"] = len(fichiers)
        infos["lignes"] = sum(
            len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            for f in fichiers)
    except OSError:
        infos["fichiers"] = infos["lignes"] = 0

    try:
        infos["commit"] = subprocess.run(
            ["git", "-C", str(RACINE), "log", "-1", "--format=%h %s"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace").stdout.strip()
    except (subprocess.SubprocessError, OSError):
        infos["commit"] = "inconnu"

    exe = RACINE / "dist" / "AssistantLocal" / "AssistantLocal.exe"
    infos["exe"] = (
        datetime.fromtimestamp(exe.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
        if exe.exists() else "absent")
    return infos


def construire(destination: Path) -> Path:
    s = styles()
    m = mesures()
    doc = SimpleDocTemplate(
        str(destination), pagesize=A4,
        leftMargin=20 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=16 * mm,
        title="Assistant local - note de reprise",
        author="Assistant local",
    )
    F = []

    # ---------------------------------------------------------------- entete
    F.append(Paragraph("Assistant local", s["titre"]))
    F.append(Paragraph(
        f"Note de reprise &mdash; {datetime.now().strftime('%d/%m/%Y a %H:%M')}"
        "<br/>A lire avant de toucher au code.", s["sous_titre"]))
    F.append(HRFlowable(width="100%", thickness=1, color=ACCENT,
                        spaceAfter=10))

    F.append(Paragraph("1. L'etat en une page", s["section"]))
    F.append(tableau([
        ["", ""],
        ["Code", f"{m['lignes']:,} lignes, {m['fichiers']} fichiers Python"
                 .replace(",", " ")],
        ["Tests", "129 au vert"],
        ["Outils du modele", "71 (36 lecture, 35 action)"],
        ["Panneaux", "19, dont 4 interactifs"],
        ["Executable", m["exe"]],
        ["Dernier commit", m["commit"][:70]],
        ["Autotest", "15 controles, tout au vert"],
    ][1:], [38 * mm, 125 * mm], s))

    F.append(Paragraph(
        "L'application connait la machine, agit dessus, repond a la voix, et "
        "ne laisse rien sur le disque hormis un fichier de reglages. Tout "
        "tourne en local.", s["corps"]))

    # ------------------------------------------------------- fait recemment
    F.append(Paragraph("2. Ce qui vient d'etre fait", s["section"]))

    F.append(Paragraph("Panneau Reparer, rendu utile", s["sous_section"]))
    F.append(Paragraph(
        "Il listait ce que l'assistant <i>savait</i> faire &mdash; un "
        "catalogue, pas un diagnostic. Il liste desormais ce qui cloche "
        "reellement, avec un bouton par ligne et un bouton "
        "<b>Tout reparer</b>. Module : <font face='Courier'>"
        "assistant/reparation.py</font>.", s["corps"]))
    F.append(Paragraph(
        "Seul ce qui ne coute rien a reprendre est coche d'office. Les caches "
        "Unreal sont listes et chiffres mais <b>decoches</b> : les supprimer "
        "coute des heures de recompilation de shaders. Les points de "
        "restauration n'apparaissent pas du tout &mdash; un filet de securite "
        "n'a pas sa place derriere un bouton automatique.", s["corps"]))

    F.append(Paragraph("Les 14 fenetres au demarrage de Windows",
                       s["sous_section"]))
    F.append(Paragraph(
        "La cause n'etait pas dans le code mais dans le <b>registre</b> : "
        "l'entree de demarrage datait du premier jour et lancait "
        "<font face='Courier'>demarrer_assistant.py</font> depuis les "
        "sources, donc la boucle vocale sans fenetre. Trois defauts corriges "
        "a cette occasion :", s["corps"]))
    for texte in [
        "<font face='Courier'>nvidia-smi</font> etait le seul appel systeme "
        "sans le drapeau <font face='Courier'>CREATE_NO_WINDOW</font>. Il "
        "tourne au demarrage, a chaque ouverture d'Etat en direct et a chaque "
        "diagnostic : une console a chaque fois.",
        "<font face='Courier'>demarrer_assistant.py</font> ouvrait la boucle "
        "vocale au lieu de la fenetre.",
        "<font face='Courier'>startup.py</font> calculait sa cible depuis "
        "<font face='Courier'>__file__</font>, qui pointe dans "
        "<font face='Courier'>_internal</font> une fois emballe. Activer le "
        "demarrage depuis l'application inscrivait un chemin invalide. Il "
        "utilise maintenant <font face='Courier'>sys.executable</font>.",
    ]:
        # reportlab n'a pas de parametre "bullet" : la puce se declare dans
        # le texte, et le style l'indente via bulletIndent.
        F.append(Paragraph(f"<bullet>&bull;</bullet>{texte}", s["puce"]))
    F.append(Paragraph(
        "L'autotest compare desormais l'entree inscrite a celle attendue et "
        "affiche les deux chemins si elles different. Ce decalage ne peut "
        "plus passer inapercu.", s["corps"]))

    F.append(Paragraph("Un conflit d'acces a l'index", s["sous_section"]))
    F.append(Paragraph(
        "Ouvrir le panneau Reparer pendant le scan initial faisait lire la "
        "base pendant qu'elle s'ecrivait : "
        "<font face='Courier'>database table is locked</font>, et le scan "
        "<b>echouait silencieusement</b>. Le detecteur attend maintenant que "
        "l'index soit pret, et le panneau l'annonce en clair.", s["corps"]))

    F.append(PageBreak())

    # --------------------------------------------------------------- a faire
    F.append(Paragraph("3. Ce qui reste a faire", s["section"]))

    F.append(Paragraph("Priorite 1 &mdash; l'eclairage RGB", s["sous_section"]))
    F.append(Paragraph(
        "Lecture parfaite, ecriture sans effet. Les trois peripheriques "
        "(RTX 5060 Ti, carte mere B550, souris Basilisk V3) sont detectes "
        "sans erreur et sans droits administrateur, mais le changement de "
        "mode ne fait pas bouger les LED.", s["corps"]))
    F.append(Paragraph(
        "<b>Le test qui tranche tout, et qui n'a jamais ete fait</b> : "
        "changer un mode dans l'interface graphique d'OpenRGB elle-meme. Si "
        "le GUI n'y arrive pas non plus, le probleme est OpenRGB ou le "
        "materiel, et tout le travail sur le protocole est inutile. "
        "<b>A faire avant d'ecrire une ligne de plus.</b>", s["corps"]))
    F.append(Paragraph(
        "Ensuite seulement : remplacer le client ecrit a la main par le SDK "
        "officiel <font face='Courier'>openrgb-python</font>. Le format "
        "binaire a piege trois fois &mdash; champ fabricant ajoute en "
        "version 1, longueur de matrice lue sur 32 bits au lieu de 16, et un "
        "decalage non resolu qui fait ressortir le nombre de LED a zero.",
        s["corps"]))
    F.append(Paragraph(
        "Deja elimine, ne pas refaire : la concurrence des logiciels "
        "fabricants (trois services arretes, aucun effet) et la lecture du "
        "profil RGB Fusion (fichier jamais reecrit en dix minutes).",
        s["note"]))

    F.append(Paragraph("Priorite 2 &mdash; le bouton Annuler",
                       s["sous_section"]))
    F.append(Paragraph(
        "Chantier commence, pas termine. "
        "<font face='Courier'>safety.Action</font> porte son annulation, "
        "<font face='Courier'>cleanup.restaurer()</font> ressort de la "
        "corbeille. Il manque le registre des operations et le bouton dans le "
        "panneau Journal. Commit <font face='Courier'>e2600cd</font>.",
        s["corps"]))

    F.append(Paragraph("Priorite 3 &mdash; demande par l'utilisateur",
                       s["sous_section"]))
    F.append(tableau([
        ["Sujet", "Etat / effort"],
        ["Joindre fichiers et images dans la conversation",
         "Les capacites existent deja (lire_fichier, lire_image, OCR). Il "
         "manque le geste : bouton trombone et glisser-deposer. ~1 h."],
        ["Rendre les autres panneaux cliquables",
         "4 sur 19 le sont. Modele a suivre : pupitre.py, ludotheque.py, "
         "reparation.py."],
        ["Generer des images en local",
         "Le seul vrai chantier. Stable Diffusion, 4 a 7 Go, VRAM partagee "
         "avec le modele et Whisper. Double la taille de l'installateur."],
    ], [58 * mm, 105 * mm], s))

    F.append(Paragraph("Priorite 4 &mdash; les mises a jour",
                       s["sous_section"]))
    F.append(Paragraph(
        "Il n'existe aucun mecanisme. Livrer une correction impose de refaire "
        "telecharger 1,13 Go, alors que ce qui change tient dans "
        "l'executable de 24 Mo &mdash; les bibliotheques CUDA representent "
        "78 % du poids et ne bougent jamais.", s["corps"]))
    F.append(Paragraph(
        "Decision en attente de l'utilisateur : ou publier, et verification "
        "manuelle ou automatique. La seconde oblige a reecrire la promesse "
        "&laquo; aucune connexion sortante apres l'installation &raquo;, qui "
        "est un argument central du projet.", s["note"]))

    # ---------------------------------------------------------------- pieges
    F.append(Paragraph("4. Pieges a ne pas refaire", s["section"]))
    F.append(tableau([
        ["Piege", "Ce qu'il faut savoir"],
        ["Restaurer depuis une vieille archive du Bureau",
         "Les archives anterieures au depot Git contiennent des fichiers "
         "plus anciens. <b>Le depot est la seule source de verite.</b>"],
        ["Croire la relecture apres une ecriture RGB",
         "Le serveur repete ce qu'on lui a dit. Seul l'oeil sur le materiel "
         "fait foi."],
        ["Reconstruire pendant qu'un processus tient dist/",
         "OpenRGB garde hidapi.dll ouverte, Ollama et llama-server tiennent "
         "leurs DLL. <font face='Courier'>reconstruire.py</font> les arrete "
         "tous. PyInstaller sort en code 0 meme quand la copie a echoue."],
        ["Oublier de reconstruire apres modification",
         "Le raccourci du Bureau lance une photographie figee. Sources et "
         "executable divergent en silence."],
        ["Redemarrer un service",
         "Demande les droits administrateur, que l'application n'a pas "
         "volontairement. Le message le dit maintenant."],
    ], [55 * mm, 108 * mm], s))

    # ------------------------------------------------------------ verifier
    F.append(Paragraph("5. Verifier que tout va bien", s["section"]))
    F.append(Paragraph(
        "Depuis <font face='Courier'>C:\\Users\\Asuna\\Documents\\Assistant"
        "</font> :", s["corps"]))
    F.append(Paragraph(
        ".venv\\Scripts\\python.exe -m pytest -q<br/>"
        ".venv\\Scripts\\python.exe reconstruire.py<br/>"
        "dist\\AssistantLocal\\AssistantLocal.exe --autotest",
        s["code"]))
    F.append(Paragraph(
        "Les trois doivent passer : 129 tests, une construction sans "
        "<font face='Courier'>PermissionError</font>, et un autotest sans "
        "ligne bloquante. Le journal de bord complet, avec le detail de "
        "chaque defaut corrige, reste dans "
        "<font face='Courier'>REPRISE.md</font> a la racine du depot.",
        s["corps"]))

    F.append(Spacer(1, 8 * mm))
    F.append(HRFlowable(width="100%", thickness=0.5, color=TRAIT))
    F.append(Paragraph(
        "La regle non negociable, posee par l'utilisateur : <b>rien n'est "
        "ecrit sur le disque</b>. L'index des fichiers et la connaissance de "
        "la machine vivent en memoire vive et se reconstruisent a chaque "
        "demarrage. Seul un fichier de reglages de quelques lignes subsiste.",
        s["note"]))

    doc.build(F)
    return destination


def bureau() -> Path:
    import os

    profil = Path(os.environ.get("USERPROFILE", ""))
    for candidat in (profil / "OneDrive" / "Bureau", profil / "OneDrive" / "Desktop",
                     profil / "Bureau", profil / "Desktop"):
        if candidat.is_dir():
            return candidat
    return Path.home()


def main() -> int:
    horodatage = datetime.now().strftime("%Y-%m-%d_%Hh%M")
    cible = bureau() / f"Assistant_note_de_reprise_{horodatage}.pdf"
    construire(cible)
    print(f"Note de reprise : {cible}")
    print(f"  {cible.stat().st_size / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
