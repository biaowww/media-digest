# 部署第二台巡检机（Mac）

目标：家里 PC 关机时，Mac 顶上，chat 写进 Drive 的新剧照样 1–2 分钟出现在 GitHub。两台机都在跑也没关系：构建前 `git pull --rebase`，push 撞车自动重试；空转 0.5 秒。

## 前置

- Google Drive for desktop 已登录同一账号，`claude` 文件夹在 `~/Library/CloudStorage/GoogleDrive-<账号>/My Drive/claude`（或「我的云端硬盘」），`scraper/paths.py` 会自动探测；不对就设 `CLAUDE_DRIVE_ROOT`。
- `gh auth login`（或 git 凭证）能 push `biaowww/media-digest`。
- Python 3.10+：`pip3 install -r scraper/requirements.txt`。
- TMDB 凭证不用配：脚本回退读 Drive `shows/_tmdb_key.txt`。

## 装

```bash
cd ~/code && git clone https://github.com/biaowww/media-digest.git && cd media-digest
chmod +x run_build.sh
./run_build.sh --no-push          # 先本地跑通：应看到 3 部剧 synced、no changes
```

launchd 每分钟一次（用户级）：

```bash
cat > ~/Library/LaunchAgents/com.biaowww.media-digest-build.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.biaowww.media-digest-build</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd ~/code/media-digest && ./run_build.sh task</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/media-digest-build.out</string>
  <key>StandardErrorPath</key><string>/tmp/media-digest-build.err</string>
</dict></plist>
EOF
launchctl load ~/Library/LaunchAgents/com.biaowww.media-digest-build.plist
launchctl list | grep media-digest
```

查：`cat scraper/logs/last-run.txt`（每分钟更新）、`tail scraper/logs/build.log`（只有变化/失败才写）。卸：`launchctl unload ~/Library/LaunchAgents/com.biaowww.media-digest-build.plist`。

## Windows（家里 PC，已装）

计划任务 `media-digest-build`：每 1 分钟，**直接用 `pythonw.exe scraper\build.py --quiet`**（无控制台 Python，不会有窗口一闪；用 cmd 跑 .bat 会每分钟弹一下黑窗）。查看 `schtasks /query /tn media-digest-build`；手动检查用双击 `run_build.bat`（会留窗显示结果）。

重建任务（PowerShell）：

```powershell
$a = New-ScheduledTaskAction -Execute "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe" -Argument 'scraper\build.py --quiet' -WorkingDirectory 'E:\claude_project\media-digest'
$t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew -Hidden
Register-ScheduledTask -TaskName media-digest-build -Action $a -Trigger $t -Settings $s -Force
```
