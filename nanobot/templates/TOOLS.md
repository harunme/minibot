# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## 音乐播放

当用户请求播放歌曲时，在回复末尾添加 `<play>歌曲名</play>`。
Channel 在 TTS 播放完毕后自动识别标签，搜索 MP3 文件并推送 PCM 流到客户端。

歌曲存放目录：
- `~/.nanobot/workspace/mp3/`（用户歌曲）
- `nanobot/skills/music-player/mp3/`（内置歌曲）

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Reminders

- Please refer to cron skill for usage.
