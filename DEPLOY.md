# 部署第二台构建机（Mac）

目标：家里 PC 关机时，Mac 顶上，chat 写进 Drive 的新剧照样在下一次构建后出现在 GitHub。两台机都在跑也没关系：构建前 `git pull --rebase`，push 撞车自动重试；空转 0.5 秒。

**频率原则（2026-09-16 王彪定）**：不做分钟级轮询——一天几次固定时间 + 开机补跑就够，想立刻生效手动跑一次。

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

launchd：登录时跑一次 + 每天 09:30 / 13:30 / 18:30 / 22:30（用户级；`RunAtLoad` 就是开机补跑）：

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
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Hour</key><integer>22</integer><key>Minute</key><integer>30</integer></dict>
  </array>
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

计划任务 `media-digest-build`：**登录后 3 分钟 + 每天 09:30 / 13:30 / 18:30 / 22:30**（StartWhenAvailable：关机错过的开机补跑）。Action **直接用 `pythonw.exe scraper\build.py --quiet`**（无控制台 Python），且 `build.py` 起子进程时带 `CREATE_NO_WINDOW`——两层都要，否则 git / py 子进程会各弹一个黑窗。查看 `schtasks /query /tn media-digest-build`；手动检查用双击 `run_build.bat`（会留窗显示结果）。

重建任务（PowerShell）：

```powershell
$a = New-ScheduledTaskAction -Execute "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe" -Argument 'scraper\build.py --quiet' -WorkingDirectory 'E:\claude_project\media-digest'
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"; $logon.Delay = 'PT3M'
$daily = @('09:30','13:30','18:30','22:30') | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName media-digest-build -Action $a -Trigger (@($logon) + $daily) -Settings $s -Force
```
