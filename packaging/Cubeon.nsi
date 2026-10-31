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
!include "x64.nsh"

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
Var StageDir
Var SavedInternal
Var SavedExe

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

; Compare incoming DISPLAY_VERSION with installed $0; push 0/1/2.
; Thin wrapper over WordFunc's ${VersionCompare}, which does a proper part-by-
; part dotted compare (a string compare gets "1.0.9" vs "1.0.10" backwards).
; It lives in a Function only so the .onInit code below reads as one call.
Function CompareVer
  ${VersionCompare} "${DISPLAY_VERSION}" $0 $2
  Push $2
FunctionEnd

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONEXCLAMATION "Cubeon needs 64-bit Windows 10 or newer." /SD IDOK
    SetErrorLevel 1
    Quit
  ${EndIf}
  ; A previous install is the normal case only if the uninstall entry exists;
  ; a copied-over folder with no registry entry is still worth offering.
  ReadRegStr $0 HKCU "${UNINST_KEY}" "DisplayVersion"
  ; NSIS applies InstallDirRegKey and then /D before .onInit. Keep that
  ; resolved directory: reading the registry again would overwrite /D.
  ; Explicit gotos, not fallthrough: the "already installed" branch has to jump
  ; PAST the not-installed one, or finding an install would quietly return and
  ; skip the question entirely.
  ${If} $0 != ""
    Goto ask
  ${EndIf}
  ; No registry entry - files on their own still count (interrupted install, or
  ; a folder somebody copied by hand). Offer a repair rather than pretend this
  ; is a first run.
  IfFileExists "${APP_EXE}" ask not_installed
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
    Call CompareVer
    Pop $3          ; 0 same, 1 incoming newer, 2 installed newer
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
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION \
      "Cubeon is still running or its files are in use.$\r$\n$\r$\nClose every Cubeon window, then click Retry. Your games and settings will be kept." \
      /SD IDCANCEL IDRETRY ask
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

Function VerifyInstallDir
  StrLen $0 "$INSTDIR"
  ${If} $0 <= 3
    MessageBox MB_OK|MB_ICONEXCLAMATION "Choose a separate Cubeon folder inside this location." /SD IDOK
    Abort
  ${EndIf}
  ${If} $INSTDIR == "$PROFILE"
  ${OrIf} $INSTDIR == "$LOCALAPPDATA"
  ${OrIf} $INSTDIR == "$WINDIR"
  ${OrIf} $INSTDIR == "$PROGRAMFILES"
  ${OrIf} $INSTDIR == "$DESKTOP"
  ${OrIf} $INSTDIR == "$DOCUMENTS"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Choose a separate Cubeon folder inside this location." /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

; --- pages: welcome, where, install, done ---------------------------------
!define MUI_WELCOMEPAGE_TITLE "Welcome to Cubeon"
!define MUI_WELCOMEPAGE_TEXT "Play Minecraft with friends easily. No technical setup, no port forwarding.$\r$\n$\r$\nThis installer will set up Cubeon in your user folder without needing administrator rights."
!insertmacro MUI_PAGE_WELCOME

!define MUI_DIRECTORYPAGE_TEXT_TOP "Cubeon will be installed in the folder below. Click Install to begin."
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE VerifyInstallDir
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
  Call VerifyInstallDir
  ; Extract completely before replacing anything. Timestamp-only ifdiff
  ; cannot detect changed bytes with preserved timestamps, and copying over
  ; a live tree leaves obsolete DLLs/packages from previous releases.
  CreateDirectory "$INSTDIR"
  GetTempFileName $StageDir "$INSTDIR"
  Delete "$StageDir"
  CreateDirectory "$StageDir"
  SetOutPath "$StageDir"
  SetOverwrite on
  ClearErrors
  File /r "${SOURCE_DIR}\*"
  IfErrors install_failed
  IfFileExists "$StageDir\Cubeon.exe" 0 install_failed
  IfFileExists "$StageDir\_internal\*" 0 install_failed
  StrCpy $SavedInternal "0"
  StrCpy $SavedExe "0"
  IfFileExists "$INSTDIR\_internal\*" 0 save_exe
  ClearErrors
  Rename "$INSTDIR\_internal" "$StageDir\previous-internal"
  IfErrors install_failed
  StrCpy $SavedInternal "1"
