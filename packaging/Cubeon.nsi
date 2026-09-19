; Cubeon per-user Windows installer.
; SOURCE_DIR and OUTPUT_DIR are supplied by build_windows_installer.py.

!ifndef SOURCE_DIR
  !error "SOURCE_DIR is required"
!endif
!ifndef OUTPUT_DIR
  !error "OUTPUT_DIR is required"
!endif

Unicode True
Name "Cubeon"
OutFile "${OUTPUT_DIR}\Cubeon-Windows-x64-Setup.exe"
InstallDir "$LOCALAPPDATA\Cubeon"
InstallDirRegKey HKCU "Software\Cubeon" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show
ShowUnInstDetails show
SetCompressor /SOLID lzma

!define APP_EXE "$INSTDIR\Cubeon.exe"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Section "Cubeon" SEC_MAIN
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*"

  WriteRegStr HKCU "Software\Cubeon" "InstallDir" "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall Cubeon.exe"

  CreateDirectory "$SMPROGRAMS\Cubeon"
  CreateShortcut "$SMPROGRAMS\Cubeon\Cubeon.lnk" "${APP_EXE}" "" "${APP_EXE}" 0
  CreateShortcut "$DESKTOP\Cubeon.lnk" "${APP_EXE}" "" "${APP_EXE}" 0
  CreateShortcut "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk" "$INSTDIR\Uninstall Cubeon.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\Cubeon.lnk"
  Delete "$SMPROGRAMS\Cubeon\Cubeon.lnk"
  Delete "$SMPROGRAMS\Cubeon\Uninstall Cubeon.lnk"
  RMDir "$SMPROGRAMS\Cubeon"
  DeleteRegKey HKCU "Software\Cubeon"
  RMDir /r "$INSTDIR"
SectionEnd
