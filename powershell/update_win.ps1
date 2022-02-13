If(-not(Get-InstalledModule PSWindowsUpdate -ErrorAction silentlycontinue)){
    Install-Module PSWindowsUpdate -Confirm:$False -Force
}
Get-WindowsUpdate -AcceptAll -Install -AutoReboot
