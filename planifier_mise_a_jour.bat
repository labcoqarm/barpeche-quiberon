@echo off
rem A lancer une seule fois : cree une tache Windows qui lance mise_a_jour.bat le 1er de chaque mois a 10 h. Quand il n'y a rien de neuf, elle s'arrete en quelques secondes.
schtasks /Create /F /TN "BarPeche mise a jour" /SC MONTHLY /D 1 /ST 10:00 /TR "\"%~dp0mise_a_jour.bat\""
if errorlevel 1 (echo La tache n'a pas pu etre creee.) else (echo Tache creee. Pour la retirer : schtasks /Delete /TN "BarPeche mise a jour")
pause
