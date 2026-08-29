# Cinema Paradiso Player icon

The player has its own taskbar mark: a gold play triangle inside the Cinema
Paradiso frame. This distinguishes playback windows from the main CP app,
which keeps the lens artwork.

`cp-player-icon.png` is used by Qt for the player window. `cp-player.ico`
contains 16, 20, 24, 32, 40, 48, 64, 128, and 256 pixel versions for the
Windows executable, taskbar, title bar, and Alt+Tab.

Regenerate both assets together with:

```powershell
.\.venv\Scripts\python.exe native\player\tools\generate_player_icon.py
```
