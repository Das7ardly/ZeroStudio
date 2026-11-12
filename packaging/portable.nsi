; ZeroStudio portable: a single exe that unpacks the app into a folder you choose (no install, no registry).
Unicode true
Target amd64-unicode
!ifndef VERSION
  !define VERSION "1.9.0"
!endif
!define APP "ZeroStudio"
Name "${APP} ${VERSION} Portable"
OutFile "..\release\${APP}-Portable-${VERSION}.exe"
InstallDir "$DESKTOP\${APP}"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
Icon "..\assets\zerostudio.ico"
BrandingText "${APP} ${VERSION} Portable"
!include "MUI2.nsh"
!define MUI_ICON "..\assets\zerostudio.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_DIRECTORYPAGE_TEXT_TOP "Choose where to unpack ${APP}. Nothing is installed: run ${APP}.exe from that folder, delete the folder to remove it. (Settings are kept in %LOCALAPPDATA%\${APP}.)"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APP}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APP} Portable"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APP} portable"
VIAddVersionKey "LegalCopyright" "ASHKELAD"
Section
  SetOutPath "$INSTDIR"
  File /r "..\dist\${APP}\*.*"
SectionEnd
