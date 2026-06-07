# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 니콘 친게 음원 감별사
# Build: pyinstaller nikon-chinge-analyzer-py.spec

block_cipher = None

a = Analysis(
    ['analyzer.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'soundfile',
        'pydub',
        'numpy',
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.sip',
        'cffi',
        'pkg_resources',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'scipy', 'PIL', 'cv2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='니콘_친게_음원_감별사',
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
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='니콘_친게_음원_감별사',
)

app = BUNDLE(
    coll,
    name='니콘 친게 음원 감별사.app',
    icon=None,
    bundle_identifier='com.nikonchinge.analyzer',
    info_plist={
        'CFBundleDisplayName': '니콘 친게 음원 감별사',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'LSApplicationCategoryType': 'public.app-category.music',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Audio File',
                'CFBundleTypeExtensions': ['flac', 'wav', 'aiff', 'aif', 'ogg', 'mp3', 'm4a', 'aac', 'opus'],
                'CFBundleTypeRole': 'Viewer',
            }
        ],
    },
)
