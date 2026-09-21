# 2026-09-21 — detached Minecraft process

Minecraft launches now use Windows detached-process flags (new process group,
no console, and best-effort job breakaway) so packaged Cubeon builds do not
present the game as a console/UI child. Linux keeps its separate session
behavior. Verified with `python -m py_compile cubeon/launch.py`.
