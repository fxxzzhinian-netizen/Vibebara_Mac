!include "LogicLib.nsh"

!macro customInstall
  DetailPrint "Registering Vibebara CLI in the user PATH"
  nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\cli\update-cli-path.ps1" -Action Add -TargetPath "$INSTDIR\resources\cli"'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONEXCLAMATION "Vibebara 已安装，但 CLI PATH 注册失败（退出码 $0）。$\r$\n可直接运行：$INSTDIR\resources\cli\vibebara.exe"
  ${EndIf}
!macroend

!macro customUnInstall
  ${IfNot} ${isUpdated}
    DetailPrint "Removing Vibebara CLI from the user PATH"
    nsExec::ExecToLog '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\cli\update-cli-path.ps1" -Action Remove -TargetPath "$INSTDIR\resources\cli"'
    Pop $0
    ${If} $0 != 0
      DetailPrint "Vibebara CLI PATH cleanup failed with exit code $0"
    ${EndIf}
  ${EndIf}
!macroend
