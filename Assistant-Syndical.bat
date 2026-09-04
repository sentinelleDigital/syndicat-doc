@echo off
rem ============================================================================
rem  Assistant Syndical - Windows.
rem  Double-cliquer sur ce fichier. Le navigateur s'ouvre tout seul.
rem  Pour arreter : fermer cette fenetre noire.
rem
rem  Ce fichier ne fait que trouver Python et passer la main a demarrer.py,
rem  qui contient toute la logique, commune a Windows, Linux et macOS.
rem ============================================================================

chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Assistant Syndical

rem --- Trouver Python -------------------------------------------------------
rem  py     : lanceur officiel installe avec python.org. Le plus fiable.
rem  python : peut aussi etre le raccourci vide du Microsoft Store, qui se
rem           contente d'ouvrir la boutique. On verifie donc la version.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  for /f "tokens=2" %%v in ('python --version 2^>^&1') do (
    echo %%v | findstr /b "3." >nul && set "PY=python"
  )
)
if not defined PY goto pas_de_python

%PY% demarrer.py %*
set CODE=%ERRORLEVEL%
if not "%CODE%"=="0" (
  echo.
  echo   L'assistant s'est arrete ^(code %CODE%^). Le detail est au-dessus.
  echo.
  pause
)
exit /b %CODE%

:pas_de_python
echo.
echo   ===============================================================
echo    Python n'est pas installe sur cet ordinateur.
echo   ===============================================================
echo.
echo   L'assistant en a besoin. C'est gratuit et ca s'installe en
echo   trois minutes, sans rien changer au reste de l'ordinateur.
echo.
echo   1. Ouvrir :  https://www.python.org/downloads/
echo   2. Cliquer sur le gros bouton jaune "Download Python".
echo   3. IMPORTANT : dans la premiere fenetre de l'installateur,
echo      cocher la case  "Add python.exe to PATH"  tout en bas.
echo      Sans cette case, il faudra recommencer.
echo   4. Cliquer "Install Now", attendre, fermer.
echo   5. Redemarrer l'ordinateur, puis double-cliquer a nouveau ici.
echo.
echo   Ne PAS passer par le Microsoft Store : sa version pose des
echo   problemes d'acces aux fichiers.
echo.
pause
exit /b 1
