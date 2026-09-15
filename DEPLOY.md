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

计划任务 `media-digest-build`：每 1 分钟调 `run_build.bat task`。查看 `schtasks /query /tn media-digest-build`；手动 `run_build.bat`（双击）。
