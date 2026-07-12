# PyInstaller spec for packaging Minecraft Layerifier.
# Build with: pyinstaller minecraft_layerifier.spec

from pathlib import Path


block_cipher = None
root = Path.cwd()

a = Analysis(
    ["minecraft_layerifier.py"],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "localizations"), "localizations"),
        (str(root / "textures"), "textures"),
        (str(root / "README.md"), "."),
    ],
    hiddenimports=["nbtlib", "numpy", "PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MinecraftLayerifier",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
