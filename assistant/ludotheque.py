"""Ludotheque : la liste des jeux, avec de quoi agir dessus.

Le panneau precedent listait les jeux en texte. On y lisait ce qui etait
installe sans pouvoir rien en faire -- il fallait retourner dans la
conversation et dicter une phrase pour en lancer un.

Ce que cette page sert vraiment a faire, dans l'ordre :

  1. voir ce que chaque jeu prend comme place, et le total ;
  2. preparer la machine avant de jouer -- c'est le bouton Booster ;
  3. faire le menage quand le disque est plein.

La desinstallation passe TOUJOURS par le launcher. Effacer les fichiers
nous-memes laisserait Steam ou Epic persuades que le jeu est installe, et la
reinstallation echouerait de facon incomprehensible.
"""
from __future__ import annotations

import threading
import tkinter as tk

from assistant import icons, theme as t
from assistant.util import human_size
from assistant.widgets import RoundButton, ScrollArea

# Couleur par launcher : reconnaitre d'ou vient un jeu d'un coup d'oeil.
COULEURS = {
    "steam": t.ACCENT,
    "epic": t.TEXT,
    "ubisoft": t.GOLD,
    "ea": t.RED,
    "riot": t.GREEN,
}


class Ludotheque(tk.Frame):
    """La liste des jeux installes, cochable et actionnable."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.cases: dict[str, tk.BooleanVar] = {}
        self.lignes: dict[str, tk.Label] = {}
        self.jeux: list = []
        self.occupe = False

        self._entete()
        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True, padx=t.PAD_XL,
                       pady=(0, t.PAD_L))
        self.recharger()

    # --- ossature ---------------------------------------------------------

    def _entete(self) -> None:
        haut = tk.Frame(self, bg=t.BG)
        haut.pack(fill="x", padx=t.PAD_XL, pady=(t.PAD_L, t.PAD))

        self.resume = tk.Label(haut, text="Lecture des jeux ...", bg=t.BG,
                               fg=t.TEXT_DIM, font=t.FONT_UI_SMALL,
                               anchor="w")
        self.resume.pack(side="left")

        self.selection = tk.Label(haut, text="", bg=t.BG, fg=t.ACCENT,
                                  font=t.FONT_UI_SMALL, anchor="e")
        self.selection.pack(side="right")

        barre = tk.Frame(self, bg=t.BG)
        barre.pack(fill="x", padx=t.PAD_XL, pady=(0, t.PAD))

        RoundButton(barre, "Tout cocher", self._tout_cocher, width=110,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(side="left")
        RoundButton(barre, "Tout decocher", self._tout_decocher, width=118,
                    bg=t.SURFACE_2, hover_bg=t.BORDER).pack(
            side="left", padx=(t.PAD, 0))
        RoundButton(barre, "Desinstaller la selection",
                    self._desinstaller_selection, width=196,
                    bg=t.SURFACE_2, hover_bg=t.RED).pack(
            side="right")

        tk.Label(self,
                 text="Booster prepare la machine pour ce jeu : profil "
                      "performance, fermeture des programmes gourmands, puis "
                      "lancement. La desinstallation passe par le launcher, "
                      "jamais par une suppression de fichiers.",
                 bg=t.BG, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=740).pack(
            fill="x", padx=t.PAD_XL, pady=(0, t.PAD))

    # --- contenu ----------------------------------------------------------

    def recharger(self) -> None:
        for enfant in self.zone.inner.winfo_children():
            enfant.destroy()
        self.cases.clear()
        self.lignes.clear()

        def travail():
            from assistant.skills import games

            trouves = games.all_games()
            self.window.post("appel", lambda: self._afficher(trouves))

        threading.Thread(target=travail, daemon=True).start()

    def _afficher(self, jeux: list) -> None:
        self.jeux = jeux
        if not jeux:
            self.resume.configure(
                text="Aucun jeu detecte. Launchers reconnus : Steam, Epic, "
                     "Ubisoft, EA, Riot.")
            return

        total = sum(j.size_bytes for j in jeux)
        connus = [j for j in jeux if j.size_bytes]
        self.resume.configure(
            text=f"{len(jeux)} jeux  —  {human_size(total)} au total"
                 + (f"  ({len(jeux) - len(connus)} de taille inconnue)"
                    if len(connus) != len(jeux) else ""))

        # Du plus gros au plus petit : c'est l'ordre dans lequel on cherche
        # quoi supprimer quand le disque est plein.
        for jeu in sorted(jeux, key=lambda j: j.size_bytes, reverse=True):
            self._ligne(jeu)

        self._compter()

    def _ligne(self, jeu) -> None:
        cadre = tk.Frame(self.zone.inner, bg=t.SURFACE)
        cadre.pack(fill="x", pady=2)

        haut = tk.Frame(cadre, bg=t.SURFACE)
        haut.pack(fill="x", padx=t.PAD_L, pady=(t.PAD, 2))

        variable = tk.BooleanVar(value=False)
        self.cases[jeu.name] = variable
        tk.Checkbutton(
            haut, variable=variable, command=self._compter,
            bg=t.SURFACE, activebackground=t.SURFACE, selectcolor=t.SURFACE_2,
            highlightthickness=0, bd=0, cursor="hand2",
        ).pack(side="left")

        # La manette, dessinee aux couleurs du launcher.
        toile = tk.Canvas(haut, width=26, height=22, bg=t.SURFACE,
                          highlightthickness=0, bd=0)
        toile.pack(side="left", padx=(2, 8))
        icons.dessiner(toile, "manette", 1, 0, 21,
                       COULEURS.get(jeu.launcher, t.TEXT_DIM))

        tk.Label(haut, text=jeu.name, bg=t.SURFACE, fg=t.TEXT,
                 font=t.FONT_LABEL, anchor="w").pack(side="left")

        taille = human_size(jeu.size_bytes) if jeu.size_bytes else "—"
        tk.Label(haut, text=taille, bg=t.SURFACE, fg=t.ACCENT,
                 font=t.FONT_MONO_BOLD).pack(side="right")
        tk.Label(haut, text=jeu.launcher.upper(), bg=t.SURFACE,
                 fg=COULEURS.get(jeu.launcher, t.TEXT_FAINT),
                 font=t.FONT_UI_TINY).pack(side="right", padx=(0, t.PAD_L))

        boutons = tk.Frame(cadre, bg=t.SURFACE)
        boutons.pack(fill="x", padx=(t.PAD_L + 34, t.PAD_L), pady=(0, 2))

        RoundButton(boutons, "Booster", lambda j=jeu: self._booster(j),
                    width=96, bg=t.ACCENT_SOFT, fg=t.ACCENT,
                    hover_bg=t.BORDER).pack(side="left")
        RoundButton(boutons, "Lancer", lambda j=jeu: self._lancer(j),
                    width=88, bg=t.SURFACE_2,
                    hover_bg=t.BORDER).pack(side="left", padx=(t.PAD, 0))
        RoundButton(boutons, "Dossier", lambda j=jeu: self._dossier(j),
                    width=88, bg=t.SURFACE_2,
                    hover_bg=t.BORDER).pack(side="left", padx=(t.PAD, 0))
        RoundButton(boutons, "Desinstaller",
                    lambda j=jeu: self._desinstaller(j), width=116,
                    bg=t.SURFACE_2, hover_bg=t.RED).pack(
            side="left", padx=(t.PAD, 0))

        message = tk.Label(cadre, text=jeu.install_dir or "", bg=t.SURFACE,
                           fg=t.TEXT_FAINT, font=t.FONT_UI_TINY, anchor="w")
        message.pack(fill="x", padx=(t.PAD_L + 34, t.PAD_L), pady=(0, t.PAD))
        self.lignes[jeu.name] = message

    # --- selection --------------------------------------------------------

    def _compter(self) -> None:
        choisis = [j for j in self.jeux if self.cases.get(j.name)
                   and self.cases[j.name].get()]
        if not choisis:
            self.selection.configure(text="")
            return
        poids = sum(j.size_bytes for j in choisis)
        self.selection.configure(
            text=f"{len(choisis)} coche(s)  —  {human_size(poids)} recuperables")

    def _tout_cocher(self) -> None:
        for variable in self.cases.values():
            variable.set(True)
        self._compter()

    def _tout_decocher(self) -> None:
        for variable in self.cases.values():
            variable.set(False)
        self._compter()

    # --- actions ----------------------------------------------------------

    def _dire(self, jeu, texte: str, couleur: str = t.TEXT_DIM) -> None:
        etiquette = self.lignes.get(jeu.name)
        if etiquette is not None:
            etiquette.configure(text=texte[:150], fg=couleur)

    def _booster(self, jeu) -> None:
        """Prepare la machine puis lance : c'est le mode jeu, cible."""
        if self.occupe:
            return
        self.occupe = True
        self._dire(jeu, "preparation de la machine ...", t.AMBER)

        def travail():
            from assistant.skills import gamemode

            # Le clic sur Booster vaut accord pour fermer les gourmands :
            # c'est exactement ce que le bouton annonce.
            rapport = gamemode.activer(jeu.name, ask=lambda _t: True)
            resume = " | ".join(l.strip() for l in rapport.splitlines()
                                if l.strip())[:150]

            def fini():
                self._dire(jeu, resume, t.GREEN)
                self.occupe = False

            self.window.post("appel", fini)

        threading.Thread(target=travail, daemon=True).start()

    def _lancer(self, jeu) -> None:
        def travail():
            from assistant.skills import games

            ok, message = games.launch(jeu.name)
            self.window.post(
                "appel",
                lambda: self._dire(jeu, message, t.GREEN if ok else t.RED))

        threading.Thread(target=travail, daemon=True).start()

    def _dossier(self, jeu) -> None:
        from assistant.skills import files

        if not jeu.install_dir:
            self._dire(jeu, "Dossier d'installation inconnu.", t.AMBER)
            return
        threading.Thread(target=files.reveal, args=(jeu.install_dir,),
                         daemon=True).start()

    def _desinstaller(self, jeu) -> None:
        def travail():
            from assistant.skills import games

            # Ici on demande VRAIMENT confirmation : contrairement a une
            # frappe au clavier, on parle de dizaines de Go a retelecharger.
            message = games.desinstaller(jeu.name)
            self.window.post("appel", lambda: self._dire(jeu, message, t.AMBER))

        threading.Thread(target=travail, daemon=True).start()

    def _desinstaller_selection(self) -> None:
        choisis = [j for j in self.jeux
                   if self.cases.get(j.name) and self.cases[j.name].get()]
        if not choisis:
            self.resume.configure(text="Coche d'abord les jeux a desinstaller.")
            return

        def travail():
            from assistant.skills import games

            for jeu in choisis:
                message = games.desinstaller(jeu.name)
                self.window.post(
                    "appel",
                    lambda j=jeu, m=message: self._dire(j, m, t.AMBER))

        threading.Thread(target=travail, daemon=True).start()
