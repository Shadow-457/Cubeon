; Cubeon per-user Windows installer - friendly setup, no admin needed.
; SOURCE_DIR, OUTPUT_DIR, ICON_FILE and (optionally) APP_VERSION /
; DISPLAY_VERSION are supplied by build_windows_installer.py - those come in
; as Wine paths when this is compiled from Linux.
;
; Design rules for this file (the "installer feels like technical shi" fix):
;   - Modern UI: a welcome page, a plain-English where-to-install page, a
;     progress bar, and a finish page that can open Cubeon right away.
;   - NO scrolling wall of file names (details hidden but still expandable).
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
; Approximate installed size in KB for Programs & Features, supplied by
; build_windows_installer.py (it walks the payload); the default is a sane
; fallback so the .nsi can also be compiled by hand.
!ifndef ESTIMATED_SIZE_KB
  !define ESTIMATED_SIZE_KB "160000"
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
ShowInstDetails hide
ShowUnInstDetails hide
; Replace the "Nullsoft Install System vX" footer with nothing.
BrandingText " "

; Version info, so the setup exe's Properties dialog says Cubeon (and not
; an anonymous binary). VIProductVersion must be four numeric parts.
VIProductVersion "${APP_VERSION}"
VIAddVersionKey "ProductName" "Cubeon"
VIAddVersionKey "ProductVersion" "${DISPLAY_VERSION}"
VIAddVersionKey "FileVersion" "${DISPLAY_VERSION}"
VIAddVersionKey "FileDescription" "Cubeon installer"
VIAddVersionKey "CompanyName" "Cubeon"
VIAddVersionKey "LegalCopyright" "Cubeon"

; Icons: the setup and the uninstaller both show the Cubeon logo.
!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"

; Modern visual styling
!ifdef WIZARD_IMAGE
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${WIZARD_IMAGE}"
  !define MUI_UNWELCOMEFINISHPAGE_BITMAP "${WIZARD_IMAGE}"
!endif
!ifdef HEADER_IMAGE
  !define MUI_HEADERIMAGE
  !define MUI_HEADERIMAGE_BITMAP "${HEADER_IMAGE}"
  !define MUI_HEADERIMAGE_RIGHT
!endif

!define MUI_ABORTWARNING

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WordFunc.nsh"

!define APP_EXE "$INSTDIR\Cubeon.exe"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Cubeon"
!define SETTINGS_KEY "Software\Cubeon"
!define DEFAULT_INSTDIR "$LOCALAPPDATA\Cubeon"

; Set in .onInit when an existing install was found, so the section knows this
; run is an update/repair.
Var IsUpdate
; The folder a previous Cubeon was actually found in (NOT necessarily the
; default - the user may have chosen a custom path, and InstallDirRegKey
; restores it). Tracked so the update logic keys off the real old install, not
; a hardcoded default.
Var OldInstDir

; --- already-installed? ------------------------------------------------------
; Launching the setup over an existing Cubeon used to silently overwrite it: the
; user got no idea an older build was being replaced, and - worse - if Cubeon
; was RUNNING, the copy fought the locked .exe and failed halfway with an
; unhelpful error. So .onInit works out what is actually on the machine and
; asks, in plain words, before touching anything.
;
; There is no process-listing plugin available to this NSIS build, so "is it
; running?" is answered the way Windows answers it: try to open the exe for
; writing. A running app holds that file locked, and the open fails. Far more
; reliable than guessing from a window title - and the installer's own window
; is titled "Cubeon" too, so a title search would have matched itself.

; CompareVer $0 $1 -> pushes "0" equal, "1" left newer, "2" right newer.
; Thin wrapper over WordFunc's ${VersionCompare}, which does a proper part-by-
; part dotted compare (a string compare gets "1.0.9" vs "1.0.10" backwards).
; It lives in a Function only so the .onInit code below reads as one call.
Function CompareVer
  ${VersionCompare} $0 $1 $2
  Push $2
FunctionEnd

Function .onInit
  ; A previous install is the normal case only if the uninstall entry exists;
  ; a copied-over folder with no registry entry is still worth offering.
  ReadRegStr $0 HKCU "${UNINST_KEY}" "DisplayVersion"
  ReadRegStr $1 HKCU "${SETTINGS_KEY}" "InstallDir"
  ${If} $1 != ""
    StrCpy $INSTDIR $1
  ${EndIf}
  ; Explicit gotos, not fallthrough: the "already installed" branch has to jump
  ; PAST the not-installed one, or finding an install would quietly return and
  ; skip the question entirely.
  ${If} $0 != ""
    Goto ask
  ${EndIf}
  ; No registry entry - files on their own still count (interrupted install, or
  ; a folder somebody copied by hand). Offer a repair rather than pretend this
  ; is a first run.
  IfFileExists "${APP_EXE}" not_installed ask
not_installed:
  Return

