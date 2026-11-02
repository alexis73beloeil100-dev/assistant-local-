"""Fenetre de l'assistant.

Deux modes dans la meme fenetre :

  - les PANNEAUX, pour ce que l'application sait deja. Configuration,
    problemes, jeux, espace disque : ces donnees sont relevees au demarrage.
    Les faire reformuler par le modele de langage serait lent et hasardeux --
    un modele qui recopie des chiffres finit toujours par en deformer un.
    Alors on les affiche directement. Un clic, rien a attendre.

  - la CONVERSATION, pour les questions libres, ou le modele est
    indispensable.

Tout ce qui est lent part dans un thread. La regle en Tk est stricte : seul
le thread principal touche aux widgets, donc les threads de travail postent
leurs resultats dans une file que la fenetre vide vingt fois par seconde.
"""
from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

from assistant import (apprentissage, config, connaissance, llm, panels,
                       theme as t)
from assistant.index import db, scanner, watcher
from assistant.skills import games, hardware
from assistant.widgets import (Bandeau, Message, NavCell, RoundButton,
                               ScrollArea, StatusDot)

TITLE = "Assistant local"
SUBTITLE = "tout reste sur cette machine"

# Affiche a cote du numero de version, dans l'en-tete.
#
# L'application est distribuee et installee sur de vraies machines : celui qui
# l'ouvre a besoin de savoir qu'elle bouge encore, sans quoi chaque defaut
# passe pour un defaut d'un produit fini.
ACCES_ANTICIPE = "acces anticipe"
CHAT_KEY = "conversation"

# Barre laterale : trois colonnes de 62 px, plus la barre de defilement et les
# marges. Dix-huit panneaux tiennent alors en six rangees, sans defilement,
# contre plus d'une hauteur de fenetre en liste.
RAIL_COLONNES = 3
CELLULE_LARGEUR = 58
RAIL_LARGEUR = RAIL_COLONNES * (CELLULE_LARGEUR + 2) + 22

# --- Reconnaissance des formes dans un releve --------------------------------
#
# Les competences rendent du texte brut, sans balises -- c'est ce qui permet de
# l'envoyer tel quel au modele. On reconnait donc les formes a l'affichage.

# Un filet de separation : "-----" ou "=====".
_REGLE = re.compile(r"^[-=]{3,}$")

# Une barre d'occupation, telle que system.py et panels.py les tracent.
_BARRE = re.compile(r"#*\.*")

# Une mesure chiffree avec son unite. Les unites sont listees explicitement :
# un motif large attraperait les numeros de version, les identifiants Steam et
# les pids, qui ne sont pas des mesures.
_MESURE = re.compile(
    r"\d+(?:[ .,]\d+)*\s?(?:%|Go/s|Mo/s|Ko/s|Go|Mo|Ko|To|GHz|MHz|"
    r"\bW\b|ms|\bh\b|\bC\b|coeurs?|threads?|jours?|fichiers?)"
)


def _decouper(ligne: str, base: str) -> list[tuple[str, str]]:
    """Decoupe une ligne en morceaux, chacun avec son tag.

    Ce qui merite d'etre distingue : les barres d'occupation, dont le plein et
    le vide n'ont pas le meme poids, et les mesures chiffrees, qui sont ce
    qu'on vient chercher dans un releve.
    """
    marques: list[tuple[int, int, str]] = []

    for trouve in _BARRE.finditer(ligne):
        texte = trouve.group()
        # finditer sur un motif entierement optionnel rend aussi des chaines
        # vides a chaque position : on ne garde que les vraies barres.
        if len(texte) < 6 or "#" not in texte and "." not in texte:
            continue
        if not set(texte) <= {"#", "."}:
            continue
        debut = trouve.start()
        plein = texte.count("#")
        if plein:
            marques.append((debut, debut + plein, "barre_pleine"))
        if plein < len(texte):
            marques.append((debut + plein, trouve.end(), "barre_vide"))

    for trouve in _MESURE.finditer(ligne):
        if any(d < trouve.end() and trouve.start() < f for d, f, _ in marques):
            continue
        marques.append((trouve.start(), trouve.end(), "mesure"))

    if not marques:
        return [(ligne, base)]

    marques.sort()
    morceaux: list[tuple[str, str]] = []
    curseur = 0
    for debut, fin, tag in marques:
        if debut > curseur:
            morceaux.append((ligne[curseur:debut], base))
        morceaux.append((ligne[debut:fin], tag))
        curseur = fin
    if curseur < len(ligne):
        morceaux.append((ligne[curseur:], base))
    return morceaux


def _resume_args(args: dict) -> str:
    if not args:
        return ""
    texte = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return texte if len(texte) <= 140 else texte[:137] + "..."


def _resume_resultat(resultat) -> str:
    lignes = [l.strip() for l in str(resultat).splitlines() if l.strip()]
    if not lignes:
        return "(rien)"
    texte = lignes[0][:200] + (f"  (+{len(lignes) - 1} lignes)" if len(lignes) > 1 else "")
    return texte


class AssistantWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        # Avant tout widget : interroger la liste des polices exige une racine
        # Tk, qui vient seulement d'exister. Si la demi-grasse manque sur cette
        # machine, on retombe sur la graisse normale plutot que de laisser Tk
        # substituer une police proportionnelle en silence -- ce qui
        # decalerait toutes les colonnes des relevés.
        t.resoudre_polices()
        self.title(TITLE)
        self.geometry("1120x740")
        self.minsize(860, 560)
        self.configure(bg=t.BG)

        self.events: queue.Queue = queue.Queue()
        self.convo = llm.new_conversation()
        self.busy = False
        # Rappels (genre, texte) pour chaque message affiche : la mini-fenetre
        # y lit la reponse a la question qu'elle a posee.
        self.abonnes_reponse: list = []
        self.current = CHAT_KEY
        self._messages: list[Message] = []
        self._nav: dict[str, tk.Frame] = {}
        # Dernier panneau consulte, joint aux questions suivantes. Ce n'est pas
        # self.current : pour taper une question il faut revenir sur la
        # conversation, donc le panneau est deja "ferme" au moment de l'envoi.
        self._contexte_panneau: str | None = None
        self._fichiers_joints: list[str] = []

        self._build()
        self.after(50, self._drain)
        self._brancher_confirmation()
        # "Tape bonjour" doit ecrire dans l'application ou l'utilisateur
        # travaille, pas dans l'assistant : on retient donc la fenetre qui
        # prend le focus quand il quitte la notre.
        self.bind("<FocusOut>", self._retenir_fenetre_cible)
        self._boot()

    def _retenir_fenetre_cible(self, _e=None) -> None:
        """Note la fenetre au premier plan, si elle n'est pas la notre.

        On compare les processus et non les identifiants de fenetre : Tk
        n'expose pas le HWND de la fenetre principale mais celui d'un widget
        enfant, et la comparaison directe echouerait toujours.
        """
        try:
            import ctypes
            import os

            from assistant.skills import control

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != os.getpid():
                control.memoriser_cible(hwnd)
        except Exception:  # noqa: BLE001 - jamais bloquant
            pass

    # =====================================================================
    # Construction
    # =====================================================================

    def _build(self) -> None:
        self._build_header()

        body = tk.Frame(self, bg=t.BG)
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)

        self.stage = tk.Frame(body, bg=t.BG)
        self.stage.pack(side="left", fill="both", expand=True)

        self._build_panel_view()
        self._build_chat_view()

        # Au tout premier lancement, on ouvre l'accueil plutot que la
        # conversation : quelqu'un qui decouvre l'application ne sait pas
        # quoi taper dans un champ vide.
        from assistant import settings

        premiere_fois = not settings.get("deja_lance", False)
        if premiere_fois:
            settings.set("deja_lance", True)
            self.show("accueil")
        else:
            self.show(CHAT_KEY)

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=t.SURFACE, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=t.SURFACE)
        left.pack(side="left", padx=t.PAD_L)
        tk.Label(left, text=TITLE, bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_TITLE).pack(side="left", pady=t.PAD_L)
        from assistant import __version__
        tk.Label(left, text=f"  {SUBTITLE}   v{__version__}",
                 bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_SMALL).pack(side="left", pady=t.PAD_L)

        # "Acces anticipe", en pastille plutot qu'en texte a la suite.
        #
        # Ecrite dans le meme gris que le reste, la mention se serait fondue
        # dans la ligne et n'aurait rien annonce. Elle dit a qui ouvre
        # l'application que ce qu'il voit peut encore bouger : c'est une
        # promesse en moins, pas une decoration.
        pastille = tk.Frame(left, bg=t.ACCENT_SOFT, highlightthickness=1,
                            highlightbackground=t.ACCENT_DEEP)
        pastille.pack(side="left", padx=(t.PAD, 0), pady=t.PAD_L)
        tk.Label(pastille, text=ACCES_ANTICIPE, bg=t.ACCENT_SOFT,
                 fg=t.ACCENT, font=t.FONT_HUD).pack(padx=t.PAD, pady=1)

        right = tk.Frame(header, bg=t.SURFACE)
        right.pack(side="right", padx=t.PAD_L)

        # Signaler un probleme depuis l'endroit ou on le rencontre.
        #
        # Un defaut qui n'est pas remonte n'est pas corrige, et la distance
        # entre "ca ne marche pas" et un rapport utilisable decourage a peu
        # pres tout le monde : retrouver une version, dire quel Windows,
        # expliquer ce qu'on faisait. Le bouton fait ce travail a la place.
        RoundButton(right, "Support", self.ouvrir_le_support, width=104,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(
            side="right", padx=(t.PAD_L, 0))

        self.status_text = tk.StringVar(value="Demarrage")
        tk.Label(right, textvariable=self.status_text, bg=t.SURFACE,
                 fg=t.TEXT_DIM, font=t.FONT_UI_SMALL).pack(
            side="right", padx=(t.PAD, 0))
        self.dot = StatusDot(right)
        self.dot.pack(side="right", pady=t.PAD_XL)

        # Filet cyan sous l'en-tete : marque la separation sans cadre.
        tk.Frame(self, bg=t.ACCENT_DEEP, height=1).pack(fill="x")

    def _build_sidebar(self, parent) -> None:
        """Grille d'icones plutot que liste de menus.

        Dix-huit destinations en lignes titre + sous-titre depassaient la
        hauteur de la fenetre : il fallait faire defiler un menu pour trouver
        une page. En grille de trois colonnes, tout tient d'un coup d'oeil et
        la barre est deux fois plus etroite.
        """
        side = tk.Frame(parent, bg=t.SURFACE, width=RAIL_LARGEUR)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Frame(parent, bg=t.ACCENT_DEEP, width=1).pack(side="left", fill="y")

        self._build_sidebar_bottom(side)

        liste = ScrollArea(side, bg=t.SURFACE)
        liste.pack(fill="both", expand=True)
        self._rail = liste.inner
        self._remplir_rail()

    def _remplir_rail(self) -> None:
        """La barre laterale du mode en cours : Dev ou PC."""
        interieur = self._rail
        for enfant in interieur.winfo_children():
            enfant.destroy()
        self._nav = {}
        mode = llm.mode_actuel()

        self._entete_rail(interieur, "conversation")
        self._cellule(interieur, CHAT_KEY, "Discuter", "parole",
                      colonne=None)

        # Une grille par rubrique, plutot qu'un seul mur d'icones.
        #
        # A dix-huit destinations, la grille passait encore. A vingt-deux, on
        # cherchait -- et c'est exactement ce qui s'est produit : les
        # nouvelles fonctions etaient invisibles faute d'un endroit ou les
        # attendre. Les rubriques rendent la place de chaque chose previsible,
        # et surtout elles MONTRENT ce qui existe.
        for cle, libelle in panels.CATEGORIES:
            dedans = [p for p in panels.PANELS
                      if p.categorie == cle and mode in p.modes]
            if not dedans:
                continue
            self._entete_rail(interieur, libelle)
            grille = tk.Frame(interieur, bg=t.SURFACE)
            grille.pack(fill="x", padx=(t.PAD, 0))
            for index, panel in enumerate(dedans):
                self._cellule(grille, panel.key, panel.court or panel.label,
                              panel.icone, colonne=index % RAIL_COLONNES,
                              ligne=index // RAIL_COLONNES)

    def _entete_rail(self, parent, texte: str) -> None:
        tk.Label(parent, text=t.espacer(texte), bg=t.SURFACE,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 2))

    def _cellule(self, parent, key: str, texte: str, icone: str,
                 colonne: int | None, ligne: int = 0) -> None:
        case = NavCell(parent, icone=icone, texte=texte,
                       command=lambda k=key: self.show(k),
                       largeur=CELLULE_LARGEUR)
        if colonne is None:
            case.pack(padx=t.PAD_L, pady=(2, 0), anchor="w")
        else:
            case.grid(row=ligne, column=colonne, padx=1, pady=1)
        self._nav[key] = case

    def _build_sidebar_bottom(self, side) -> None:
        """Les reglages de la conversation, sous le menu."""
        bottom = tk.Frame(side, bg=t.SURFACE)
        bottom.pack(side="bottom", fill="x", pady=(0, t.PAD_L))

        tk.Frame(bottom, bg=t.BORDER, height=1).pack(fill="x", pady=(0, t.PAD))

        # Dicter : la dictee de Windows (Win+H) ecrit dans la zone de texte
        # comme dans n'importe quelle application. La voix de l'assistant --
        # reconnaissance et lecture a voix haute -- a ete retiree le
        # 02/11/2026 : elle ne reconnaissait qu'une phrase sur six, la lecture
        # ne marchait pas, et Win+H fait mieux sans rien embarquer.
        tk.Label(bottom, text="Dicter : Win+H dans la zone de texte",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w").pack(fill="x", padx=t.PAD, pady=(2, 0))

        # Dev / PC : ce que le modele a sous la main. En Dev, il ne voit que
        # les outils du developpement -- plus rapide, et moins d'occasions de
        # se tromper d'outil.
        tk.Label(bottom, text="Mode", bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_TINY, anchor="w").pack(fill="x", padx=t.PAD,
                                                       pady=(t.PAD, 2))
        modes = tk.Frame(bottom, bg=t.SURFACE)
        modes.pack(fill="x", padx=t.PAD)
        self.boutons_mode = {}
        for mode, libelle in (("pc", "PC"), ("dev", "Dev")):
            bouton = RoundButton(modes, libelle,
                                 lambda m=mode: self.changer_mode(m),
                                 width=64, height=28, font=t.FONT_UI_TINY)
            bouton.pack(side="left", padx=(0, 6))
            self.boutons_mode[mode] = bouton
        self._montrer_mode()

        # Le modele : bascule entre ceux qui sont installes, comme dans
        # ChatGPT. La liste est relue a chaque clic, donc un modele que
        # l'installateur vient d'ajouter y apparait sans relancer.
        self.lien_modele = tk.Label(bottom, text="", bg=t.SURFACE,
                                    fg=t.ACCENT, font=t.FONT_UI_TINY,
                                    cursor="hand2", anchor="w")
        self.lien_modele.pack(fill="x", padx=t.PAD, pady=(6, 0))
        self.lien_modele.bind("<Button-1>", self.choisir_modele)
        self._montrer_modele()

        # Le projet Unreal de travail : choisi une fois, retenu ensuite.
        self.lien_projet = tk.Label(bottom, text="", bg=t.SURFACE,
                                    fg=t.ACCENT, font=t.FONT_UI_TINY,
                                    cursor="hand2", anchor="w")
        self.lien_projet.pack(fill="x", padx=t.PAD, pady=(6, 0))
        self.lien_projet.bind("<Button-1>", lambda _e: self.choisir_projet())
        self._montrer_projet()

        # Deux lignes : trois liens cote a cote depassaient de la barre.
        for rangee in ((("Composants", self.open_installer),),
                       (("Sauvegarder", self.sauvegarder_donnees),
                        ("Restaurer", self.restaurer_donnees))):
            liens = tk.Frame(bottom, bg=t.SURFACE)
            liens.pack(fill="x", padx=t.PAD, pady=(4, 0))
            for texte, action in rangee:
                lien = tk.Label(liens, text=texte, bg=t.SURFACE, fg=t.ACCENT,
                                font=t.FONT_UI_TINY, cursor="hand2")
                lien.pack(side="left", padx=(0, t.PAD))
                lien.bind("<Button-1>", lambda _e, a=action: a())

    def _montrer_modele(self) -> None:
        self.lien_modele.configure(text=f"Modele : {config.LLM_MODEL}  (changer)")

    def choisir_modele(self, evenement=None) -> None:
        from assistant import backend

        installes = backend.modeles_de_conversation()
        menu = tk.Menu(self, tearoff=False, bg=t.SURFACE, fg=t.TEXT,
                       activebackground=t.SURFACE_2, activeforeground=t.ACCENT)
        if not installes:
            menu.add_command(label="Aucun modele installe : ouvre Composants",
                             command=self.open_installer)
        for nom in installes:
            marque = "> " if nom == config.LLM_MODEL else "   "
            menu.add_command(label=marque + nom,
                             command=lambda n=nom: self._basculer_modele(n))
        x = evenement.x_root if evenement else self.winfo_pointerx()
        y = evenement.y_root if evenement else self.winfo_pointery()
        menu.tk_popup(x, y)

    def _basculer_modele(self, nom: str) -> None:
        from assistant import backend

        ancien = config.LLM_MODEL
        config.changer_modele(nom)
        self._montrer_modele()
        if ancien != nom:
            # 4B + 14B = 16,9 Go : ils ne tiennent pas ensemble sur 16 Go.
            threading.Thread(target=backend.decharger, args=(ancien,),
                             daemon=True).start()

    def changer_mode(self, mode: str) -> None:
        try:
            llm.changer_mode(mode)
        except llm.ModeVerrouille:
            self.fenetre_cle_dev()
            return
        self._montrer_mode()
        self._montrer_projet()
        self._remplir_rail()
        # En Dev, on arrive sur le panneau Projet : il montre le projet et
        # tout ce qu'on peut demander. Sinon, le panneau ouvert n'existe
        # peut-etre plus dans ce mode.
        panneau = panels.BY_KEY.get(self.current)
        if mode == "dev":
            self.show("unreal_projet")
        elif panneau is not None and mode not in panneau.modes:
            self.show(CHAT_KEY)
        elif self.current in self._nav:
            self._nav[self.current].set_actif(True)
        nom = "Dev" if mode == "dev" else "PC"
        self.post("status", (f"Mode {nom}", t.GREEN))

    def _mot_de_passe(self, titre: str, confirmer: bool) -> str | None:
        from tkinter import simpledialog

        premier = simpledialog.askstring(
            titre, "Mot de passe de l'archive (8 caracteres au moins) :",
            show="*", parent=self)
        if not premier:
            return None
        if confirmer:
            second = simpledialog.askstring(titre, "Retape-le :", show="*", parent=self)
            if second != premier:
                self.post("error", "Les deux mots de passe ne sont pas identiques.")
                return None
        return premier

    def sauvegarder_donnees(self) -> None:
        """Tout ce qu'on perdrait a une reinitialisation, dans une archive."""
        from tkinter import filedialog

        from assistant import sauvegarde

        dossier = filedialog.askdirectory(
            parent=self, title="Ou ranger la sauvegarde (cle USB, disque, OneDrive) ?")
        if not dossier:
            return
        mot = self._mot_de_passe("Sauvegarder", confirmer=True)
        if not mot:
            return
        self.post("status", ("Sauvegarde en cours", t.AMBER))
        threading.Thread(target=lambda: (
            self.post("info", sauvegarde.sauvegarder(dossier, mot)),
            self.post("status", ("Pret", t.GREEN))), daemon=True).start()

    def restaurer_donnees(self) -> None:
        from tkinter import filedialog

        from assistant import sauvegarde

        fichier = filedialog.askopenfilename(
            parent=self, title="Choisir la sauvegarde a restaurer",
            filetypes=[("Sauvegarde Assistant local", "*.alsauv")])
        if not fichier:
            return
        mot = self._mot_de_passe("Restaurer", confirmer=False)
        if not mot:
            return
        self.post("status", ("Restauration en cours", t.AMBER))

        def travail():
            message = sauvegarde.restaurer(fichier, mot)
            self.post("info", message + " Redemarre l'application pour tout recharger.")
            self.post("status", ("Pret", t.GREEN))

        threading.Thread(target=travail, daemon=True).start()

    def fenetre_cle_dev(self) -> None:
        from assistant import fenetre_cle

        def ouvrir_dev() -> None:
            self.changer_mode("dev")

        fenetre_cle.ouvrir(self, ouvrir_dev)

    def choisir_projet(self) -> None:
        if llm.mode_actuel() != "dev":
            return
        from tkinter import filedialog

        from assistant.skills import code, unreal

        recents = unreal.projets_recents()
        depart = str(recents[0].parent.parent) if recents else None
        chemin = filedialog.askdirectory(
            parent=self, title="Choisir le dossier du projet",
            initialdir=depart, mustexist=True)
        if not chemin:
            return
        self.post("info", code.choisir_projet(chemin))
        self._montrer_projet()

    def _montrer_projet(self) -> None:
        from assistant.skills import code

        if llm.mode_actuel() != "dev":
            # Le projet de travail ne concerne que le mode Dev.
            self.lien_projet.configure(text="", cursor="arrow")
            return
        nom = code.projet_nom()
        texte = f"Projet : {nom}" if nom else "Choisir le projet"
        self.lien_projet.configure(text=texte[:30], cursor="hand2")

    def _montrer_mode(self) -> None:
        actuel = llm.mode_actuel()
        for mode, bouton in self.boutons_mode.items():
            if mode == actuel:
                bouton.set_couleurs(t.ACCENT, "#0b1220", "#79b4ff")
            else:
                bouton.set_couleurs(t.SURFACE_2, t.TEXT_DIM, t.BORDER)

    # --- vue panneau ------------------------------------------------------

    def _build_panel_view(self) -> None:
        self.panel_view = tk.Frame(self.stage, bg=t.BG)

        entete = tk.Frame(self.panel_view, bg=t.BG)
        entete.pack(fill="x", padx=t.PAD_XL, pady=(t.PAD_L, t.PAD))

        self.panel_title = tk.Label(entete, text="", bg=t.BG, fg=t.TEXT,
                                    font=("Segoe UI Semibold", 14), anchor="w")
        self.panel_title.pack(side="left")

        self.panel_refresh = RoundButton(entete, "Actualiser",
                                         self._refresh_panel, width=104,
                                         bg=t.SURFACE_2, hover_bg=t.BORDER)
        self.panel_refresh.pack(side="right")

        cadre = tk.Frame(self.panel_view, bg=t.SURFACE)
        self.panel_frame = cadre
        cadre.pack(fill="both", expand=True, padx=t.PAD_XL,
                   pady=(0, t.PAD_XL))

        barre = tk.Scrollbar(cadre, bg=t.SURFACE, troughcolor=t.SURFACE,
                             activebackground=t.SURFACE_2,
                             highlightthickness=0, bd=0, width=10)
        barre.pack(side="right", fill="y")

        self.panel_text = tk.Text(
            cadre, bg=t.SURFACE, fg=t.TEXT, font=t.FONT_MONO, wrap="word",
            spacing1=1, spacing3=1,
            relief="flat", padx=t.PAD_L, pady=t.PAD_L, state="disabled",
            insertbackground=t.TEXT, yscrollcommand=barre.set,
        )
        self.panel_text.pack(fill="both", expand=True)
        barre.configure(command=self.panel_text.yview)

        self.panel_text.tag_configure("grave", foreground=t.RED,
                                      font=t.FONT_MONO_BOLD)
        self.panel_text.tag_configure("attention", foreground=t.AMBER,
                                      font=t.FONT_MONO_BOLD)
        self.panel_text.tag_configure("titre", foreground=t.ACCENT,
                                      font=t.FONT_MONO_TITRE,
                                      spacing1=6, spacing3=2)
        self.panel_text.tag_configure("remede", foreground=t.TEXT_DIM)
        # Les filets de separation : presents, mais ils ne doivent pas peser
        # autant que ce qu'ils separent.
        self.panel_text.tag_configure("regle", foreground=t.ACCENT_DEEP)
        # Une mesure est ce qu'on vient chercher dans un releve : elle doit
        # sauter aux yeux au milieu de sa phrase.
        self.panel_text.tag_configure("mesure", foreground=t.ACCENT,
                                      font=t.FONT_MONO_BOLD)
        self.panel_text.tag_configure("barre_pleine", foreground=t.ACCENT)
        self.panel_text.tag_configure("barre_vide", foreground=t.BORDER)

        # Accueil des panneaux interactifs : ils remplacent la zone de texte
        # quand le panneau affiche de vrais widgets.
        self.panel_widget_host = tk.Frame(self.panel_view, bg=t.BG)
        self.panel_widgets: dict[str, tk.Frame] = {}
        # Les exemples de l'accueil : cliquables, et ils doivent en avoir l'air.
        self.panel_text.tag_configure("exemple", foreground=t.ACCENT,
                                      font=t.FONT_MONO_BOLD)
        self.panel_text.tag_bind("exemple", "<Enter>",
                                 lambda _e: self.panel_text.configure(cursor="hand2"))
        self.panel_text.tag_bind("exemple", "<Leave>",
                                 lambda _e: self.panel_text.configure(cursor=""))
        self.panel_text.tag_bind("exemple", "<Button-1>", self._cliquer_exemple)

    def _render_panel(self, texte: str) -> None:
        """Met en forme un releve en texte brut.

        Les competences rendent du texte aligne, sans balises : c'est ce qui
        permet de l'envoyer tel quel au modele. La mise en valeur se fait donc
        ici, a la lecture, en reconnaissant les formes -- titres en capitales,
        filets, barres d'occupation, mesures chiffrees.
        """
        self.panel_text.configure(state="normal")
        self.panel_text.delete("1.0", "end")

        for ligne in texte.splitlines():
            depouille = ligne.strip()

            if ligne.startswith(panels.EXEMPLE):
                # On retire le marqueur a l'affichage : l'utilisateur voit
                # la phrase telle qu'il la dirait, pas un code interne.
                self.panel_text.insert(
                    "end", "  " + ligne[len(panels.EXEMPLE):] + "\n", "exemple")
                continue

            if depouille and _REGLE.match(depouille):
                self.panel_text.insert("end", ligne + "\n", "regle")
                continue

            base = ""
            if "[GRAVE]" in ligne:
                base = "grave"
            elif "[A SURVEILLER]" in ligne or "/!\\" in ligne:
                base = "attention"
            elif depouille.startswith("->"):
                base = "remede"
            elif (depouille and len(depouille) > 8
                  and depouille == depouille.upper()):
                base = "titre"

            # Un titre ou une alerte se lit d'un bloc : y colorier des mesures
            # au milieu casserait la ligne au lieu de la mettre en valeur.
            if base in ("titre", "grave", "attention"):
                self.panel_text.insert("end", ligne + "\n", base)
                continue

            for morceau, tag in _decouper(ligne, base):
                self.panel_text.insert("end", morceau, tag)
            self.panel_text.insert("end", "\n")

        self.panel_text.configure(state="disabled")
        self.panel_text.yview_moveto(0)

    def _cliquer_exemple(self, event) -> None:
        """Envoie la phrase d'exemple sur laquelle on vient de cliquer."""
        index = self.panel_text.index(f"@{event.x},{event.y}")
        debut = self.panel_text.index(f"{index} linestart")
        fin = self.panel_text.index(f"{index} lineend")
        phrase = self.panel_text.get(debut, fin).strip()
        if phrase:
            self.ask(phrase)

    def _montrer_interactif(self, panel) -> None:
        """Affiche un panneau fait de widgets plutot que de texte."""
        self.panel_frame.pack_forget()
        self.panel_widget_host.pack(fill="both", expand=True,
                                    padx=t.PAD_XL, pady=(0, t.PAD_XL))

        for enfant in self.panel_widget_host.winfo_children():
            enfant.pack_forget()

        widget = self.panel_widgets.get(panel.key)
        if widget is None:
            if panel.interactif == "startup":
                from assistant.optimiser import StartupOptimizer

                widget = StartupOptimizer(self.panel_widget_host, self)
            elif panel.interactif == "pupitre":
                from assistant.pupitre import Pupitre

                widget = Pupitre(self.panel_widget_host, self)
            elif panel.interactif == "ludotheque":
                from assistant.ludotheque import Ludotheque

                widget = Ludotheque(self.panel_widget_host, self)
            elif panel.interactif == "reparation":
                from assistant.reparation import Reparateur

                widget = Reparateur(self.panel_widget_host, self)
            elif panel.interactif == "atelier":
                from assistant.atelier import Atelier

                widget = Atelier(self.panel_widget_host, self)
            elif panel.interactif == "miseajour":
                from assistant.reseau_panneaux import MiseAJour

                widget = MiseAJour(self.panel_widget_host, self)
            else:
                return
            self.panel_widgets[panel.key] = widget
        else:
            widget.recharger()

        widget.pack(fill="both", expand=True)

    def _refresh_panel(self) -> None:
        if self.current == CHAT_KEY:
            return
        cle = self.current
        panel = panels.BY_KEY.get(cle)
        if panel is not None and panel.interactif:
            widget = self.panel_widgets.get(cle)
            if widget is not None:
                widget.recharger()
            return
        self._render_panel("Actualisation ...")

        def work():
            self.post("panneau", (cle, panels.content(cle, force=True)))

        threading.Thread(target=work, daemon=True).start()

    # --- vue conversation -------------------------------------------------

    def _build_chat_view(self) -> None:
        self.chat_view = tk.Frame(self.stage, bg=t.BG)

        self.chat = ScrollArea(self.chat_view, bg=t.BG)
        self.chat.pack(fill="both", expand=True)
        self.chat.canvas.bind("<Configure>", self._on_resize, add="+")

        # Temoin du panneau joint a la question. Il est VISIBLE, et retirable :
        # l'assistant ne doit jamais lire par-dessus l'epaule de l'utilisateur
        # sans que celui-ci le sache. C'est aussi ce qui rend le comportement
        # previsible -- sans ce bandeau, une question sans rapport se
        # retrouverait accompagnee d'un panneau consulte dix minutes plus tot,
        # sans explication.
        self.contexte_bar = tk.Frame(self.chat_view, bg=t.BG)
        self.contexte_texte = tk.Label(
            self.contexte_bar, text="", bg=t.BG, fg=t.TEXT_FAINT,
            font=t.FONT_UI_TINY, anchor="w")
        self.contexte_texte.pack(side="left")
        self.contexte_retirer = tk.Label(
            self.contexte_bar, text="  retirer", bg=t.BG, fg=t.ACCENT,
            font=t.FONT_UI_TINY, cursor="hand2")
        self.contexte_retirer.pack(side="left")
        self.contexte_retirer.bind("<Button-1>",
                                   lambda _e: self.oublier_contexte())

        # Temoin des fichiers joints, sur le meme principe que celui du
        # panneau : visible et retirable. Un fichier qui reste attache sans
        # qu'on le sache partirait avec une question sans rapport, dix minutes
        # plus tard.
        self.fichiers_bar = tk.Frame(self.chat_view, bg=t.BG)
        self.fichiers_texte = tk.Label(
            self.fichiers_bar, text="", bg=t.BG, fg=t.TEXT_FAINT,
            font=t.FONT_UI_TINY, anchor="w")
        self.fichiers_texte.pack(side="left")
        self.fichiers_retirer = tk.Label(
            self.fichiers_bar, text="  retirer", bg=t.BG, fg=t.ACCENT,
            font=t.FONT_UI_TINY, cursor="hand2")
        self.fichiers_retirer.pack(side="left")
        self.fichiers_retirer.bind("<Button-1>",
                                   lambda _e: self.oublier_fichiers())

        # Conserve : le temoin de contexte s'insere au-dessus de cette barre,
        # et pack() sans reference le placerait en dessous.
        bar = self._barre_saisie = tk.Frame(self.chat_view, bg=t.BG)
        bar.pack(fill="x", padx=t.PAD_L, pady=t.PAD_L)

        field = tk.Frame(bar, bg=t.SURFACE_2, highlightthickness=1,
                         highlightbackground=t.BORDER)
        field.pack(side="left", fill="x", expand=True)
        self.entry = tk.Entry(field, bg=t.SURFACE_2, fg=t.TEXT,
                              insertbackground=t.ACCENT, relief="flat",
                              font=t.FONT_INPUT)
        self.entry.pack(fill="x", padx=t.PAD_L, pady=10)
        self.entry.bind("<Return>", lambda _e: self.send())

        # Le trombone. Il ouvre le selecteur de Windows plutot que de demander
        # un chemin : personne ne tape "C:\\Users\\...\\Documents\\devis.pdf"
        # a la main, et une faute de frappe rendait un "fichier introuvable"
        # qu'on prenait pour une incapacite de l'assistant.
        self.joindre_btn = RoundButton(bar, "Joindre", self.joindre_fichiers,
                                       width=96, bg=t.SURFACE_2,
                                       hover_bg=t.BORDER)
        self.joindre_btn.pack(side="left", padx=(t.PAD, 0))

        self.send_btn = RoundButton(bar, "Envoyer", self.send, width=96,
                                    bg=t.ACCENT, fg="#0b1220",
                                    hover_bg="#79b4ff")
        self.send_btn.pack(side="left", padx=(t.PAD, 0))

    # =====================================================================
    # Contexte joint aux questions
    # =====================================================================

    def _montrer_contexte(self) -> None:
        """Affiche ou masque le bandeau du panneau joint."""
        joint = None
        if self._contexte_panneau:
            joint = panels.contexte(self._contexte_panneau)

        if joint is None:
            self.contexte_bar.pack_forget()
            return

        libelle, _contenu = joint
        self.contexte_texte.configure(text=f"Joint a ta question : {libelle}")
        self.contexte_bar.pack(fill="x", padx=t.PAD_L, pady=(0, 4),
                               before=self._barre_saisie)

    # =====================================================================
    # Fichiers joints a la question
    # =====================================================================

    def joindre_fichiers(self) -> None:
        """Ouvre le selecteur de Windows et retient ce qui a ete choisi.

        Rien n'est LU ici. La lecture d'un PDF de deux cents pages prend
        plusieurs secondes, et la faire sur le fil graphique figerait la
        fenetre entre le clic et la question -- l'utilisateur croirait
        l'application plantee. On lit au moment de l'envoi, sur le fil de
        travail, comme tout le reste.
        """
        from tkinter import filedialog

        choisis = filedialog.askopenfilenames(
            parent=self,
            title="Joindre des fichiers a la question",
            filetypes=[
                ("Tout ce que je sais lire",
                 "*.txt *.md *.pdf *.docx *.xlsx *.pptx *.csv *.json *.log "
                 "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                ("Documents", "*.pdf *.docx *.xlsx *.pptx *.txt *.md *.csv"),
                ("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if not choisis:
            return
        # On ajoute a ce qui est deja joint : deux clics sur le trombone
        # doivent additionner, pas remplacer.
        for chemin in choisis:
            if chemin not in self._fichiers_joints:
                self._fichiers_joints.append(chemin)
        self._montrer_fichiers()

    def _montrer_fichiers(self) -> None:
        """Affiche le bandeau des fichiers joints, ou le masque."""
        from pathlib import Path

        if not self._fichiers_joints:
            self.fichiers_bar.pack_forget()
            return

        noms = ", ".join(Path(c).name for c in self._fichiers_joints[:3])
        reste = len(self._fichiers_joints) - 3
        if reste > 0:
            noms += f" et {reste} autre" + ("s" if reste > 1 else "")
        self.fichiers_texte.configure(text=f"Joint a ta question : {noms}")
        self.fichiers_bar.pack(fill="x", padx=t.PAD_L, pady=(0, 4),
                               before=self._barre_saisie)

    def oublier_fichiers(self) -> None:
        """Detache les fichiers, sur demande de l'utilisateur."""
        self._fichiers_joints = []
        self._montrer_fichiers()

    def _lire_fichiers_joints(self, chemins: list[str]) -> list[dict]:
        """Lit les fichiers joints et les presente au modele comme des donnees.

        Les IMAGES passent par vision.read_image(), pas par read_text(). La
        premiere version appelait directement l'OCR, ce qui court-circuitait
        le modele de vision : meme installe, il n'aurait jamais servi pour un
        fichier joint. Le 24/08/2026 l'assistant a decrit deux captures
        d'ecran qu'il n'avait pas vues -- il avait recu du texte OCR deforme
        ("Eure Truck Simul", "Assetto Cors") et l'avait remis en mots
        plausibles. Une lecture inventee ressemble a une lecture.

        Un fichier illisible n'interrompt pas les autres et ne disparait pas
        en silence : la raison part au modele, qui pourra la dire. Un joint
        qu'on croit lu et qui ne l'est pas est pire qu'un joint refuse.
        """
        from pathlib import Path

        from assistant.skills import content, vision

        messages = []
        for chemin in chemins:
            nom = Path(chemin).name
            image = False
            try:
                if vision.is_image(chemin):
                    image = True
                    # read_image essaie le modele de vision, puis retombe sur
                    # l'OCR. Il annonce lui-meme lequel a servi.
                    texte = vision.read_image(chemin)
                    ok = bool(str(texte).strip())
                    libelle = f"image {nom}"
                else:
                    ok, texte = content.extract(chemin)
                    libelle = f"fichier {nom}"
            except Exception as exc:  # noqa: BLE001 - un joint muet vaut mieux qu'un plantage
                ok, texte = False, f"{type(exc).__name__}: {exc}"
                libelle = f"{'image' if image else 'fichier'} {nom}"

            if not ok or not str(texte).strip():
                texte = (f"[illisible : {texte}]" if texte
                         else "[aucun texte lisible dans ce fichier]")
            messages.append(
                llm.message_de_fichier_joint(libelle, str(texte), image=image))
        return messages

    def oublier_contexte(self) -> None:
        """Detache le panneau, sur demande de l'utilisateur."""
        self._contexte_panneau = None
        self.convo = llm.sans_contexte(self.convo)
        self._montrer_contexte()

    # =====================================================================
    # Navigation
    # =====================================================================

    def show(self, key: str) -> None:
        self.current = key
        for cle, case in self._nav.items():
            case.set_actif(cle == key)

        self.panel_view.pack_forget()
        self.chat_view.pack_forget()

        if key == CHAT_KEY:
            self.chat_view.pack(fill="both", expand=True)
            self._montrer_contexte()
            self.entry.focus_set()
            return

        # Consulter un panneau le joint aux questions suivantes : c'est la
        # sequence reelle -- on lit "Problemes detectes", on revient sur la
        # conversation, on tape "corrige ca".
        if key not in panels.SANS_CONTEXTE:
            self._contexte_panneau = key

        panel = panels.BY_KEY.get(key)
        self.panel_title.configure(text=panel.label if panel else key)
        self.panel_view.pack(fill="both", expand=True)

        if panel is not None and panel.interactif:
            self._montrer_interactif(panel)
            return

        self.panel_widget_host.pack_forget()
        self.panel_frame.pack(fill="both", expand=True, padx=t.PAD_XL,
                              pady=(0, t.PAD_XL))

        if panel is not None and not panel.live and panels.is_ready(key):
            self._render_panel(panels.content(key))
            return

        self._render_panel("Preparation ...")

        def work():
            self.post("panneau", (key, panels.content(key)))

        threading.Thread(target=work, daemon=True).start()

    # =====================================================================
    # Evenements
    # =====================================================================

    def post(self, kind: str, payload) -> None:
        self.events.put((kind, payload))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    texte, couleur = payload
                    self.status_text.set(texte)
                    self.dot.set_color(couleur)
                elif kind == "busy":
                    self._set_busy(payload)
                elif kind == "appel":
                    # Un thread demande a executer quelque chose sur le fil
                    # principal. C'est la seule facon sure de toucher aux
                    # widgets depuis un travail de fond : after() appele
                    # depuis un thread echoue des que la boucle Tk n'est pas
                    # celle du thread appelant.
                    try:
                        payload()
                    except Exception:  # noqa: BLE001
                        pass
                elif kind == "panneau":
                    cle, texte = payload
                    if self.current == cle:
                        self._render_panel(texte)
                elif kind == "alerte":
                    self.add(payload, "user")
                    self.chat_view.pack_forget()
                    self.show(CHAT_KEY)
                    try:
                        self.deiconify()
                        self.lift()
                        self.focus_force()
                    except tk.TclError:
                        pass
                else:
                    self.add(payload, kind)
        except queue.Empty:
            pass
        self.after(50, self._drain)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.send_btn.set_enabled(not busy)

    # =====================================================================
    # Demarrage
    # =====================================================================

    def _montrer_la_fenetre(self) -> None:
        """Revele la fenetre principale, une fois l'ecran d'accueil efface."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _boot(self) -> None:
        self.add("Pose ta question ici, ou clique \"Par ou commencer\" a "
                 "gauche pour voir des exemples.", "info")

        # L'ecran de chargement HABILLE l'attente, il ne la cree pas : le
        # travail ci-dessous part immediatement, en parallele. S'il n'a pas pu
        # s'ouvrir -- video absente, codec manquant -- accueil vaut None et
        # tout se passe exactement comme avant.
        from assistant import demarrage

        accueil = demarrage.ouvrir(self, a_la_fin=self._montrer_la_fenetre)
        if accueil is not None:
            # Masquee, pas fermee : elle continue de se construire derriere.
            # Sans ce retrait, on la voyait se remplir par-dessous son propre
            # ecran d'accueil.
            self.withdraw()
            # FILET DE SECURITE, et il n'est pas theorique : si l'ecran
            # d'accueil se bloque ou meurt sans prevenir -- codec absent dans
            # la version packagee, Tk qui refuse une image -- la fenetre
            # resterait masquee pour toujours et l'application paraitrait
            # plantee. Au-dela de dix secondes, elle revient quoi qu'il
            # arrive. deiconify sur une fenetre deja visible ne coute rien.
            self.after(10000, self._montrer_la_fenetre)

        def etape(texte: str) -> None:
            if accueil is not None:
                self.post("appel", lambda: accueil.etape(texte))

        def work():
            etape("Demarrage du moteur ...")
            self.post("status", ("Demarrage du moteur", t.AMBER))
            ok, message = llm.available(
                on_progress=lambda m: self.post("status", (m[:28], t.AMBER))
            )
            if not ok:
                self.post("error", message)

            etape("Analyse de la machine ...")
            self.post("status", ("Analyse de la machine", t.AMBER))
            hardware.collect()
            games.all_games()
            panels.prime(["configuration", "problemes", "jeux", "demarrage",
                          "correctifs"])
            self.post("info", hardware.summary())

            # L'inventaire logiciel : ce qui est installe, les services, les
            # taches, les pilotes. Le RELEVE se refait a chaque demarrage --
            # un logiciel desinstalle hier ne doit pas reapparaitre -- mais ce
            # qu'il verse dans la connaissance, lui, est conserve.
            etape("Inventaire logiciel ...")
            self.post("status", ("Inventaire logiciel", t.AMBER))
            apprentissage.tout_apprendre()
            self.post("info", connaissance.rapport().splitlines()[0])

            # Trois cas, alors qu'un seul existait avant que l'index soit
            # conserve : absent, perime, ou utilisable tel quel.
            age = db.age_de_l_index()
            if not db.is_ready() or db.index_perime():
                if age is not None:
                    self.post("info",
                              f"Index vieux de {age:.0f} jours : on le refait.")
                self.post("status", ("Scan des fichiers", t.AMBER))
                stats = scanner.rebuild(verbose=False)
                nombre = f"{stats.get('files', 0):,}".replace(",", " ")
                ou = ("conserves d'une fois sur l'autre"
                      if config.PERSIST_INDEX else "en memoire uniquement")
                self.post("info", f"{nombre} fichiers connus, {ou}.")
            elif age is not None:
                self.post("info", "Index relu du lancement precedent "
                                  f"(scan d'il y a {age:.0f} jours).")

            # La surveillance demarre TOUJOURS, index reconstruit ou relu.
            # Elle etait enfermee dans le bloc du scan : des lors qu'un index
            # conserve permet d'eviter ce scan, plus rien ne suivait les
            # fichiers et l'index vieillissait sans que personne le rattrape.
            if watcher.start() is not None:
                self.post("info", watcher.status())
            panels.prime(["espace", "fichiers"])

            etape("Pret.")
            self.post("status", ("Pret", t.GREEN))
            if accueil is not None:
                self.post("appel", accueil.application_prete)

        threading.Thread(target=work, daemon=True).start()
        self._brancher_alertes()

    def _brancher_alertes(self) -> None:
        """Affiche et annonce les minuteurs et surveillances qui se declenchent.

        Sans cela, une alerte se declenche dans un thread et personne n'en
        sait rien : l'utilisateur regle un minuteur qui ne le previent jamais.
        """
        from assistant.skills import reminders

        def prevenir(alerte) -> None:
            detail = f"  ({alerte.detail})" if alerte.detail else ""
            retard = "  (en retard : l'assistant etait ferme)" if getattr(
                alerte, "en_retard", False) else ""
            self.post("alerte", f"{alerte.message}{detail}{retard}")

        reminders.set_notifier(prevenir)

        # Le notifier D'ABORD, la relecture ENSUITE : une echeance deja passee
        # se declenche des le premier tour de boucle, et sans destinataire
        # branche elle serait perdue une seconde fois.
        repris = reminders.charger()
        if repris:
            self.post("alerte", repris)

    # =====================================================================
    # Conversation
    # =====================================================================

    def _wrap_width(self) -> int:
        return max(self.chat.canvas.winfo_width() - 2 * t.PAD_XL - 24, 240)

    def _on_resize(self, _e=None) -> None:
        largeur = self._wrap_width()
        for message in self._messages:
            message.set_wrap(largeur)

    # Les roles qui meritent un cadre plutot qu'une couleur de texte.
    #
    # Un message important ecrit en rouge au milieu du reste se lit comme du
    # decor : rien ne le separe de ce qui l'entoure, et l'oeil finit par le
    # sauter. C'est ce qui arrivait a l'avertissement de fermeture anormale.
    BANDEAUX = {"error": "erreur", "warn": "alerte"}

    def add(self, texte: str, role: str = "assistant") -> None:
        for abonne in list(self.abonnes_reponse):
            try:
                abonne(role, texte)
            except Exception:  # noqa: BLE001
                pass
        ton = self.BANDEAUX.get(role)
        if ton:
            message = Bandeau(self.chat.inner, texte, ton=ton)
        else:
            message = Message(self.chat.inner, texte, role, self._wrap_width())
        message.pack(fill="x", pady=(0, t.PAD) if ton else 0)
        self._messages.append(message)
        self.chat.scroll_to_bottom()

    def send(self) -> None:
        texte = self.entry.get().strip()
        if texte:
            self.entry.delete(0, "end")
            self.ask(texte)

    def ask(self, question: str) -> None:
        if self.busy:
            return
        self.show(CHAT_KEY)
        self.add(question, "user")
        self._set_busy(True)
        self.post("status", ("Reflexion", t.AMBER))

        # Fige le contexte maintenant, sur le fil graphique. Le fil de travail
        # met plusieurs secondes a repondre, pendant lesquelles l'utilisateur
        # peut ouvrir un autre panneau : la question doit partir avec ce qu'il
        # avait sous les yeux en l'ecrivant, pas avec ce qu'il regarde depuis.
        joint = (panels.contexte(self._contexte_panneau)
                 if self._contexte_panneau else None)

        # Les fichiers joints partent AVEC cette question-la, puis sont
        # detaches. Les laisser colles rejouerait un devis de trois cents
        # pages a chaque phrase suivante, sans que personne comprenne
        # pourquoi les reponses derivent.
        fichiers = list(self._fichiers_joints)
        if fichiers:
            self.oublier_fichiers()

        def work():
            # Le contexte est remplace, jamais empile : cinq questions devant
            # le meme panneau ne doivent pas laisser cinq copies de son
            # contenu dans l'historique.
            self.convo = llm.sans_contexte(self.convo)
            if joint is not None:
                self.convo.append(llm.message_de_contexte(*joint))
            if fichiers:
                self.post("status", ("Lecture des fichiers", t.AMBER))
                self.convo.extend(self._lire_fichiers_joints(fichiers))
            self.convo.append({"role": "user", "content": question})
            try:
                reponse, self.convo = llm.chat(
                    self.convo,
                    on_tool=lambda n, a: self.post("tool", f"    > {n}  {_resume_args(a)}"),
                    # Ce que l'outil a rendu : l'utilisateur voit ce que
                    # l'assistant a fait, pas seulement son nom.
                    on_result=lambda _n, r: self.post("tool", f"      = {_resume_resultat(r)}"),
                )
                self.post("assistant", reponse)
            except Exception as exc:  # noqa: BLE001
                self.post("error", str(exc))
            # Elagage sur la taille reelle, plus sur un nombre de messages
            # fige : voir llm.trim_conversation.
            self.convo = llm.trim_conversation(self.convo)
            self.post("status", ("Pret", t.GREEN))
            self.post("busy", False)

        threading.Thread(target=work, daemon=True).start()

    # =====================================================================
    # Confirmation des actions
    # =====================================================================

    def _brancher_confirmation(self) -> None:
        """Fait passer les demandes d'accord par une fenetre, pas par le
        terminal.

        Sans cela, l'application packagee en mode fenetre n'a pas d'entree
        standard : la demande echouait sur "lost sys.stdin" et toute action
        du modele plantait avant d'etre proposee.
        """
        from assistant import safety

        safety.set_asker(self._demander_accord)

    def ouvrir_le_support(self) -> None:
        """Fenetre de signalement : ce qu'on a vu, et ce qui sera joint.

        Le contexte technique est AFFICHE, pas seulement annonce. Un rapport
        assemble dans le dos de la personne qui le signe est exactement ce
        qu'on ne veut pas -- et le depot est public, donc ce qui part y reste.
        """
        from assistant import support

        dialogue = tk.Toplevel(self)
        dialogue.title("Signaler un probleme")
        dialogue.configure(bg=t.BG)
        dialogue.transient(self)

        cadre = tk.Frame(dialogue, bg=t.BG)
        cadre.pack(fill="both", expand=True, padx=t.PAD_XL, pady=t.PAD_L)

        tk.Label(cadre, text=t.espacer("signaler un probleme"), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", pady=(0, t.PAD))
        # Ou ca casse, nomme par le GESTE et non par le module.
        #
        # Demander "quel composant ?" suppose de savoir lequel est en cause,
        # ce qu'on ignore precisement quand on rencontre un defaut. Le choix
        # part aussi dans le titre de l'issue : les rapports se trient seuls.
        tk.Label(cadre, text="Ou est-ce que ca s'est passe ?", bg=t.BG,
                 fg=t.TEXT_DIM, font=t.FONT_UI_SMALL, anchor="w").pack(
            fill="x", pady=(0, 4))

        categorie = tk.StringVar(value=support.CATEGORIES[0][0])
        grille = tk.Frame(cadre, bg=t.BG)
        grille.pack(fill="x", pady=(0, t.PAD))
        for index, (nom, _aide) in enumerate(support.CATEGORIES):
            tk.Radiobutton(
                grille, text=nom, value=nom, variable=categorie,
                bg=t.BG, fg=t.TEXT, selectcolor=t.SURFACE_2,
                activebackground=t.BG, activeforeground=t.ACCENT,
                font=t.FONT_UI_SMALL, anchor="w", highlightthickness=0,
            ).grid(row=index // 3, column=index % 3, sticky="w",
                   padx=(0, t.PAD))

        tk.Label(cadre, text="Qu'est-ce qui s'est passe ? Ce que tu faisais, "
                             "ce que tu attendais, ce qui est arrive.",
                 bg=t.BG, fg=t.TEXT_DIM, font=t.FONT_UI_SMALL, anchor="w",
                 justify="left", wraplength=560).pack(fill="x")

        saisie = tk.Text(cadre, height=7, bg=t.SURFACE_2, fg=t.TEXT,
                         insertbackground=t.ACCENT, relief="flat",
                         font=t.FONT_INPUT, wrap="word",
                         highlightthickness=1, highlightbackground=t.BORDER)
        saisie.pack(fill="x", pady=t.PAD)
        saisie.focus_set()

        joindre = tk.BooleanVar(value=True)
        technique = support.contexte()
        tk.Checkbutton(
            cadre, variable=joindre, bg=t.BG, fg=t.TEXT_DIM,
            selectcolor=t.SURFACE_2, activebackground=t.BG,
            activeforeground=t.TEXT, font=t.FONT_UI_SMALL, anchor="w",
            text="Joindre les informations ci-dessous").pack(fill="x")

        tk.Label(cadre, text=technique, bg=t.SURFACE, fg=t.TEXT_FAINT,
                 font=t.FONT_MONO, anchor="w", justify="left",
                 wraplength=560).pack(fill="x", pady=(4, t.PAD))

        # La capture est PREPAREE, pas envoyee : GitHub n'accepte pas d'image
        # par adresse. On la depose sur le Bureau et on dit ou elle est. Ce
        # detour laisse aussi l'occasion de regarder ce qu'on publie -- une
        # capture montre tout ce qui etait a l'ecran, sur un depot public.
        avec_capture = tk.BooleanVar(value=False)
        tk.Checkbutton(
            cadre, variable=avec_capture, bg=t.BG, fg=t.TEXT_DIM,
            selectcolor=t.SURFACE_2, activebackground=t.BG,
            activeforeground=t.TEXT, font=t.FONT_UI_SMALL, anchor="w",
            text="Joindre une capture d'ecran (deposee sur le Bureau, "
                 "a glisser dans le formulaire)").pack(fill="x")

        etat = tk.Label(cadre, text="Le formulaire s'ouvrira dans ton "
                                    "navigateur : rien n'est envoye tant que "
                                    "tu n'as pas publie.",
                        bg=t.BG, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                        anchor="w", justify="left", wraplength=560)
        etat.pack(fill="x")

        def envoyer() -> None:
            texte = saisie.get("1.0", "end").strip()
            if not texte:
                etat.configure(text="Ecris d'abord ce qui s'est passe.",
                               fg=t.AMBER)
                return

            image = ""
            if avec_capture.get():
                # La fenetre se cache le temps du cliche : sinon la capture
                # montre le formulaire de signalement plutot que le probleme.
                dialogue.withdraw()
                self.update_idletasks()
                ok, resultat = support.capture_pour_le_rapport()
                dialogue.deiconify()
                if ok:
                    image = resultat
                else:
                    etat.configure(text=resultat, fg=t.AMBER)

            etat.configure(
                text=support.ouvrir(texte, joindre.get(), categorie.get(),
                                    image),
                fg=t.TEXT_FAINT)
            dialogue.after(2500, dialogue.destroy)

        boutons = tk.Frame(cadre, bg=t.BG)
        boutons.pack(fill="x", pady=(t.PAD_L, 0))
        RoundButton(boutons, "Ouvrir le formulaire", envoyer, width=190,
                    bg=t.ACCENT, fg="#0b1220",
                    hover_bg="#79b4ff").pack(side="left")
        RoundButton(boutons, "Annuler", dialogue.destroy, width=104,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(side="left",
                                                            padx=(t.PAD, 0))

        dialogue.grab_set()

    def _demander_accord(self, texte: str) -> bool:
        """Appele depuis un thread de travail : marshale vers le fil principal.

        Le thread se met en attente pendant que la fenetre s'affiche, et
        repart avec la reponse.
        """
        reponse: dict = {}
        fini = threading.Event()

        def montrer():
            try:
                reponse["ok"] = self._fenetre_accord(texte)
            except Exception:  # noqa: BLE001
                reponse["ok"] = False
            fini.set()

        self.post("appel", montrer)
        # Cinq minutes : au-dela, l'utilisateur est parti, on refuse.
        if not fini.wait(timeout=300):
            return False
        return bool(reponse.get("ok", False))

    def _fenetre_accord(self, texte: str) -> bool:
        """Fenetre modale decrivant l'action, en attente d'un accord."""
        dialogue = tk.Toplevel(self)
        dialogue.title("Confirmation")
        dialogue.configure(bg=t.BG)
        dialogue.transient(self)
        dialogue.resizable(False, False)

        cadre = tk.Frame(dialogue, bg=t.BG)
        cadre.pack(fill="both", expand=True, padx=t.PAD_XL, pady=t.PAD_L)

        tk.Label(cadre, text=t.espacer("action a confirmer"), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", pady=(0, t.PAD))

        corps = tk.Frame(cadre, bg=t.SURFACE)
        corps.pack(fill="both", expand=True)
        # Un Text plutot qu'un Label : une modification de code se montre
        # comme une difference, lignes retirees en rouge et ajoutees en vert,
        # et une longue difference defile au lieu de pousser les boutons
        # hors de l'ecran.
        lignes = texte.splitlines()
        zone = tk.Text(corps, bg=t.SURFACE, fg=t.TEXT, font=t.FONT_MONO,
                       wrap="word", relief="flat", bd=0, highlightthickness=0,
                       width=88, height=min(max(len(lignes), 3), 26),
                       padx=t.PAD_L, pady=t.PAD_L)
        zone.tag_configure("plus", foreground=t.GREEN)
        zone.tag_configure("moins", foreground=t.RED)
        zone.tag_configure("bloc", foreground=t.ACCENT_DEEP)
        # Tabulations de quatre caracteres, comme dans un editeur de code.
        from tkinter import font as tkfont

        zone.configure(tabs=(tkfont.Font(font=t.FONT_MONO).measure("    "),))
        for ligne in lignes:
            # Seules les lignes de la difference commencent en colonne 0 par
            # + ou - ; les cibles de l'action, elles, sont en retrait.
            style = ()
            if ligne.startswith("+") and not ligne.startswith("+++"):
                style = "plus"
            elif ligne.startswith("-") and not ligne.startswith("---"):
                style = "moins"
            elif ligne.startswith("@@"):
                style = "bloc"
            zone.insert("end", ligne + "\n", style)
        zone.configure(state="disabled")
        if len(lignes) > 26:
            barre = tk.Scrollbar(corps, command=zone.yview)
            zone.configure(yscrollcommand=barre.set)
            barre.pack(side="right", fill="y")
        zone.pack(fill="both", expand=True)

        tk.Label(cadre, text="Rien ne sera fait sans ton accord. "
                             "Cette decision est journalisee.",
                 bg=t.BG, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w").pack(fill="x", pady=(t.PAD, 0))

        choix = {"ok": False}

        def repondre(accepte: bool) -> None:
            choix["ok"] = accepte
            dialogue.destroy()

        boutons = tk.Frame(cadre, bg=t.BG)
        boutons.pack(fill="x", pady=(t.PAD_L, 0))

        RoundButton(boutons, "Confirmer", lambda: repondre(True), width=118,
                    bg=t.ACCENT, fg="#06222A",
                    hover_bg="#7BE3F2").pack(side="right")
        RoundButton(boutons, "Annuler", lambda: repondre(False), width=104,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(
            side="right", padx=(0, t.PAD))

        # Annuler par defaut : la touche Echap et la croix refusent.
        dialogue.protocol("WM_DELETE_WINDOW", lambda: repondre(False))
        dialogue.bind("<Escape>", lambda _e: repondre(False))

        dialogue.update_idletasks()
        largeur = dialogue.winfo_width()
        hauteur = dialogue.winfo_height()
        x = self.winfo_rootx() + (self.winfo_width() - largeur) // 2
        y = self.winfo_rooty() + (self.winfo_height() - hauteur) // 3
        dialogue.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        dialogue.grab_set()
        dialogue.focus_force()
        self.wait_window(dialogue)
        return choix["ok"]

    # =====================================================================
    # Installateur
    # =====================================================================

    def open_installer(self) -> None:
        """Ouvre l'installateur dans un processus separe.

        Il telecharge des modeles de plusieurs giga-octets : le faire dans
        cette fenetre figerait la conversation en cours.
        """
        if getattr(sys, "frozen", False):
            commande = [sys.executable, "--installer"]
        else:
            racine = Path(__file__).resolve().parent.parent
            commande = [sys.executable, str(racine / "AssistantLocal.py"),
                        "--installer"]
        try:
            subprocess.Popen(commande)
        except OSError as exc:
            self.post("error", f"Impossible d'ouvrir l'installateur : {exc}")

    # =====================================================================
    # Fin de vie
    # =====================================================================

    def report_callback_exception(self, exc, val, tb) -> None:
        """Recupere les erreurs que Tkinter ferait disparaitre.

        Tk attrape ce qui echoue dans un callback et l'imprime sur la sortie
        d'erreur. En mode fenetre, cette sortie n'existe pas : le bouton ne
        fait rien, et il n'y a rien a lire nulle part. On les ecrit, et on le
        dit dans la conversation plutot que de laisser croire a un clic rate.
        """
        import traceback as _tb

        texte = "".join(_tb.format_exception(exc, val, tb))
        try:
            from assistant import vie

            vie.noter_exception(texte)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.post("error", f"{exc.__name__}: {val}")
        except Exception:  # noqa: BLE001
            pass

    def _fermer_proprement(self) -> None:
        """Note QUI a ferme la fenetre, puis ferme.

        Sans cette ligne, une fermeture volontaire et une mort brutale
        laissaient exactement la meme chose derriere elles : rien.
        """
        try:
            from assistant import vie

            vie.arret("fenetre fermee par l'utilisateur")
        except Exception:  # noqa: BLE001
            pass
        self.destroy()


# Renseigne par le lanceur quand la session precedente s'est mal terminee.
MESSAGE_DE_REPRISE = ""


def main() -> int:
    fenetre = AssistantWindow()
    fenetre.protocol("WM_DELETE_WINDOW", fenetre._fermer_proprement)
    try:
        from assistant import mini_fenetre

        mini = mini_fenetre.MiniFenetre(fenetre)
        fenetre.mini_raccourci = mini_fenetre.demarrer_raccourci(fenetre, mini)
    except Exception as exc:  # noqa: BLE001
        # Un raccourci indisponible ne doit pas empecher l'application de
        # s'ouvrir : on le dit, et la grande fenetre reste utilisable.
        fenetre.add(f"Mini-fenêtre indisponible : {exc}", "error")
    if MESSAGE_DE_REPRISE:
        fenetre.after(1200, lambda: fenetre.post("error", MESSAGE_DE_REPRISE))
    fenetre.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
