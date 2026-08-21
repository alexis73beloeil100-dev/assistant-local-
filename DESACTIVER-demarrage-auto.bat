@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   Desactivation du demarrage automatique
echo   --------------------------------------
echo.
.venv\Scripts\python.exe -m assistant.cli demarrage-auto off
echo.
echo   Appuie sur une touche pour fermer.
pause >nul
