# -*- mode: python ; coding: utf-8 -*-
# Proprietas Desktop — spec PyInstaller (onedir, sans console).
# Build : pyinstaller --clean --noconfirm desktop/proprietas.spec  (depuis la racine du dépôt,
#         après `npm --prefix frontend run build`).
# macOS : même commande sur un Mac → dist/Proprietas.app (BUNDLE ; icône .icns
#         committée — régénérable avec desktop/make_icns.py).
#
# onedir et non onefile : le mode onefile s'auto-extrait dans %TEMP% puis se
# relance, un comportement qui déclenche les heuristiques de Windows Defender
# (faux positif vécu sur l'app sœur Patrimony — le mode dossier n'extrait rien).

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))  # racine du dépôt, absolue
BACKEND = os.path.join(ROOT, 'backend')

# --- Version info Windows (générée depuis frontend/package.json à chaque build) ---
_ver = json.load(open(os.path.join(ROOT, 'frontend', 'package.json'), encoding='utf-8'))['version']
_nums = tuple(([int(x) for x in _ver.split('.')] + [0, 0, 0, 0])[:4])
_vi = os.path.join(SPECPATH, 'version_info.txt')
with open(_vi, 'w', encoding='utf-8') as f:
    f.write(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={_nums}, prodvers={_nums}, mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'LostInTheBugs'),
      StringStruct('FileDescription', 'Proprietas - co-ownership management'),
      StringStruct('FileVersion', '{_ver}'),
      StringStruct('InternalName', 'Proprietas'),
      StringStruct('LegalCopyright', 'MIT License - github.com/LostInTheBugs/Proprietas'),
      StringStruct('OriginalFilename', 'Proprietas.exe'),
      StringStruct('ProductName', 'Proprietas'),
      StringStruct('ProductVersion', '{_ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
''')

a = Analysis(
    ['launcher.py'],
    pathex=[ROOT, BACKEND],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'frontend', 'dist'), 'frontend_dist'),  # SPA servie par le backend
        (os.path.join(BACKEND, 'alembic.ini'), '.'),                # migrations embarquées
        (os.path.join(BACKEND, 'alembic'), 'alembic'),
        (os.path.join(BACKEND, 'app', 'assets'), 'app/assets'),     # polices PDF (reportlab)
    ],
    hiddenimports=[
        # uvicorn importe ses implémentations dynamiquement
        'uvicorn.logging',
        'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
        'uvicorn.protocols', 'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        # fenêtre native (pywebview : plateforme choisie au runtime)
        'webview',
        'webview.platforms.winforms', 'webview.platforms.edgechromium',
        'webview.platforms.gtk', 'webview.platforms.cocoa',
        # paquets chargés dynamiquement à l'exécution
        'app', 'app.main', 'app.core.scheduler',
        'apscheduler.schedulers.background', 'apscheduler.triggers.interval',
        'apscheduler.triggers.cron', 'apscheduler.executors.pool',
        'email_validator', 'multipart',
        'passlib.handlers.bcrypt', 'bcrypt',
        'sqlalchemy.dialects.sqlite',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'psycopg2'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Proprietas',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='proprietas.ico',
    version=_vi,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Proprietas',
)

# --- macOS : bundle .app (icône .icns, version dans l'Info.plist) ----------
# N'est exécuté que sur macOS ; sur Windows/Linux la spec produit dist/Proprietas/.
if sys.platform == 'darwin':
    appl = BUNDLE(
        coll,
        name='Proprietas.app',
        icon='proprietas.icns',
        bundle_identifier='com.lostinthebugs.proprietas',
        version=_ver,
        info_plist={
            'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.finance',
            'LSMinimumSystemVersion': '12.0',
            'NSHumanReadableCopyright': 'MIT License - github.com/LostInTheBugs/Proprietas',
        },
    )
