!include "LogicLib.nsh"

!macro customInit
  ; Electron 主进程和 ELECTRON_RUN_AS_NODE 本地代理均使用 Vibebara.exe。
  ; 升级时代理可能比窗口晚退出，electron-builder 的进程检测会因此反复提示无法关闭。
  DetailPrint "Stopping existing Vibebara processes before upgrade"
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /F /T /IM "Vibebara.exe"'
  Pop $0
  Sleep 1000
!macroend

!macro customCheckAppRunning
  ; customInit 已按精确映像名清理进程。覆盖 electron-builder 默认的模糊匹配检测，
  ; 避免应用未运行时仍反复弹出“Vibebara 无法关闭”。
!macroend

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
