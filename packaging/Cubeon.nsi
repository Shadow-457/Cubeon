; Cubeon per-user Windows installer - friendly setup, no admin needed.
; SOURCE_DIR, OUTPUT_DIR, ICON_FILE and (optionally) APP_VERSION /
; DISPLAY_VERSION are supplied by build_windows_installer.py - those come in
; as Wine paths when this is compiled from Linux.
;
; Design rules for this file (the "installer feels like technical shi" fix):
;   - Modern UI: a welcome page, a plain-English where-to-install page, a
;     progress bar, and a finish page that can open Cubeon right away.
;   - NO scrolling wall of file names (ShowInstDetails is nshow, not show).
;   - The setup exe, the Start-menu entry and the desktop shortcut all carry
;     the Cubeon icon (ICON_FILE for the pages, the app exe for shortcuts).
;   - It installs per-user (HKCU, no admin prompt) and registers a proper
;     Programs-and-Features entry, so uninstalling works from Windows
;     Settings like any normal app.

!ifndef SOURCE_DIR
  !error "SOURCE_DIR is required"
!endif
!ifndef OUTPUT_DIR
  !error "OUTPUT_DIR is required"
!endif
!ifndef ICON_FILE
  !error "ICON_FILE is required"
!endif
!ifndef APP_VERSION
  !define APP_VERSION "1.0.0.0"
!endif
!ifndef DISPLAY_VERSION
  !define DISPLAY_VERSION "1.0.0"
!endif

Unicode True
Name "Cubeon"
OutFile "${OUTPUT_DIR}\Cubeon-Windows-x64-Setup.exe"
InstallDir "$LOCALAPPDATA\Cubeon"
InstallDirRegKey HKCU "Software\Cubeon" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
; Keep the file-details panes collapsed: the default "show" turned every
; install into a terminal-like scroll of extracted paths.
ShowInstDetails nshow
ShowUnInstDetails nshow
; Replace the "Nullsoft Install System vX" footer with nothing.
BrandingText " "

; Version info, so the setup exe's Properties dialog says Cubeon (and not
; an anonymous binary). VIProductVersion must be four numeric parts.
VIProductVersion "${APP_VERSION}"
VIAddVersionKey "ProductName" "Cubeon"
VIAddVersionKey "ProductVersion" "${DISPLAY_VERSION}"
VIAddVersionKey "FileDescription" "Cubeon installer"
VIAddVersionKey "CompanyName" "Cubeon"
VIAddVersionKey "LegalCopyright" "Cubeon"

; Icons: the setup and the uninstaller both show the Cubeon logo.
!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"

!include "MUI2.nsh"

!define APP_EXE "$INSTDIR\Cubeon.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Cubeon"

; --- pages: welcome, where, install, done ---------------------------------
; (single line: NSIS string-continuation across lines is easy to get wrong,
;  and this is compiled from Linux too - keep it dumb and valid)
!define MUI_WELCOMEPAGE_TEXT "This sets up Cubeon on this PC. It takes a moment and only adds Cubeon's own files - nothing else on your computer is touched, and no administrator password is needed."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Open Cubeon"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Cubeon" SEC_MAIN
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*"

  WriteRegStr HKCU "Software\Cubeon" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall Cubeon.exe"

  ; Shortcuts - icon index 0 of the app exe (the Cubeon logo).
  CreateDirectory "$SMPROGRAMS\Cubeon"
  CreateShortcut "$SMPROGRAMS\Cubeon\Cubeon.lnk" "${APP_EXE}" "" "${APP_EXE}" 0
  CreateShortcut "$DESKTOP\Cubeon.lnk" "${APP_EXE}" "" "${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk" "$INSTDIR\Uninstall Cubeon.exe"

  ; Programs & Features entry: uninstall from Windows Settings like any app.
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "Cubeon"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${DISPLAY_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Cubeon"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall Cubeon.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Cubeon.lnk"
  Delete "$SMPROGRAMS\Cubeon\Cubeon.lnk"
  Delete "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk"
  RMDir "$SMPROGRAMS\Cubeon"
  DeleteRegKey HKCU "Software\Cubeon"
  DeleteRegKey HKCU "${UNINST_KEY}"
  RMDir /r "$INSTDIR"
SectionEnd
