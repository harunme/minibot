# Music Player Skill

## 音乐播放技能

当用户说"播放某某歌曲"时，自动返回对应的MP3文件。

## 使用方法

### 1. 添加歌曲

将你的MP3文件放到 `mp3/` 目录下，文件名就是歌曲名：

```bash
cp "path/to/你的歌曲.mp3" mp3/
```

例如：
```
mp3/七里香.mp3
mp3/晴天.mp3
mp3/稻香.mp3
```

### 2. 查询歌曲

```bash
# 列出所有歌曲
python3 scripts/music_player.py list

# 搜索歌曲
python3 scripts/music_player.py search "关键词"

# 获取歌曲完整路径（用于播放）
python3 scripts/music_player.py play "歌曲名"
```

## 在对话中使用

当用户说：
- "播放七里香"
- "我想听晴天"
- "播放一下稻香"

系统会自动搜索匹配的MP3文件并返回，供播放使用。
