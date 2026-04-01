---
name: music-player
description: "当用户说「播放某某歌曲」时，在客户端设备上播放本地 MP3 文件。"
---

# Music Player Skill

当用户说"播放某某歌曲"时，在客户端设备上播放 `mp3/` 目录下的 MP3 文件。

## 触发条件

当用户说以下类似的话时，调用 `music_player_play` tool：
- "播放七里香"
- "我想听晴天"
- "放一首稻香"
- "播放音乐"

## 使用方法

调用 `music_player_play` tool，传入 `song_name` 参数（歌曲名称，支持模糊匹配）：

```
song_name: "七里香"  ← 用户说的歌曲名（可以是部分名称）
```

Tool 会自动：
1. 在 `mp3/` 目录下搜索匹配的文件（模糊匹配）
2. 在客户端设备上开始播放

## MP3 文件存放位置

将 MP3 文件放到以下目录：
```
nanobot/skills/music-player/mp3/
```

文件名即歌曲名，例如：
- `mp3/七里香.mp3`
- `mp3/晴天.mp3`
- `mp3/周杰伦-稻香.mp3`

## 返回结果

Tool 返回 `🎵 正在播放：{歌曲名}`，同时客户端开始播放音频。
