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

## openrgb-python — GPLv3, et c'est le point qui compte

`openrgb-python` 0.3.6 est le client Python qui parle au serveur OpenRGB. Il
est sous **GPLv3**, et contrairement à OpenRGB lui-même, il n'est pas lancé
comme un programme séparé : `assistant/skills/rgb.py` l'**importe**, aux
lignes 901, 922, 977, 1123 et 1172.

Importer, c'est lier. La simple agrégation ne s'applique plus.

**Conséquence concrète :** le code de l'assistant reste sous licence MIT et
reste réutilisable comme tel, mais **le binaire distribué**, lui, doit être
transmis sous GPLv3 — avec l'offre du code source qui va avec. Publier
l'installateur en annonçant « MIT » tout court serait inexact.

Le texte de la GPLv3 voyage déjà avec le bundle, dans
`_internal/openrgb_python-0.3.6.dist-info/LICENSE.md`.

Deux façons d'en sortir, si l'on veut un binaire entièrement permissif :

1. **Remplacer le client.** Le protocole OpenRGB SDK est un protocole binaire
   documenté sur TCP, et l'assistant n'en utilise qu'une poignée de messages
   (lister les périphériques, changer de mode, écrire des couleurs). Le
   réécrire supprime la dépendance. C'est aussi le sous-système dont le
   fonctionnement reste ouvert : les deux chantiers se rejoignent.
2. **Assumer la GPLv3** pour le binaire publié, et fournir le source. C'est
   sans effort, et parfaitement légitime — mais c'est un choix, pas un défaut,
   et il doit être écrit noir sur blanc là où les gens le lisent.

Tant que la décision n'est pas prise, l'installateur ne devrait pas annoncer
une licence permissive pour l'ensemble.

---

## OpenRGB — GPLv2

`outils/OpenRGB/` contient l'exécutable OpenRGB et ses bibliothèques Qt5.
C'est le seul composant sous licence **copyleft forte** du lot, et le seul qui
impose des obligations à la redistribution :

- le texte de la licence doit accompagner le binaire — il est desormais
  dans [`outils/OpenRGB/LICENSE-GPLv2.txt`](outils/OpenRGB/LICENSE-GPLv2.txt),
  qui manquait jusqu'au 22/08/2026 ;
- le code source doit rester accessible aux destinataires. Il l'est chez son
  auteur : <https://gitlab.com/CalcProgrammer1/OpenRGB>.

**Cela ne contamine pas le code de l'assistant.** OpenRGB est lancé comme un
programme séparé, dans son propre processus, et l'assistant lui parle par son
protocole réseau local. C'est ce que la GPL appelle une simple agrégation :
les deux œuvres voyagent ensemble sans se lier. L'assistant reste MIT.

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
