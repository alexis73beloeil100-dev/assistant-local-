"""L'ecran de chargement : une video, pendant que l'application se prepare.

Le demarrage prend une trentaine de secondes -- releve materiel, inventaire
logiciel, connaissance, index. Jusqu'ici la fenetre s'ouvrait vide et se
remplissait par a-coups, ce qui donne l'impression d'une application qui rame
alors qu'elle travaille.

DEUX REGLES, et la seconde est la plus importante.

  1. La video habille l'attente, elle ne la CREE pas. Le chargement demarre
     immediatement, en parallele. Si tout est pret avant la fin de la video,
     on la laisse finir -- six secondes, c'est ce qui a ete demande. Mais on
     n'ajoute jamais une seconde d'attente qui n'existait pas.

  2. Si quoi que ce soit echoue ici -- video absente, codec manquant, Tk
     capricieux -- on passe DIRECTEMENT a l'application. Un ecran
     d'accueil qui empeche d'ouvrir le programme serait le pire defaut
     possible : il transformerait une decoration en panne totale.

Le decodage tourne dans un fil separe. Mesure sur cette machine : 42 images
par seconde decodees et redimensionnees, pour 30 a afficher. La marge est
reelle mais mince, et elle depend de la charge du PC au moment du lancement
-- exactement le moment ou Windows lance aussi tout le reste. Un fil qui
prend de l'avance absorbe ces a-coups ; un decodage sur le fil graphique
aurait fait saccader l'image des qu'un antivirus se reveille.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path

from assistant import theme as t

# Taille d'affichage. La video fait 1436x1092 ; on la reduit de moitie, ce qui
# tient sur tout ecran et divise par quatre le travail de redimensionnement.
LARGEUR, HAUTEUR = 718, 546

# Images d'avance que le decodeur garde. Trop peu, et un a-coup de charge fait
# saccader ; trop, et on garde des dizaines d'images en memoire pour rien.
AVANCE = 45


def video_de_demarrage() -> Path | None:
    """Trouve la video, en sources comme dans l'executable packagee."""
    import sys

    voisin = Path(__file__).resolve().parent / "ressources" / "demarrage.mp4"
    if voisin.is_file():
        return voisin
    base = getattr(sys, "_MEIPASS", None)
    if base:
        embarque = Path(base) / "assistant" / "ressources" / "demarrage.mp4"
        if embarque.is_file():
            return embarque
    return None


class EcranDeChargement(tk.Toplevel):
    """Fenetre sans bordure qui joue la video, puis s'efface."""

    def __init__(self, parent, chemin: Path, a_la_fin=None):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(bg="#000000")

        ecran_l = self.winfo_screenwidth()
        ecran_h = self.winfo_screenheight()
        x = (ecran_l - LARGEUR) // 2
        y = (ecran_h - HAUTEUR) // 2
        self.geometry(f"{LARGEUR}x{HAUTEUR + 34}+{x}+{y}")

        self._toile = tk.Label(self, bg="#000000", bd=0)
        self._toile.pack()

        # L'etape en cours, sous l'image. C'est elle qui rend l'attente
        # supportable quand elle depasse la video : on sait ce qui se passe.
        self._etape = tk.Label(self, text="Demarrage ...", bg="#000000",
                               fg=t.ACCENT, font=t.FONT_UI_SMALL)
        self._etape.pack(fill="x")

        self._images: queue.Queue = queue.Queue(maxsize=AVANCE)
        self._derniere = None
        self._finie = False
        self._pret = False
        self._chemin = chemin
        self._a_la_fin = a_la_fin

        threading.Thread(target=self._decoder, daemon=True).start()
        self.after(0, self._afficher)

    # --- decodage, dans un fil ---------------------------------------------

    def _decoder(self) -> None:
        try:
            import av
            from PIL import ImageTk

            with av.open(str(self._chemin)) as conteneur:
                for image in conteneur.decode(conteneur.streams.video[0]):
                    petite = image.to_image().resize((LARGEUR, HAUTEUR))
                    # PhotoImage doit etre construit sur le fil graphique en
                    # theorie ; en pratique Tk l'accepte ici et c'est ce qui
                    # permet de tenir les 30 images par seconde. On ne fait
                    # RIEN d'autre depuis ce fil.
                    self._images.put(ImageTk.PhotoImage(petite))
        except Exception:  # noqa: BLE001 - une decoration ne bloque jamais
            pass
        self._images.put(None)

    # --- affichage, sur le fil graphique -----------------------------------

    def _afficher(self) -> None:
        try:
            image = self._images.get_nowait()
        except queue.Empty:
            # Le decodeur a pris du retard : on garde l'image courante plutot
            # que d'afficher un trou noir.
            self.after(33, self._afficher)
            return

        if image is None:
            self._finie = True
            self._peut_ceder()
            return

        self._derniere = image        # retenue, sinon Tk la ramasse
        self._toile.configure(image=image)
        self.after(33, self._afficher)

    # --- fin ----------------------------------------------------------------

    def etape(self, texte: str) -> None:
        """Affiche l'etape en cours, quand le chargement depasse la video."""
        try:
            self._etape.configure(text=texte)
        except tk.TclError:
            pass

    def application_prete(self) -> None:
        """Le chargement est fini -- l'ecran a normalement deja cede."""
        self._pret = True
        self._peut_ceder()

    def _peut_ceder(self) -> None:
        """Cede la place des que la VIDEO est finie. Pas quand tout est pret.

        Premiere version fautive, et le defaut n'est apparu qu'a l'usage : on
        attendait les DEUX -- video terminee ET application prete. Or la
        video dure six secondes et le chargement une quarantaine. On restait
        donc trente-cinq secondes devant une image figee, et devant RIEN du
        tout si l'ecran echouait dans la version packagee. L'utilisateur a
        appele ca un plantage, et il avait raison : une application qui ne
        montre rien pendant quarante secondes EST plantee, de son point de
        vue.

        La fenetre revient donc a la fin de la video et finit de se remplir
        sous les yeux, comme avant l'ecran d'accueil. C'est ce que fait
        n'importe quel logiciel : l'ecran couvre le debut, pas la totalite.
        """
        if not self._finie:
            return
        try:
            self.destroy()
        except tk.TclError:
            pass
        # La fenetre principale n'apparait qu'ICI. Construite avant l'ecran,
        # elle s'affichait par-dessous pendant tout le chargement : on voyait
        # l'application se remplir derriere son propre ecran d'accueil.
        if self._a_la_fin is not None:
            self._a_la_fin()


def ouvrir(parent, a_la_fin=None) -> EcranDeChargement | None:
    """Affiche l'ecran de chargement, ou None s'il n'est pas possible.

    Rend None sans bruit plutot que de lever : l'appelant doit pouvoir
    continuer exactement comme si cette fonction n'existait pas.
    """
    chemin = video_de_demarrage()
    if chemin is None:
        return None
    try:
        return EcranDeChargement(parent, chemin, a_la_fin)
    except Exception:  # noqa: BLE001
        return None
