"""Pupitre de controle : de vrais boutons, plus un releve en texte.

Le panneau precedent affichait le volume, la sortie audio et le profil
d'alimentation sous forme de lignes de texte. On y lisait l'etat de la
machine sans pouvoir rien y changer -- il fallait retourner dans la
conversation et dicter une phrase pour monter le son.

Trois principes ici :

  1. Ce qui s'affiche se clique. Un reglage qu'on voit et qu'on ne peut pas
     toucher est une frustration, pas une information.
  2. Chaque entree mene a l'endroit EXACT du systeme, pas a la page d'accueil
     des parametres. "Ou est-ce qu'on regle ca ?" est la question qui fait
     perdre le plus de temps dans Windows.
  3. Tout ce qui est lent part dans un thread. Lire les peripheriques audio
     prend pres d'une seconde, et l'interface ne doit jamais figer.
"""
from __future__ import annotations

import threading
import tkinter as tk

from assistant import theme as t
from assistant.widgets import RoundButton, ScrollArea

# Les raccourcis proposes, dans l'ordre ou on les cherche vraiment.
RACCOURCIS = [
    ("son", "Parametres du son"),
    ("peripheriques_audio", "Peripheriques audio"),
    ("melangeur", "Volume par application"),
    ("alimentation", "Alimentation et veille"),
    ("profils_alimentation", "Profils d'alimentation"),
    ("affichage", "Affichage"),
    ("demarrage", "Applications au demarrage"),
    ("applications", "Applications installees"),
    ("stockage", "Stockage"),
    ("bluetooth", "Bluetooth et appareils"),
    ("reseau", "Reseau"),
    ("confidentialite_micro", "Acces au microphone"),
    ("notifications", "Notifications"),
    ("gestionnaire", "Gestionnaire des taches"),
    ("peripheriques", "Gestionnaire de peripheriques"),
    ("disques", "Nettoyage de disque"),
]

MEDIA = [
    ("precedent", "|<<", "Piste ou chapitre precedent"),
    ("play", "> ||", "Lecture ou pause"),
    ("suivant", ">>|", "Piste ou chapitre suivant"),
    ("stop", "[ ]", "Arreter la lecture"),
]

PROFILS = [
    ("performance", "Performance"),
    ("equilibre", "Equilibre"),
    ("economie", "Economie"),
]

# Teintes d'un clic. Le nom, pas le code : c'est celui que l'assistant
# comprend aussi a la voix, donc les deux chemins parlent la meme langue.
_PALETTE = [
    ("rouge", (255, 0, 0)), ("orange", (255, 100, 0)),
    ("jaune", (255, 255, 0)), ("vert", (0, 255, 0)),
    ("cyan", (0, 255, 255)), ("bleu", (0, 0, 255)),
    ("violet", (140, 0, 255)), ("magenta", (255, 0, 255)),
    ("rose", (255, 105, 180)), ("blanc", (255, 255, 255)),
    ("noir", (0, 0, 0)),
]


