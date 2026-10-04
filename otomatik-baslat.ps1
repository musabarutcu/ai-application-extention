# Başvuru Asistanı backend'ini Windows açılışında penceresiz başlatır.
#
#   Aç:     powershell -ExecutionPolicy Bypass -File otomatik-baslat.ps1
#   Kapat:  powershell -ExecutionPolicy Bypass -File otomatik-baslat.ps1 -Kaldir
#
# Başlangıç klasörüne bir kısayol koyar (Görev Zamanlayıcı / yönetici izni gerekmez).
# Loglar: %LOCALAPPDATA%\basvuru-asistani\backend.log

param([switch]$Kaldir)

$ErrorActionPreference = "Stop"
$startup  = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "Başvuru Asistanı.lnk"

if ($Kaldir) {
    if (Test-Path $shortcut) { Remove-Item $shortcut -Confirm:$false }
    Write-Output "Otomatik başlatma kapatıldı. (Çalışan backend bir sonraki yeniden başlatmada kapanır.)"
    exit 0
}

$backend = Join-Path $PSScriptRoot "backend"
$pythonw = Join-Path $env:LOCALAPPDATA "basvuru-asistani\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Error "Sanal ortam bulunamadı ($pythonw). Önce baslat.bat'ı bir kez çalıştır."
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $pythonw
$link.Arguments = "-m app"
$link.WorkingDirectory = $backend
$link.Description = "Başvuru Asistanı backend (penceresiz)"
$link.Save()

# Şimdi de başlat (zaten çalışıyorsa yeni kopya kendini kapatır)
Start-Process -FilePath $pythonw -ArgumentList "-m", "app" -WorkingDirectory $backend -WindowStyle Hidden
Write-Output "Otomatik başlatma açık: $shortcut"
