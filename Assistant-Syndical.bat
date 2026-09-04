@echo off
rem ============================================================================
rem  Assistant Syndical - lancement sous Windows
rem
rem  Double-cliquer sur ce fichier. Le navigateur s'ouvre tout seul.
rem  Pour arreter l'outil : fermer cette fenetre noire.
rem
rem  Rien n'est installe, rien n'est envoye sur le reseau : tout tourne sur
rem  cet ordinateur.
rem ============================================================================

rem Console en UTF-8, sinon les accents et les symboles font planter l'affichage.
chcp 65001 >nul 2>&1
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

rem Se placer dans le dossier de ce fichier, quel que soit l'endroit du disque.
cd /d "%~dp0"

title Assistant Syndical

rem --- Trouver Python -------------------------------------------------------
rem  py    : lanceur officiel, installe avec python.org. Le plus fiable.
rem  python: peut etre le vrai Python, ou le raccourci vide du Microsoft Store
rem          qui ne fait qu'ouvrir le Store. On verifie donc la version.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  for /f "tokens=2" %%v in ('python --version 2^>^&1') do (
    echo %%v | findstr /b "3." >nul && set "PY=python"
  )
)

if not defined PY goto pas_de_python

rem --- Lancement ------------------------------------------------------------
echo.
echo   Assistant Syndical - demarrage...
echo   Le navigateur va s'ouvrir. Laisser cette fenetre ouverte.
echo   Pour arreter : fermer cette fenetre.
echo.

%PY% serveur.py
set CODE=%ERRORLEVEL%

if not "%CODE%"=="0" (
  echo.
  echo   ---------------------------------------------------------------
  echo   L'assistant s'est arrete avec une erreur ^(code %CODE%^).
  echo   Le detail est affiche juste au-dessus.
  echo   ---------------------------------------------------------------
  echo.
  pause
)
exit /b %CODE%

rem --- Python absent --------------------------------------------------------
:pas_de_python
echo.
echo   ===============================================================
echo    Python n'est pas installe sur cet ordinateur.
echo   ===============================================================
echo.
echo   L'assistant en a besoin pour fonctionner. C'est gratuit, ca
echo   s'installe en trois minutes et ca ne change rien au reste de
echo   l'ordinateur.
echo.
echo   1. Ouvrir :  https://www.python.org/downloads/
echo   2. Cliquer sur le gros bouton jaune "Download Python".
echo   3. IMPORTANT : dans la premiere fenetre de l'installateur,
echo      cocher la case  "Add python.exe to PATH"  en bas.
echo      Sans cette case, il faudra recommencer.
echo   4. Cliquer "Install Now", attendre, fermer.
echo   5. Redemarrer l'ordinateur, puis double-cliquer a nouveau
echo      sur ce fichier.
echo.
echo   ---------------------------------------------------------------
echo   Ne PAS passer par le Microsoft Store : la version qui s'y
echo   trouve pose des problemes d'acces aux fichiers.
echo   ---------------------------------------------------------------
echo.
pause
exit /b 1
