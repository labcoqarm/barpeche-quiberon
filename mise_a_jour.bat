@echo off
rem Met BarPeche a jour : telecharge la saison ecoulee et recalcule la saison suivante. Lance chaque mois par la tache planifiee ; on peut aussi double-cliquer dessus.
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "CONDA="
for %%D in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%ProgramData%\anaconda3" "%ProgramData%\miniconda3") do if exist "%%~D\Scripts\activate.bat" set "CONDA=%%~D"
if not defined CONDA (
  echo Anaconda introuvable : corriger le chemin dans mise_a_jour.bat
  exit /b 1
)
call "%CONDA%\Scripts\activate.bat" base
if not exist data mkdir data
python chaine\v2_run.py %* >> data\mise_a_jour.log 2>&1
echo Fini, voir data\mise_a_jour.log
