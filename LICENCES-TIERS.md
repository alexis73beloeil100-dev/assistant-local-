# Licences des composants tiers

L'Assistant local est sous [licence MIT](LICENSE). Ce fichier concerne ce qui
est **redistribué avec lui** dans l'installateur, et dont les licences
s'appliquent indépendamment.

Chaque licence ci-dessous a été relevée dans les métadonnées du paquet
installé, pas recopiée de mémoire. Pour la régénérer après une mise à jour
des dépendances :

```
.venv\Scripts\python.exe outils\licences_tierces.py
```

---

## openrgb-python — GPLv3, retiré le 23/08/2026

`openrgb-python` était le client Python qui parlait au serveur OpenRGB. Il est
sous **GPLv3**, et `assistant/skills/rgb.py` l'**importait**. Importer, c'est
lier : le binaire distribué devait se transmettre sous GPLv3, code source
compris.

**Il n'est plus utilisé.** `assistant/skills/openrgb_protocole.py` parle
directement au serveur, par son protocole binaire sur TCP. Ce fichier est
écrit pour ce projet ; il n'emprunte aucune ligne à la bibliothèque, dont il
reproduit seulement le dialogue réseau — ce qu'aucune licence ne couvre.

Ce que cela change :

- le programme distribué est de nouveau sous **MIT** ;
- l'archive `assistant-local-source.zip` n'est plus produite ni livrée, et
  `outils/source_pour_gpl.py` a été supprimé ;
- la page de licence de l'installateur annonce le MIT.

Trois tests gardent cet état, parce que la rechute serait muette :
`test_aucun_module_gpl_n_est_importe` interdit tout `import openrgb`,
`test_le_source_n_est_plus_joint_au_binaire` vérifie que l'archive ne
réapparaît pas, et `test_la_licence_affichee_annonce_la_bonne_licence` vérifie
que la page dit la vérité. Un `from openrgb import ...` ajouté pour dépanner
fonctionnerait parfaitement — la bibliothèque reste installée dans le `.venv`
— et ramènerait l'obligation sans que rien ne le signale.

La vérification qui compte n'était pas la relecture du code : le nouveau
client a été comparé au SDK champ par champ sur le matériel réel — 3
périphériques, 18 modes, aucun écart — puis essayé pour de vrai sur la carte
mère, celle qui avait fait échouer une première tentative.

---

## OpenRGB — GPLv2, et il n'est plus distribué

**Depuis le 23/08/2026, l'application ne contient plus OpenRGB.** Ni le dépôt
ni le paquet ne le transportent : qui veut piloter son éclairage l'installe
lui-même depuis <https://openrgb.org>, ou pose sa version portable dans
`outils/OpenRGB/`, où l'assistant va la chercher.

Il n'y a donc plus aucune obligation de redistribution à tenir de ce côté —
ni texte de licence à joindre, ni source à rendre accessible. Deux tests le
gardent, un par frontière : `test_openrgb_n_est_pas_redistribue` surveille le
paquet, `test_le_depot_ne_suit_aucun_fichier_openrgb` surveille le dépôt. La
règle du `.spec` balaie `outils/` en entier, et il suffirait d'en retirer
l'exclusion pour recommencer à distribuer sans que rien ne plante.

Sa licence reste citée ici parce que le programme reste **nécessaire** au
fonctionnement de l'éclairage — il est simplement fourni par l'utilisateur.
Son code source est chez son auteur :
<https://gitlab.com/CalcProgrammer1/OpenRGB>.

Cela n'a de toute façon jamais contaminé le code de l'assistant : OpenRGB
tourne dans son propre processus et l'assistant lui parle par son protocole
réseau local. C'est `openrgb-python`, ci-dessus, qui pose le vrai problème.

Ce qu'il ne faut *pas* faire sans revoir la question : intégrer du code
OpenRGB dans l'assistant, ou lier ses bibliothèques directement.

---

## PyInstaller — GPLv2 avec exception

PyInstaller est sous GPLv2, mais assortie d'une **exception explicite** qui
autorise à distribuer l'application produite sous la licence de son choix.
C'est la raison d'être de cette exception, et le point mérite d'être écrit :
lu sans elle, le tableau ci-dessous ferait croire que tout le bundle doit
passer en GPL. Ce n'est pas le cas.

---

## Bibliothèques NVIDIA — licence propriétaire

`nvidia-cublas-cu12` et `nvidia-cudnn-cu12` pèsent 1 986 Mo, soit 74 % du
dossier livré. Elles sont sous licence propriétaire NVIDIA, qui **autorise la
redistribution** avec une application, sans modification et avec l'avis de
droit d'auteur conservé — ce que fait l'installateur.

---

## Le reste — permissif

| Composant | Version | Licence |
|---|---|---|
| faster-whisper | 1.2.1 | MIT |
| ctranslate2 | 4.8.1 | MIT |
| onnxruntime | 1.29.0 | MIT |
| comtypes | 1.4.16 | MIT |
| mss | 10.2.0 | MIT |
| sounddevice | 0.5.6 | MIT |
| opencv-python | 5.0.0.93 | Apache 2.0 |
| openWakeWord | 0.6.0 | Apache 2.0 |
| rapidocr-onnxruntime | 1.4.4 | Apache 2.0 |
| watchdog | 6.0.0 | Apache 2.0 |
| huggingface-hub | 1.28.0 | Apache 2.0 |
| requests | 2.34.2 | Apache 2.0 |
| numpy | 2.5.2 | BSD-3-Clause et autres |
| scipy | 1.18.0 | BSD |
| scikit-learn | 1.9.0 | BSD-3-Clause |
| psutil | 7.2.2 | BSD-3-Clause |
| send2trash | 2.1.0 | BSD-3-Clause |
| reportlab | 5.0.1 | BSD |
| av | 18.1.0 | BSD-3-Clause |
| pyttsx3 | 2.99 | MPL-2.0 |

MPL-2.0 (pyttsx3) est un copyleft **par fichier** : tant que la bibliothèque
n'est pas modifiée, il n'y a rien à faire de plus. Si un jour un correctif y
est apporté, ce fichier-là doit être publié.

---

## Ce qui n'est PAS redistribué

Le moteur d'IA (Ollama) et les modèles de langage ne sont pas dans
l'installateur : ils sont téléchargés depuis leur source d'origine à
l'installation des composants. Leurs licences sont celles de leurs auteurs, et
l'assistant n'en redistribue aucun.
