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
Var MoveSource
Var MoveTarget
Var MoveError
Var MoveAttempts
Var FailureStep
Var FailurePath
Var FailureCode
Var FailureAdvice
Var SetupLog

; Directory swaps can race the exiting desktop client or a scanner. Capture
; the native error immediately and retry only transient sharing/access errors.
; Never replace an existing destination or schedule a replacement at reboot.
Function MoveProgramEntry
  StrCpy $MoveAttempts "20"
move_retry:
  System::Call 'kernel32::MoveFileW(w "$MoveSource", w "$MoveTarget") i.r0 ?e'
  Pop $MoveError
  ${If} $0 != 0
    StrCpy $MoveError "0"
    Return
  ${EndIf}
  IntOp $MoveAttempts $MoveAttempts - 1
  ${If} $MoveAttempts > 0
  ${AndIf} $MoveError == 5
    Sleep 250
    Goto move_retry
  ${ElseIf} $MoveAttempts > 0
  ${AndIf} $MoveError == 32
    Sleep 250
    Goto move_retry
  ${ElseIf} $MoveAttempts > 0
  ${AndIf} $MoveError == 33
    Sleep 250
    Goto move_retry
  ${EndIf}
FunctionEnd

!macro MoveProgram SOURCE TARGET STEP FAILED
  StrCpy $MoveSource "${SOURCE}"
  StrCpy $MoveTarget "${TARGET}"
  Call MoveProgramEntry
  ${If} $MoveError != 0
    StrCpy $FailureStep "${STEP}"
    StrCpy $FailurePath "$MoveSource -> $MoveTarget"
    StrCpy $FailureCode "$MoveError"
    Goto ${FAILED}
  ${EndIf}
!macroend

Function RecordSetupFailure
  StrCpy $FailureAdvice "Try setup again, or choose a separate Cubeon folder you can write to."
  ${If} $FailureCode == 5
    StrCpy $FailureAdvice "Windows denied access. Choose a folder you can write to, or check whether another process is using these files."
  ${ElseIf} $FailureCode == 32
  ${OrIf} $FailureCode == 33
    StrCpy $FailureAdvice "Another process is using these files. End any remaining Cubeon.exe or flet.exe belonging to Cubeon in Task Manager, then retry setup."
  ${ElseIf} $FailureCode == 112
    StrCpy $FailureAdvice "The destination or temporary drive is full. Free space on that drive, then retry setup."
  ${ElseIf} $FailureCode == 183
    StrCpy $FailureAdvice "A conflicting file or folder already exists. Choose a new Cubeon installation folder."
  ${ElseIf} $FailureCode == 206
    StrCpy $FailureAdvice "The installation path is too long. Choose a shorter Cubeon folder path."
  ${EndIf}
  DetailPrint "Setup failed: $FailureStep ($FailureCode): $FailurePath"
  ClearErrors
  FileOpen $SetupLog "$INSTDIR\Cubeon-Setup.log" "a"
  ${If} $SetupLog != ""
    ; NSIS 'a' preserves contents but does not position at EOF.
    FileSeek $SetupLog 0 END
    FileWrite $SetupLog "Cubeon ${DISPLAY_VERSION}: $FailureStep$\r$\nWindows error: $FailureCode$\r$\nPath: $FailurePath$\r$\n$FailureAdvice$\r$\nBackup/stage: $StageDir$\r$\n$\r$\n"
    FileClose $SetupLog
  ${EndIf}
FunctionEnd

; Detect update/repair for welcome copy; native staged swaps report real locks.
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
  ; Only a downgrade needs a separate choice. Normal updates/repairs use
  ; the wizard, and /S remains suitable for the authorized update handoff.
  ${If} $0 != ""
    Call CompareVer
    Pop $3
    ${If} $3 == "2"
      MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
        "Cubeon $0 is installed. This setup installs the older ${DISPLAY_VERSION}.$\r$\n$\r$\nInstall the older version? Your games and settings will be kept." \
        /SD IDYES IDYES do_install
      SetErrorLevel 1
      Quit
    ${EndIf}
  ${EndIf}
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
!define MUI_WELCOMEPAGE_TEXT "Install Cubeon ${DISPLAY_VERSION} and start playing Minecraft with friends.$\r$\n$\r$\nSetup adds Cubeon to your Start Menu without an administrator password. Existing installations are updated or repaired; your games, worlds and settings are kept.$\r$\n$\r$\nClose Cubeon before installing."
!insertmacro MUI_PAGE_WELCOME

!define MUI_DIRECTORYPAGE_TEXT_TOP "Cubeon will be installed in the folder below. Click Install to begin."
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE VerifyInstallDir
!insertmacro MUI_PAGE_DIRECTORY

