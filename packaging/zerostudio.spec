# PyInstaller spec for ZeroStudio (onedir, windowed). Run from the project root:
#   python -m PyInstaller packaging/zerostudio.spec --noconfirm
import os

ROOT = os.path.abspath(os.getcwd())

# Qt modules ZeroStudio never uses: keep the build small
EXCLUDE_MODULES = [
    "tkinter", "unittest", "pydoc_data", "test", "lib2to3", "py7zr",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtConcurrent", "PySide6.QtDBus", "PySide6.QtHelp", "PySide6.QtMultimedia",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtUiTools", "PySide6.QtDesigner", "PySide6.QtPrintSupport",
]
# DLLs that are pulled in by PySide6 but not needed by a Widgets app.
# icu*: Wine build stub only, real Windows has its own icuuc.dll.
DROP_BINARIES = ("icu", "opengl32sw", "qt6pdf", "qt6quick", "qt6qml", "qt6network", "qt6opengl",
                 "qt6virtualkeyboard", "qt6svg", "qtvirtualkeyboard", "qt6sql", "qt6dbus")

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "zerostudio", "vendor"), os.path.join("zerostudio", "vendor")),
           (os.path.join(ROOT, "assets", "zerostudio.ico"), "assets")],
    hiddenimports=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
)


def keep(entry):
    name = os.path.basename(entry[0]).lower()
    return not name.startswith(DROP_BINARIES)


a.binaries = [b for b in a.binaries if keep(b)]
# Qt plugins we don't need (image formats except ico/png, tls, network info ...)
a.binaries = [b for b in a.binaries if not any(p in b[0].replace("\\", "/").lower() for p in (
    "plugins/tls/", "plugins/networkinformation/", "plugins/generic/", "plugins/imageformats/qpdf",
    "plugins/imageformats/qsvg", "plugins/iconengines/qsvg", "plugins/platforminputcontexts/"))]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/").lower()]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ZeroStudio",
    console=False,
    icon=os.path.join(ROOT, "assets", "zerostudio.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ZeroStudio", upx=False)
