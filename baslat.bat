@echo off
chcp 65001 >nul
rem Başvuru Asistanı backend'ini başlatır. İlk çalıştırmada sanal ortamı kurar.
rem Sanal ortam OneDrive dışında tutulur (binlerce dosya senkronize edilmesin diye).

set "VENV=%LOCALAPPDATA%\basvuru-asistani\.venv"

rem PATH'teki python MSYS2'ninki olabilir; önce resmi Windows Python'unu ara.
if not defined PYTHON (
    for %%P in (python3.13.exe python3.12.exe python3.11.exe) do (
        if not defined PYTHON if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\%%P" set "PYTHON=%LOCALAPPDATA%\Microsoft\WindowsApps\%%P"
    )
)
if not defined PYTHON set "PYTHON=python"

if not exist "%VENV%\Scripts\python.exe" (
    echo Sanal ortam kuruluyor...
    "%PYTHON%" -m venv "%VENV%" || goto :error
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
    "%VENV%\Scripts\python.exe" -m pip install -r "%~dp0backend\requirements.txt" || goto :error
)

cd /d "%~dp0backend"
"%VENV%\Scripts\python.exe" -m app
goto :eof

:error
echo Kurulum basarisiz oldu. Python yuklu mu? (python --version)
pause
