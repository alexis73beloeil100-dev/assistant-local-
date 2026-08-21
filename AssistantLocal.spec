# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

# probe.ps1 n'est pas du Python : sans cette ligne, PyInstaller l'ignore et
# l'application packagee ne sait plus relever la configuration de la machine.
datas = [('assistant/skills/probe.ps1', 'assistant/skills'),
         ('assistant/skills/inventaire.ps1', 'assistant/skills')]

# Outils tiers portables embarques avec l'application.
#
# L'utilisateur ne veut rien installer sur sa machine : ces outils vivent DANS
# l'assistant, partent avec lui et s'en vont avec lui. Le dossier est declare
# seulement s'il existe -- l'application doit se construire meme sans, et
# expliquer proprement ce qui manque plutot que d'echouer a la construction.
import os as _os

if _os.path.isdir('outils'):
    for _racine, _sous, _fichiers in _os.walk('outils'):
        if _fichiers:
            datas.append((_os.path.join(_racine, '*'), _racine))
binaries = []
hiddenimports = ['pyttsx3.drivers', 'pyttsx3.drivers.sapi5', 'pynput.keyboard._win32', 'pynput.mouse._win32']
hiddenimports += collect_submodules('assistant')

# RapidOCR embarque ses modeles ONNX comme fichiers de donnees. Sans cette
# collecte l'executable se construit sans erreur, puis echoue a la premiere
# lecture d'image sur un FileNotFoundError.
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('openwakeword')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyttsx3')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('comtypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('nvidia')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# pywin32, pour trois choses qui echouent silencieusement sans lui :
# l'enumeration des applications du Microsoft Store (shell:AppsFolder), la
# restauration depuis la corbeille, et la lecture des voix OneCore. Ces
# modules sont importes A L'INTERIEUR des fonctions, donc l'analyse statique
# de PyInstaller ne les voit pas -- meme piege que pour le paquet assistant.
hiddenimports += ['win32com', 'win32com.client', 'pythoncom', 'pywintypes',
                  'win32api', 'win32gui', 'win32con']

# Le SDK officiel d'OpenRGB. Importe a l'interieur des fonctions, donc
# invisible a l'analyse statique -- meme piege que pour pywin32 et pour le
# paquet assistant lui-meme. Sans lui, l'executable se construit sans erreur
# et l'eclairage RGB cesse de fonctionner en silence.
hiddenimports += ['openrgb', 'openrgb.orgb', 'openrgb.utils',
                  'openrgb.network', 'openrgb.consts']
tmp_ret = collect_all('openrgb')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('win32com')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['AssistantLocal.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AssistantLocal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AssistantLocal',
)