!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "Cubeon is ready"
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
  StrCpy $FailureStep "create the installation folder"
  StrCpy $FailurePath "$INSTDIR"
  StrCpy $FailureCode "not available"
  StrCpy $StageDir ""
  StrCpy $SavedInternal "0"
  StrCpy $SavedExe "0"
  ClearErrors
  CreateDirectory "$INSTDIR"
  IfErrors prepare_failed
  GetTempFileName $StageDir "$INSTDIR"
  IfErrors prepare_failed
  Delete "$StageDir"
  IfErrors prepare_failed
  CreateDirectory "$StageDir"
  IfErrors prepare_failed
  SetOutPath "$StageDir"
  SetOverwrite on
  StrCpy $FailureStep "extract the new program files"
  StrCpy $FailurePath "$StageDir"
  ClearErrors
  File /r "${SOURCE_DIR}\*"
  IfErrors extract_failed
  ; File /r may enter runtime subdirectories. Leave the staged tree BEFORE
  ; renaming it: Windows holds a process's current directory open.
  SetOutPath "$INSTDIR"
  StrCpy $FailureStep "verify the downloaded program files"
  StrCpy $FailureCode "not available"
  IfFileExists "$StageDir\Cubeon.exe" 0 install_failed
  IfFileExists "$StageDir\_internal\*" 0 install_failed
  ; Include an empty runtime directory left by an interrupted setup.
  IfFileExists "$INSTDIR\_internal\." 0 save_exe
  !insertmacro MoveProgram "$INSTDIR\_internal" "$StageDir\previous-internal" "back up the previous runtime" install_failed
  StrCpy $SavedInternal "1"
save_exe:
  IfFileExists "${APP_EXE}" 0 place_internal
  !insertmacro MoveProgram "${APP_EXE}" "$StageDir\previous.exe" "back up the previous launcher" restore_internal
  StrCpy $SavedExe "1"
place_internal:
  !insertmacro MoveProgram "$StageDir\_internal" "$INSTDIR\_internal" "place the new runtime" restore_exe
  !insertmacro MoveProgram "$StageDir\Cubeon.exe" "${APP_EXE}" "place the new launcher" remove_new_internal
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
  ; Move the new tree aside rather than deleting it during rollback.
  StrCpy $MoveSource "$INSTDIR\_internal"
  StrCpy $MoveTarget "$StageDir\_internal"
  Call MoveProgramEntry
  ${If} $MoveError != 0
    Goto rollback_failed
  ${EndIf}
restore_exe:
  ${If} $SavedExe == "1"
    StrCpy $MoveSource "$StageDir\previous.exe"
    StrCpy $MoveTarget "${APP_EXE}"
    Call MoveProgramEntry
    ${If} $MoveError != 0
      Goto rollback_failed
    ${EndIf}
  ${EndIf}
restore_internal:
  ${If} $SavedInternal == "1"
    StrCpy $MoveSource "$StageDir\previous-internal"
    StrCpy $MoveTarget "$INSTDIR\_internal"
    Call MoveProgramEntry
    ${If} $MoveError != 0
      Goto rollback_failed
    ${EndIf}
  ${EndIf}
  Goto install_failed
prepare_failed:
extract_failed:
  System::Call 'kernel32::GetLastError() i.r0'
  ${If} $0 != 0
    StrCpy $FailureCode "$0"
  ${EndIf}
install_failed:
  Call RecordSetupFailure
  SetOutPath "$TEMP"
  ${If} $StageDir != ""
    RMDir /r "$StageDir"
  ${EndIf}
  MessageBox MB_OK|MB_ICONEXCLAMATION "Setup could not $FailureStep.$\r$\n$\r$\nWindows error: $FailureCode$\r$\n$FailurePath$\r$\n$\r$\n$FailureAdvice$\r$\n$\r$\nDetails are in $INSTDIR\Cubeon-Setup.log (if the folder is writable). Your previous installation and games have been kept." /SD IDOK
  SetErrorLevel 1
  Quit
rollback_failed:
  ; Preserve the backup if another process prevents restoration.
  Call RecordSetupFailure
  DetailPrint "Rollback failed ($MoveError): $MoveSource -> $MoveTarget"
  FileOpen $SetupLog "$INSTDIR\Cubeon-Setup.log" "a"
  ${If} $SetupLog != ""
    FileSeek $SetupLog 0 END
    FileWrite $SetupLog "Rollback error: $MoveError$\r$\n$MoveSource -> $MoveTarget$\r$\n"
    FileClose $SetupLog
  ${EndIf}
  MessageBox MB_OK|MB_ICONEXCLAMATION "Setup could not $FailureStep (Windows error $FailureCode), and could not restore the previous program files (Windows error $MoveError).$\r$\n$\r$\n$FailureAdvice$\r$\n$\r$\nThe previous program files are kept in $StageDir. Details are in $INSTDIR\Cubeon-Setup.log. Your games and settings have been kept." /SD IDOK
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
  Delete "$INSTDIR\Cubeon-Setup.log"
  RMDir "$INSTDIR"
uninstall_keep_folder:
SectionEnd
