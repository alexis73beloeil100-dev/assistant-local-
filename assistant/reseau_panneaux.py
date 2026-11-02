"""Le panneau qui touche au reseau : la mise a jour.

C'est le seul endroit de l'application d'ou quelque chose sort vers
Internet, et il ne fait rien a l'ouverture : verifier et telecharger partent
chacun d'un clic.
"""
from __future__ import annotations

import threading
import tkinter as tk

from assistant import theme as t
from assistant.widgets import RoundButton, ScrollArea


class MiseAJour(tk.Frame):
    """Le panneau Mise a jour : verifier, puis installer, chacun au clic."""

    def __init__(self, parent, window):
        super().__init__(parent, bg=t.BG)
        self.window = window
        self.occupe = False
        self.dispo = None

        self.zone = ScrollArea(self, bg=t.BG)
        self.zone.pack(fill="both", expand=True)
        corps = self.zone.inner

        tk.Label(corps, text=t.espacer("mise a jour"), bg=t.BG,
                 fg=t.ACCENT_DEEP, font=t.FONT_HUD, anchor="w").pack(
            fill="x", padx=t.PAD_L, pady=(t.PAD_L, 4))

        cadre = tk.Frame(corps, bg=t.SURFACE)
        cadre.pack(fill="x", padx=t.PAD_L)
        rangee = tk.Frame(cadre, bg=t.SURFACE)
        rangee.pack(fill="x", padx=t.PAD_L, pady=t.PAD)

        gauche = tk.Frame(rangee, bg=t.SURFACE)
        gauche.pack(side="left", fill="x", expand=True)
        tk.Label(gauche, text="Vérifier les mises à jour", bg=t.SURFACE,
                 fg=t.TEXT, font=t.FONT_LABEL, anchor="w").pack(fill="x")
        tk.Label(gauche,
                 text="Demande a GitHub si une version plus recente existe. "
                      "Rien ne part avant ce clic, et rien de personnel "
                      "n'est envoye.",
                 bg=t.SURFACE, fg=t.TEXT_FAINT, font=t.FONT_UI_TINY,
                 anchor="w", justify="left", wraplength=520).pack(fill="x")

        self.bouton_installer = RoundButton(
            rangee, "Installer", self._installer, width=104,
            bg=t.ACCENT, fg="#0b1220", hover_bg="#79b4ff")
        self.bouton = RoundButton(rangee, "Vérifier", self._verifier,
                                  width=104, bg=t.ACCENT, fg="#0b1220",
                                  hover_bg="#79b4ff")
        self.bouton.pack(side="right", padx=(t.PAD, 0))

        self.resultat = tk.Label(
            corps, text="", bg=t.BG, fg=t.TEXT_DIM, font=t.FONT_MONO,
            anchor="w", justify="left", wraplength=640)
        self.resultat.pack(fill="x", padx=t.PAD_L, pady=(t.PAD_L, t.PAD))
        self.recharger()

    def _afficher(self, texte: str, couleur) -> None:
        self.resultat.configure(text=texte, fg=couleur)

    def _verifier(self) -> None:
        if self.occupe:
            return
        self.occupe = True
        self.bouton_installer.pack_forget()
        self._afficher("Interrogation de GitHub ...", t.AMBER)

        def fil():
            from assistant import mise_a_jour as maj

            try:
                dispo = maj.verifier()
                texte = maj.resume(dispo)
                if dispo is not None and dispo.notes:
                    texte += "\n\n" + dispo.notes[:1500]
                couleur = t.TEXT_DIM
            except maj.Echec as exc:
                dispo, texte, couleur = None, f"Verification impossible : {exc}", t.AMBER

            def fin():
                self.dispo = dispo
                self.occupe = False
                self._afficher(texte, couleur)
                if dispo is not None:
                    self.bouton_installer.pack(side="right", padx=(t.PAD, 0))

            self.window.post("appel", fin)

        threading.Thread(target=fil, daemon=True).start()

    def _installer(self) -> None:
        if self.occupe or self.dispo is None:
            return
        self.occupe = True
        dispo = self.dispo
        self._afficher("Telechargement ...", t.AMBER)

        def avance(recu: int, total: int) -> None:
            pourcent = 100 * recu / total if total else 0
            self.window.post("appel", lambda: self._afficher(
                f"Telechargement : {recu / 1e6:.0f} / {total / 1e6:.0f} Mo "
                f"({pourcent:.0f} %)", t.AMBER))

        def fil():
            from assistant import mise_a_jour as maj

            try:
                chemin = maj.telecharger(dispo, progression=avance)
            except maj.Echec as exc:
                message = f"Echec : {exc}"
                self.window.post("appel", lambda: (
                    self._afficher(message, t.AMBER),
                    setattr(self, "occupe", False)))
                return

            # Encore dans le fil de travail : la fenetre d'accord bloque
            # l'appelant en attendant la reponse, et l'appeler depuis le fil
            # de l'interface la figerait cinq minutes.
            try:
                maj.lancer(chemin, dispo)
            except (maj.Echec, OSError) as exc:
                message = f"Echec : {exc}"
                self.window.post("appel", lambda: (
                    self._afficher(message, t.AMBER),
                    setattr(self, "occupe", False)))
                return

            def fermer():
                self._afficher("Installation lancee, l'application se ferme.",
                               t.TEXT_DIM)
                # L'installateur remplace nos fichiers : on lui laisse la place.
                self.window.after(1500, self.window._fermer_proprement)

            self.window.post("appel", fermer)

        threading.Thread(target=fil, daemon=True).start()

    def recharger(self) -> None:
        if self.occupe:
            return
        # Ouvrir le panneau ne contacte personne.
        from assistant import panels

        self.dispo = None
        self.bouton_installer.pack_forget()
        self._afficher(panels.content("miseajour", force=True), t.TEXT_DIM)
