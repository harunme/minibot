# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## 音乐播放

当用户请求播放歌曲时，调用 `play_music(song_name="歌曲名")` 工具。
Channel 在 TTS 播放完毕后自动搜索 `~/.nanobot/workspace/mp3/` 目录下的 MP3 文件并推送 PCM 流到客户端。

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Reminders

- Please refer to cron skill for usage.
