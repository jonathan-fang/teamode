# Windows Desktop Shortcut

Launch TeaMode in Windows Terminal with a desktop shortcut:

1. Right-click the desktop → **New** → **Shortcut**.
2. Paste the following as the target:

```
wt.exe --size 55,30 -p "Ubuntu" wsl.exe --cd ~ -e bash -i -c "~/WSL/github.com/jonathan-fang/teamode/scripts/teamode_launcher.sh"
```

3. Name it **TeaMode** and click Finish.

**Notes:**
- Replace `"Ubuntu"` with your WSL profile name in Windows Terminal if different.
- The launcher sources `~/.teamode-secrets` automatically — no manual env setup needed.
- To launch the stable worktree instead: append `stable` to the launcher call in the wt.exe target:
  ```
  wt.exe --size 55,30 -p "Ubuntu" wsl.exe --cd ~ -e bash -i -c "~/WSL/github.com/jonathan-fang/teamode/scripts/teamode_launcher.sh stable"
  ```
