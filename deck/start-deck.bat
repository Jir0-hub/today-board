@echo off
rem Deck resident watcher launcher (double-click). The launcher itself is unchanged since v1.2;
rem the Deck version is in deck_watcher.py and README.md.
rem Runs deck_watcher.py via pythonw (no console window).
rem Single-instance guard is enforced by deck_watcher.py itself.
rem Since v1.9 the lock is keyed on the board.html being watched
rem (%TEMP%\today-board-deck-locks\), not on this folder, so a copy
rem of deck_watcher.py in another folder cannot start a second
rem watcher for the same board. The second launch exits immediately
rem and watcher.log records which process holds the lock.

cd /d "%~dp0"

where pythonw >nul 2>nul
if errorlevel 1 (
    echo pythonw not found. Install Python 3 and add it to PATH.
    pause
    exit /b 1
)

start "" pythonw "%~dp0deck_watcher.py"
exit /b 0