ask:
  StrCpy $IsUpdate "1"
  ; Remember where the old install actually lives (the registry path, or the
  ; default we just resolved). The section below uses this instead of assuming
  ; $LOCALAPPDATA\Cubeon.
  StrCpy $OldInstDir "$INSTDIR"
  ; Word the prompt by what will actually happen to the files. $0 is empty when
  ; the files were found with no registry entry to read a version from.
  ${If} $0 == ""
    StrCpy $2 "Cubeon is already installed on this computer, but there is no version information for it.$\r$\n$\r$\nRun the setup again to repair it?$\r$\n$\r$\nClick Yes to repair, No to exit."
  ${Else}
    Push $0
    Push "${DISPLAY_VERSION}"
    Call CompareVer
    Pop $3          ; 0 same, 1 incoming newer, 2 installed newer
    Pop $0
    ${If} $3 == "1"
      StrCpy $2 "Update Cubeon?$\r$\n$\r$\nYou have Cubeon $0. This setup is Cubeon ${DISPLAY_VERSION}.$\r$\n$\r$\nClick Yes to update, No to exit."
    ${ElseIf} $3 == "2"
      StrCpy $2 "Cubeon $0 is already installed, and this setup is the OLDER Cubeon ${DISPLAY_VERSION}.$\r$\n$\r$\nClick Yes to install it anyway (this downgrades Cubeon), No to exit."
    ${Else}
      StrCpy $2 "Cubeon ${DISPLAY_VERSION} is already installed.$\r$\n$\r$\nClick Yes to reinstall it, No to exit."
    ${EndIf}
  ${EndIf}

  ; A running launcher holds its own .exe open against writing, and
  ; overwriting a locked file fails halfway through with a raw Windows error.
  ; There is no process-listing plugin in this NSIS build, so the probe is the
  ; one Windows itself answers with: try to open the file for writing. Opened
  ; in APPEND mode so a successful probe cannot truncate anything - it only
  ; proves the file is not locked. (Searching for a window by title would be
  ; worse than useless here: the installer's own window is titled "Cubeon"
  ; too, so it would always match itself.)
  ;
  ; Only worth asking when the exe is actually there - a registry entry with no
  ; files is a broken install, and "close Cubeon first" would be a lie.
  IfFileExists "${APP_EXE}" 0 exe_not_running
  ClearErrors
  FileOpen $4 "${APP_EXE}" "a"
  ${If} $4 == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Cubeon is still running.$\r$\n$\r$\nClose Cubeon, then run this setup again." \
      /SD IDOK
    SetErrorLevel 1
    Quit
  ${EndIf}
  FileClose $4
exe_not_running:

  ; /SD keeps unattended installs (the release CI, `setup /S`) going: there is
  ; nobody to answer a dialog, so "proceed" is the only sensible default.
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON1 "$2" /SD IDYES IDYES do_install
  SetErrorLevel 1
  Quit
do_install:
FunctionEnd

; --- pages: welcome, where, install, done ---------------------------------
!define MUI_WELCOMEPAGE_TITLE "Welcome to Cubeon"
!define MUI_WELCOMEPAGE_TEXT "Play Minecraft with friends easily. No technical setup, no port forwarding.$\r$\n$\r$\nThis installer will set up Cubeon in your user folder without needing administrator rights."
!insertmacro MUI_PAGE_WELCOME

!define MUI_DIRECTORYPAGE_TEXT_TOP "Cubeon will be installed in the folder below. Click Install to begin."
!insertmacro MUI_PAGE_DIRECTORY

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "Cubeon is Ready"
!define MUI_FINISHPAGE_TEXT "Cubeon has been installed successfully.$\r$\n$\r$\nYou can launch it right now or find it anytime in your Start Menu."
!define MUI_FINISHPAGE_RUN "${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch Cubeon"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Cubeon" SEC_MAIN
  ; Updates no longer wipe the folder first. The old flow did `RMDir /r
  ; "$INSTDIR"` then `File /r`, i.e. delete and rewrite every one of the
  ; hundreds of files - double the disk I/O and double the antivirus scan,
  ; which is the "updating deletes for ages" the user reported. We now copy
  ; over the top with `SetOverwrite ifdiff`: NSIS compares each file and only
  ; writes the ones that actually changed, so the big unchanged pieces
  ; (assets/jars ~62 MB, the bundled flet client ~40 MB, the DLLs) are skipped
  ; entirely.
  ;
  ; `File /r` never deletes, so a file the new build DROPPED would linger. The
  ; only spot that has bitten us is a stale `templates` package dir (the
  ; seasonal palettes once shipped as data there). Clear just that small,
  ; code-only path - never the large assets - so an update stays correct
  ; without paying for a full wipe.
  ;
  ; Everything the user owns (settings, auth key, friends cache, downloaded
  ; runtimes) lives in %USERPROFILE%\.cubeon_launcher and the game in
  ; \.cubeon_minecraft, so this folder is program files only.
  ${If} $IsUpdate == "1"
    SetOverwrite ifdiff
    RMDir /r "$INSTDIR\_internal\templates"
  ${Else}
    SetOverwrite on
  ${EndIf}

  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*"
  SetOverwrite on

  WriteRegStr HKCU "${SETTINGS_KEY}" "InstallDir" "$INSTDIR"
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
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall Cubeon.exe" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "https://cubeon.vercel.app"
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" ${ESTIMATED_SIZE_KB}
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Cubeon.lnk"
  Delete "$SMPROGRAMS\Cubeon\Cubeon.lnk"
  Delete "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk"
  RMDir "$SMPROGRAMS\Cubeon"
  DeleteRegKey HKCU "${SETTINGS_KEY}"
  DeleteRegKey HKCU "${UNINST_KEY}"
  ; Only delete the folder when it is demonstrably OURS - our uninstaller and
  ; the app exe must both be present. A hand-edited or stale InstallDir must
  ; never make uninstall recursively delete an unrelated folder.
  IfFileExists "$INSTDIR\Uninstall Cubeon.exe" 0 uninstall_keep_folder
  IfFileExists "$INSTDIR\Cubeon.exe" 0 uninstall_keep_folder
  RMDir /r "$INSTDIR"
uninstall_keep_folder:
SectionEnd
