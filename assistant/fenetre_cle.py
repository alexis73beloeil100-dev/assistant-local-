"""La fenetre "Clé d'accès développeur".

Pour tout le monde : coller sa cle, la faire verifier.

Pour le proprietaire seulement, selon ce qui se trouve sur CE PC :
  - aucune cle publique dans le code et aucune cle maitre ici : le bouton
    qui cree la cle maitre (une seule fois dans la vie du projet) ;
  - la cle maitre presente ici : de quoi s'ouvrir l'acces sur ce PC, et
    fabriquer une cle pour quelqu'un d'autre.
Sans la cle maitre, ces sections n'apparaissent pas.
"""
from __future__ import annotations

import tkinter as tk

from assistant import licence
from assistant import theme as t
from assistant.widgets import RoundButton


def ouvrir(fenetre, apres_validation) -> None:
    dialogue = tk.Toplevel(fenetre)
    dialogue.title("Clé d'accès développeur")
    dialogue.configure(bg=t.BG)
    dialogue.transient(fenetre)
    dialogue.resizable(False, False)

    cadre = tk.Frame(dialogue, bg=t.BG)
    cadre.pack(fill="both", expand=True, padx=t.PAD_XL, pady=t.PAD_L)

    def titre(texte: str) -> None:
        tk.Label(cadre, text=t.espacer(texte), bg=t.BG, fg=t.ACCENT_DEEP,
                 font=t.FONT_HUD, anchor="w").pack(fill="x", pady=(t.PAD, 4))

    def ligne(texte: str, couleur=t.TEXT_DIM) -> tk.Label:
        etiquette = tk.Label(cadre, text=texte, bg=t.BG, fg=couleur,
                             font=t.FONT_UI_SMALL, anchor="w", justify="left",
                             wraplength=520)
        etiquette.pack(fill="x")
        return etiquette

    def champ(largeur: int = 64) -> tk.Entry:
        entree = tk.Entry(cadre, bg=t.SURFACE_2, fg=t.TEXT, width=largeur,
                          insertbackground=t.ACCENT, relief="flat",
                          font=t.FONT_MONO)
        entree.pack(fill="x", ipady=6, pady=(2, 4))
        return entree

    titre("mode dev")
    ligne("Le mode Dev et l'atelier Unreal demandent une clé d'accès. "
          "Colle la tienne ci-dessous.")
    pc = licence.identifiant_pc() or "indisponible"
    ligne(f"Identifiant de ce PC : {pc}", t.TEXT_FAINT)

    saisie = champ()
    verdict = ligne("")

    def valider() -> None:
        valide, raison = licence.enregistrer_cle(saisie.get())
        verdict.configure(text=("Acceptée : " if valide else "Refusée : ") + raison,
                          fg=t.GREEN if valide else t.RED)
        if valide:
            dialogue.after(700, lambda: (dialogue.destroy(), apres_validation()))

    RoundButton(cadre, "Valider", valider, width=118, bg=t.ACCENT,
                fg="#06222A", hover_bg="#7BE3F2").pack(anchor="e", pady=(4, 0))

    graine = licence.graine_maitre()

    if not licence.CLE_PUBLIQUE and graine is None:
        titre("propriétaire : première fois")
        ligne("Crée la clé maître une seule fois, sur TON PC. Elle sera "
              "écrite dans tes Documents, jamais sur GitHub. Envoie ensuite "
              "la clé PUBLIQUE affichée : elle sera inscrite dans "
              "l'application.")
        resultat = champ()

        def creer() -> None:
            try:
                publique = licence.creer_cle_maitre()
            except OSError as exc:
                resultat.delete(0, "end")
                resultat.insert(0, f"Échec : {exc}")
                return
            resultat.delete(0, "end")
            resultat.insert(0, publique)
            dialogue.clipboard_clear()
            dialogue.clipboard_append(publique)
            ligne(f"Clé maître écrite dans {licence.fichier_maitre()}. "
                  "Fais-en une copie sur une clé USB. La clé publique est "
                  "copiée dans le presse-papier.", t.GREEN)

        RoundButton(cadre, "Créer la clé maître", creer, width=180).pack(
            anchor="e", pady=(4, 0))

    if graine is not None and licence.CLE_PUBLIQUE:
        titre("propriétaire : délivrer une clé")
        ligne("Ta clé maître est sur ce PC. Nom, identifiant du PC (vide = "
              "tout PC), date de fin AAAA-MM-JJ (vide = sans fin) :",
              t.TEXT_FAINT)
        nom, pc_cible, fin = champ(30), champ(30), champ(30)
        pc_cible.insert(0, licence.identifiant_pc())
        sortie = champ()

        def delivrer() -> None:
            try:
                cle = licence.fabriquer_cle(graine, nom.get().strip() or "?",
                                            pc_cible.get().strip(),
                                            fin.get().strip())
            except ValueError:
                sortie.delete(0, "end")
                sortie.insert(0, "Date invalide : AAAA-MM-JJ")
                return
            sortie.delete(0, "end")
            sortie.insert(0, cle)
            dialogue.clipboard_clear()
            dialogue.clipboard_append(cle)

        RoundButton(cadre, "Fabriquer", delivrer, width=118).pack(
            anchor="e", pady=(4, 0))

    dialogue.bind("<Escape>", lambda _e: dialogue.destroy())
    dialogue.grab_set()
    saisie.focus_set()