save_exe:
  IfFileExists "${APP_EXE}" 0 place_internal
  ClearErrors
  Rename "${APP_EXE}" "$StageDir\previous.exe"
  IfErrors restore_internal
  StrCpy $SavedExe "1"
place_internal:
  ClearErrors
  Rename "$StageDir\_internal" "$INSTDIR\_internal"
  IfErrors restore_exe
  ClearErrors
  Rename "$StageDir\Cubeon.exe" "${APP_EXE}"
  IfErrors remove_new_internal
  SetOutPath "$INSTDIR"
  RMDir /r "$StageDir"

  WriteRegStr HKCU "${SETTINGS_KEY}" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall Cubeon.exe"

  ; Shortcuts - icon index 0 of the app exe (the Cubeon logo).
  CreateDirectory "$SMPROGRAMS\Cubeon"
  CreateShortcut "$SMPROGRAMS\Cubeon\Cubeon.lnk" "${APP_EXE}" "" "${APP_EXE}" 0
  ; Respect removal of the desktop shortcut on updates.
  ${If} $IsUpdate != "1"
    CreateShortcut "$DESKTOP\Cubeon.lnk" "${APP_EXE}" "" "${APP_EXE}" 0
  ${EndIf}
  CreateShortcut "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk" "$INSTDIR\Uninstall Cubeon.exe"

  ; Programs & Features entry: uninstall from Windows Settings like any app.
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "Cubeon"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "${APP_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${DISPLAY_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Cubeon"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall Cubeon.exe"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall Cubeon.exe" /S'
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "URLInfoAbout" "https://www.ylet.online/"
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" ${ESTIMATED_SIZE_KB}
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  Goto install_done

remove_new_internal:
  RMDir /r "$INSTDIR\_internal"
restore_exe:
  ${If} $SavedExe == "1"
    ClearErrors
    Rename "$StageDir\previous.exe" "${APP_EXE}"
    IfErrors rollback_failed
  ${EndIf}
restore_internal:
  ${If} $SavedInternal == "1"
    ClearErrors
    Rename "$StageDir\previous-internal" "$INSTDIR\_internal"
    IfErrors rollback_failed
  ${EndIf}
install_failed:
  SetOutPath "$TEMP"
  RMDir /r "$StageDir"
  MessageBox MB_OK|MB_ICONEXCLAMATION "Cubeon could not be installed. Check free disk space and close all Cubeon windows, then try again. Your previous installation and games have been kept." /SD IDOK
  SetErrorLevel 1
  Quit
rollback_failed:
  ; Preserve the backup if another process prevents restoration.
  MessageBox MB_OK|MB_ICONEXCLAMATION "Cubeon could not finish the update. Close all Cubeon windows and run setup again. The previous program files are kept in $StageDir. Your games and settings have been kept." /SD IDOK
  SetErrorLevel 1
  Quit
install_done:
SectionEnd

Section "Uninstall"
  ReadRegStr $0 HKCU "${SETTINGS_KEY}" "InstallDir"
  ${If} $0 == "$INSTDIR"
    Delete "$DESKTOP\Cubeon.lnk"
    Delete "$SMPROGRAMS\Cubeon\Cubeon.lnk"
    Delete "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk"
    RMDir "$SMPROGRAMS\Cubeon"
    DeleteRegKey HKCU "${SETTINGS_KEY}"
    DeleteRegKey HKCU "${UNINST_KEY}"
  ${EndIf}
  ; Only delete the folder when it is demonstrably OURS - our uninstaller and
  ; the app exe must both be present. A hand-edited or stale InstallDir must
  ; never make uninstall recursively delete an unrelated folder.
  IfFileExists "$INSTDIR\Uninstall Cubeon.exe" 0 uninstall_keep_folder
  IfFileExists "$INSTDIR\Cubeon.exe" 0 uninstall_keep_folder
  ; A custom install folder can contain unrelated files. Remove only the
  ; onedir program payload, then remove the root only if it is empty.
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Cubeon.exe"
  Delete "$INSTDIR\Uninstall Cubeon.exe"
  RMDir "$INSTDIR"
uninstall_keep_folder:
SectionEnd