class Pupitre(tk.Frame):
    """Le panneau Controle, en widgets."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.occupe = False

        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True)
        self._corps = self.zone.inner

        self._construire()
        self.recharger()

    # --- ossature ---------------------------------------------------------

    def _section(self, titre: str) -> tk.Frame:
        tk.Label(self._corps, text=t.espacer(titre), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))
        cadre = tk.Frame(self._corps, bg=t.SURFACE)
        cadre.pack(fill="x", padx=t.PAD_L)
        return cadre

    def _construire(self) -> None:
        self._section_son()
        self._section_lecture()
        self._section_eclairage()
        self._section_clavier()
        self._section_alimentation()
        self._section_raccourcis()

    # --- eclairage RGB ------------------------------------------------------

    def _section_eclairage(self) -> None:
        """Les modes RGB, decouverts et non codes en dur.

        Rien ici ne connait Gigabyte, Asus ou Corsair : les peripheriques et
        leurs modes sont demandes au materiel au moment de l'affichage. Sur
        une autre machine, la section se remplit avec ce qui s'y trouve.
        """
        cadre = self._section("eclairage rgb")
        self.cadre_rgb = cadre

        self.etat_rgb = tk.Label(
            cadre, text="lecture des peripheriques ...", bg=t.SURFACE,
            fg=t.TEXT_FAINT, font=t.FONT_UI_TINY, anchor="w",
            justify="left", wraplength=620)
        self.etat_rgb.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 4))

        self.modes_rgb = tk.Frame(cadre, bg=t.SURFACE)
        self.modes_rgb.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

    def _charger_rgb(self) -> None:
        def travail():
            from assistant.skills import rgb

            if not rgb.disponible():
                message = ("Pilotage RGB indisponible : OpenRGB n'est pas "
                           "installe. Les logiciels des fabricants n'ont "
                           "aucune ligne de commande ; OpenRGB parle au "
                           "materiel lui-meme et couvre la plupart des "
                           "marques. Il est libre et fonctionne hors ligne.")
                self.window.post("appel",
                                 lambda: self._afficher_rgb([], message))
                return
            trouves, erreur = rgb.peripheriques()
            concurrents = rgb.concurrents_actifs()
            if not erreur and concurrents:
                erreur = (", ".join(concurrents) + " tourne en meme temps : "
                          "deux logiciels sur le meme controleur font "
                          "clignoter l'eclairage au hasard.")
            self.window.post("appel",
                             lambda: self._afficher_rgb(trouves, erreur))

        threading.Thread(target=travail, daemon=True).start()

    def _afficher_rgb(self, peripheriques, message: str) -> None:
        for enfant in self.modes_rgb.winfo_children():
            enfant.destroy()
        self.reglages_rgb = {}

        if not peripheriques:
            self.etat_rgb.configure(text=message or "Aucun peripherique RGB.")
            return

        self.etat_rgb.configure(
            text=f"{len(peripheriques)} peripherique(s)."
                 + (f"  {message}" if message else ""),
            fg=t.AMBER if message else t.TEXT_DIM)

        for peripherique in peripheriques:
            self._bloc_peripherique(peripherique)

    def _bloc_peripherique(self, peripherique) -> None:
        """Un materiel : ses modes, sa couleur, et ses reglages disponibles.

        Ce qui est propose depend de ce que le MODE declare accepter. Un
        curseur de vitesse sur un mode qui n'en a pas serait un bouton mort ;
        le cacher quand il existe priverait l'utilisateur. Les intervalles
        different d'un materiel a l'autre -- la luminosite va de 1 a 10 sur la
        carte graphique et de 0 a 255 sur la carte mere.
        """
        cadre = tk.Frame(self.modes_rgb, bg=t.SURFACE_2)
        cadre.pack(fill="x", pady=(6, 0))

        entete = tk.Frame(cadre, bg=t.SURFACE_2)
        entete.pack(fill="x", padx=t.PAD, pady=(t.PAD, 2))
        tk.Label(entete, text=peripherique.nom, bg=t.SURFACE_2, fg=t.TEXT,
                 font=t.FONT_LABEL, anchor="w").pack(side="left")
        tk.Label(entete, text=f"{peripherique.genre} · {peripherique.nb_leds} LED",
                 bg=t.SURFACE_2, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_TINY).pack(side="right")

        modes = tk.Frame(cadre, bg=t.SURFACE_2)
        modes.pack(fill="x", padx=t.PAD, pady=(0, 4))
        for nom in peripherique.modes:
            _LigneCliquable(
                modes, nom,
                lambda m=nom, p=peripherique: self._appliquer_rgb(p, mode=m),
                active=(nom == peripherique.mode_actif),
            ).pack(side="left", padx=(0, 2))

        # La palette : douze teintes d'un clic, et la roue de Windows pour
        # tout le reste. Se limiter aux presets serait dire "n'importe quelle
        # couleur" en n'en offrant que douze.
        palette = tk.Frame(cadre, bg=t.SURFACE_2)
        palette.pack(fill="x", padx=t.PAD, pady=(0, 4))
        tk.Label(palette, text="couleur", bg=t.SURFACE_2, fg=t.TEXT_FAINT,
                 font=t.FONT_UI_TINY).pack(side="left", padx=(0, 6))
        for nom, (r, v, b) in _PALETTE:
            case = tk.Canvas(palette, width=16, height=16, bg=t.SURFACE_2,
                             highlightthickness=1,
                             highlightbackground=t.BORDER, cursor="hand2")
            case.create_rectangle(0, 0, 16, 16, fill=f"#{r:02x}{v:02x}{b:02x}",
                                  outline="")
            case.pack(side="left", padx=1)
            case.bind("<Button-1>",
                      lambda _e, c=nom, p=peripherique:
                      self._appliquer_rgb(p, couleur=c))
        choix = tk.Label(palette, text="  autre...", bg=t.SURFACE_2,
                         fg=t.ACCENT, font=t.FONT_UI_TINY, cursor="hand2")
        choix.pack(side="left")
        choix.bind("<Button-1>",
                   lambda _e, p=peripherique: self._choisir_couleur(p))

        detail = peripherique.mode(peripherique.mode_actif)
        if detail is None:
            return
        for libelle, plage, cle in (("luminosite", detail.luminosite, "lum"),
                                    ("vitesse", detail.vitesse, "vit")):
            if not plage:
                continue
            bas, haut, valeur = plage
            ligne = tk.Frame(cadre, bg=t.SURFACE_2)
            ligne.pack(fill="x", padx=t.PAD, pady=(0, 2))
            tk.Label(ligne, text=libelle, bg=t.SURFACE_2, fg=t.TEXT_FAINT,
                     font=t.FONT_UI_TINY, width=10, anchor="w").pack(side="left")
            curseur = tk.Scale(
                ligne, from_=bas, to=haut, orient="horizontal", showvalue=True,
                bg=t.SURFACE_2, fg=t.TEXT_DIM, troughcolor=t.BG,
                activebackground=t.ACCENT, highlightthickness=0, bd=0,
                sliderrelief="flat", sliderlength=16, width=8,
                font=t.FONT_UI_TINY, length=200,
            )
            curseur.set(valeur)
            curseur.pack(side="left")
            curseur.bind(
                "<ButtonRelease-1>",
                lambda _e, p=peripherique, c=cle, s=curseur:
                self._appliquer_rgb(p, **{("luminosite" if c == "lum"
                                           else "vitesse"): s.get()}))
        self.reglages_rgb[peripherique.nom] = cadre

    def _choisir_couleur(self, peripherique) -> None:
        from tkinter import colorchooser

        choisi = colorchooser.askcolor(
            title=f"Couleur pour {peripherique.nom}", parent=self)
        if choisi and choisi[1]:
            self._appliquer_rgb(peripherique, couleur=choisi[1].lstrip("#"))

    def _appliquer_rgb(self, peripherique, mode: str = "", couleur: str = "",
                       luminosite=None, vitesse=None) -> None:
        quoi = mode or couleur or "reglage"
        self.etat_rgb.configure(text=f"{peripherique.nom} -> {quoi} ...",
                                fg=t.AMBER)

        def travail():
            from assistant.skills import rgb

            message = rgb.appliquer(peripherique.nom, mode, couleur,
                                    luminosite, vitesse)
            self.window.post("appel", lambda: (
                self.etat_rgb.configure(text=message.replace("\n", "  ")[:190],
                                        fg=t.TEXT_DIM),
                self._charger_rgb(),
            ))

        threading.Thread(target=travail, daemon=True).start()

    # --- son --------------------------------------------------------------

    def _section_son(self) -> None:
        cadre = self._section("son")

        haut = tk.Frame(cadre, bg=t.SURFACE)
        haut.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 2))

        self.etiquette_volume = tk.Label(
            haut, text="Volume", bg=t.SURFACE, fg=t.TEXT,
            font=t.FONT_LABEL, anchor="w")
        self.etiquette_volume.pack(side="left")

        self.bouton_muet = RoundButton(haut, "Couper", self._basculer_muet,
                                       width=88, bg=t.SURFACE_2,
                                       hover_bg=t.BORDER)
        self.bouton_muet.pack(side="right")

        # Le curseur agit en continu, sans validation : c'est le seul reglage
        # qu'on veut regler a l'oreille, en le bougeant.
        self.curseur = tk.Scale(
            cadre, from_=0, to=100, orient="horizontal", showvalue=False,
            command=self._glisser_volume, bg=t.SURFACE, fg=t.TEXT,
            troughcolor=t.BG, activebackground=t.ACCENT,
            highlightthickness=0, bd=0, sliderrelief="flat",
            sliderlength=18, width=10,
        )
        self.curseur.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

        tk.Label(cadre, text=t.espacer("sortie"), bg=t.SURFACE,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L)
        self.sorties = tk.Frame(cadre, bg=t.SURFACE)
        self.sorties.pack(fill="x", padx=t.PAD_L, pady=(2, t.PAD))

    def _glisser_volume(self, valeur) -> None:
        if self.occupe:
            return
        from assistant.skills import control

        niveau = int(float(valeur))
        self.etiquette_volume.configure(text=f"Volume   {niveau} %")
        threading.Thread(target=control.set_volume, args=(niveau,),
                         daemon=True).start()

    def _basculer_muet(self) -> None:
        from assistant.skills import control

        def travail():
            message = control.mute(None)
            self.window.post("appel", lambda: self._apres(message))

        threading.Thread(target=travail, daemon=True).start()

    def _choisir_sortie(self, nom: str) -> None:
        from assistant.skills import control

        def travail():
            message = control.set_audio_output(nom)
            self.window.post("appel", lambda: self._apres(message))

        threading.Thread(target=travail, daemon=True).start()

    # --- lecture ----------------------------------------------------------

    def _section_lecture(self) -> None:
        cadre = self._section("lecture en cours")

        tk.Label(cadre,
                 text="Pilote ce qui joue : Spotify, VLC, YouTube, Netflix, "
                      "le lecteur Windows. Ce sont les touches multimedia du "
                      "clavier, donc toutes les applications repondent.",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=620).pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD, 4))

        rangee = tk.Frame(cadre, bg=t.SURFACE)
        rangee.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))
        for action, symbole, infobulle in MEDIA:
            bouton = RoundButton(
                rangee, symbole, lambda a=action: self._media(a),
                width=72, bg=t.SURFACE_2, hover_bg=t.ACCENT_SOFT,
                font=t.FONT_MONO_BOLD)
            bouton.pack(side="left", padx=(0, t.PAD))
            _infobulle(bouton, infobulle)

        self.etat_media = tk.Label(cadre, text="", bg=t.SURFACE,
                                   fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                                   anchor="w")
        self.etat_media.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

    def _media(self, action: str) -> None:
        from assistant.skills import control

        message = control.media(action)
        self.etat_media.configure(text=message[:120], fg=t.TEXT_DIM)

    # --- clavier ----------------------------------------------------------

    def _section_clavier(self) -> None:
        cadre = self._section("ecrire au clavier")

        tk.Label(cadre,
                 text="Le texte part dans la fenetre qui avait le focus avant "
                      "l'assistant, comme si tu l'avais tape. Utile pour "
                      "dicter dans une application qui ne connait pas la "
                      "dictee.",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=620).pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD, 4))

        rangee = tk.Frame(cadre, bg=t.SURFACE)
        rangee.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

        champ = tk.Frame(rangee, bg=t.SURFACE_2, highlightthickness=1,
                         highlightbackground=t.BORDER)
        champ.pack(side="left", fill="x", expand=True)
        self.saisie = tk.Entry(champ, bg=t.SURFACE_2, fg=t.TEXT,
                               insertbackground=t.ACCENT, relief="flat",
                               font=t.FONT_INPUT)
        self.saisie.pack(fill="x", padx=t.PAD, pady=7)
        self.saisie.bind("<Return>", lambda _e: self._taper())

        RoundButton(rangee, "Taper", self._taper, width=92,
                    bg=t.ACCENT, fg="#06222A",
                    hover_bg="#79b4ff").pack(side="left", padx=(t.PAD, 0))

        self.etat_clavier = tk.Label(cadre, text="", bg=t.SURFACE,
                                     fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                                     anchor="w")
        self.etat_clavier.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))

    def _taper(self) -> None:
        from assistant.skills import control

        texte = self.saisie.get()
        if not texte.strip():
            return
        self.saisie.delete(0, "end")
        self.etat_clavier.configure(text="envoi ...", fg=t.AMBER)

        def travail():
            # Pas de confirmation : l'utilisateur a ecrit le texte lui-meme et
            # le voit devant lui. L'action reste journalisee.
            message = control.taper(texte)
            self.window.post(
                "appel",
                lambda: self.etat_clavier.configure(text=message[:120],
                                                    fg=t.TEXT_DIM))

        threading.Thread(target=travail, daemon=True).start()

    # --- alimentation ------------------------------------------------------

    def _section_alimentation(self) -> None:
        cadre = self._section("alimentation")

        self.etat_profil = tk.Label(cadre, text="lecture ...", bg=t.SURFACE,
                                    fg=t.TEXT_DIM, font=t.FONT_UI_TINY,
                                    anchor="w")
        self.etat_profil.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 4))

        rangee = tk.Frame(cadre, bg=t.SURFACE)
        rangee.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))
        for cle, libelle in PROFILS:
            RoundButton(rangee, libelle,
                        lambda c=cle: self._profil(c), width=120,
                        bg=t.SURFACE_2, hover_bg=t.ACCENT_SOFT).pack(
                side="left", padx=(0, t.PAD))

    def _profil(self, cle: str) -> None:
        from assistant.skills import control

        def travail():
            message = control.power_plan(cle)
            self.window.post("appel", lambda: self._apres(message))

        threading.Thread(target=travail, daemon=True).start()

    # --- raccourcis --------------------------------------------------------

    def _section_raccourcis(self) -> None:
        cadre = self._section("ouvrir dans windows")

        tk.Label(cadre,
                 text="Chaque ligne ouvre l'endroit exact du systeme, pas la "
                      "page d'accueil des parametres.",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=620).pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD, 4))

        grille = tk.Frame(cadre, bg=t.SURFACE)
        grille.pack(fill="x", padx=t.PAD_L, pady=(0, t.PAD))
        for index, (cle, libelle) in enumerate(RACCOURCIS):
            _LigneCliquable(grille, libelle,
                            lambda c=cle: self._ouvrir(c)).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=2, pady=1)
        grille.columnconfigure(0, weight=1, uniform="raccourci")
        grille.columnconfigure(1, weight=1, uniform="raccourci")

    def _ouvrir(self, cle: str) -> None:
        from assistant.skills import control

        threading.Thread(target=control.ouvrir_reglage, args=(cle,),
                         daemon=True).start()

    # --- rafraichissement ---------------------------------------------------

    def _apres(self, message: str) -> None:
        """Message d'une action, puis relecture de l'etat reel."""
        self.etiquette_volume.configure(text=message[:60])
        self.recharger()

    def recharger(self) -> None:
        from assistant.skills import control

        def travail():
            try:
                niveau = control.volume()
                coupe = bool(control._endpoint().GetMute())
            except Exception:  # noqa: BLE001
                niveau, coupe = -1, False
            try:
                from pycaw.utils import AudioUtilities

                control._ensure_com()
                actuelle = AudioUtilities.GetSpeakers().FriendlyName
                appareils = [a.FriendlyName for a in control._output_devices()]
            except Exception:  # noqa: BLE001
                actuelle, appareils = "", []
            profil = control.power_plan()

            self.window.post("appel", lambda: self._afficher(
                niveau, coupe, actuelle, appareils, profil))

        threading.Thread(target=travail, daemon=True).start()
        # L'eclairage a son propre fil : interroger le controleur RGB peut
        # prendre plusieurs secondes, et le volume ne doit pas attendre.
        self._charger_rgb()

    def _afficher(self, niveau, coupe, actuelle, appareils, profil) -> None:
        self.occupe = True       # le .set() ci-dessous ne doit rien declencher
        try:
            if niveau >= 0:
                self.curseur.set(niveau)
                self.etiquette_volume.configure(
                    text=f"Volume   {niveau} %" + ("   coupe" if coupe else ""))
            else:
                self.etiquette_volume.configure(text="Volume illisible")
        finally:
            self.occupe = False

        self.bouton_muet.set_text("Retablir" if coupe else "Couper")

        for enfant in self.sorties.winfo_children():
            enfant.destroy()
        for nom in appareils:
            active = nom == actuelle
            _LigneCliquable(self.sorties, nom,
                            lambda n=nom: self._choisir_sortie(n),
                            active=active).pack(fill="x", pady=1)

        self.etat_profil.configure(text=profil.strip()[:120] or "profil inconnu")


class _LigneCliquable(tk.Frame):
    """Une ligne de menu qui reagit au survol et se clique.

    Tk n'a pas d'element de liste : sans ca, un Label reste inerte et rien
    n'indique qu'il mene quelque part.
    """

    def __init__(self, parent, texte: str, command, active: bool = False):
        fond = t.ACCENT_SOFT if active else t.SURFACE
        super().__init__(parent, bg=fond, cursor="hand2")
        self._fond = fond
        self._actif = active

        marque = "-> " if active else "   "
        self._texte = tk.Label(self, text=marque + texte, bg=fond,
                               fg=t.ACCENT if active else t.TEXT_DIM,
                               font=t.FONT_UI_TINY, anchor="w")
        self._texte.pack(fill="x", padx=t.PAD, pady=4)

        for widget in (self, self._texte):
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", lambda _e: self._survol(True))
            widget.bind("<Leave>", lambda _e: self._survol(False))

    def _survol(self, dedans: bool) -> None:
        if self._actif:
            return
        couleur = t.SURFACE_2 if dedans else self._fond
        self.configure(bg=couleur)
        self._texte.configure(bg=couleur,
                              fg=t.TEXT if dedans else t.TEXT_DIM)


def _infobulle(widget, texte: str) -> None:
    """Petite bulle au survol : les boutons media n'ont que des symboles."""
    bulle = {"fenetre": None}

    def montrer(_e=None):
        if bulle["fenetre"] is not None:
            return
        fenetre = tk.Toplevel(widget)
        fenetre.wm_overrideredirect(True)
        fenetre.configure(bg=t.BORDER)
        tk.Label(fenetre, text=texte, bg=t.SURFACE_2, fg=t.TEXT,
                 font=t.FONT_UI_TINY, padx=8, pady=4).pack(padx=1, pady=1)
        fenetre.wm_geometry(
            f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + 40}")
        bulle["fenetre"] = fenetre

    def cacher(_e=None):
        if bulle["fenetre"] is not None:
            bulle["fenetre"].destroy()
            bulle["fenetre"] = None

    widget.bind("<Enter>", montrer, add="+")
    widget.bind("<Leave>", cacher, add="+")
