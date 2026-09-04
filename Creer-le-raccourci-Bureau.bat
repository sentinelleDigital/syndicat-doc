@echo off
rem ============================================================================
rem  Pose une icone "Assistant Syndical" sur le Bureau.
rem  A lancer UNE SEULE FOIS, par un double-clic. Ensuite, on n'utilise plus
rem  que l'icone du Bureau.
rem ============================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0"
title Assistant Syndical - creation du raccourci

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$bureau = [Environment]::GetFolderPath('Desktop');" ^
  "$lien = Join-Path $bureau 'Assistant Syndical.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lien);" ^
  "$s.TargetPath = Join-Path $PWD 'Assistant-Syndical.bat';" ^
  "$s.WorkingDirectory = $PWD;" ^
  "$s.Description = 'Assistant documentaire syndical - CCN 3029 + Code du travail';" ^
  "$s.IconLocation = 'shell32.dll,13';" ^
  "$s.Save();" ^
  "Write-Host ''; Write-Host ('  Raccourci cree : ' + $lien)"

echo.
echo   C'est fait. Une icone "Assistant Syndical" est sur le Bureau.
echo   Double-cliquer dessus pour lancer l'outil.
echo.
echo   Ce fichier-ci n'a plus besoin d'etre relance.
echo.
pause
