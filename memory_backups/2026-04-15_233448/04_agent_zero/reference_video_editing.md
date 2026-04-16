---
name: Video Editing Workflow (Mac Mini)
description: meta_video_editor.py + video_config.yaml pipeline — AirDrop clips, edit YAML, run script, finished video lands on Desktop
type: reference
---

### Pipeline
All edits controlled via `~/video_config.yaml`. Script: `~/meta_video_editor.py`.

### Steps
1. **AirDrop clips** from iPhone → Mac mini Downloads
2. **Edit config:** `nano ~/video_config.yaml`
3. **Fill in clips + music:**
   ```yaml
   clips:
     - IMG_1071.MOV
     - IMG_1074.MOV

   music:
     - file: drake.mp3
       start: 0
       end: 30
       fade_in: 1.5
       fade_out: 2.0
       volume: 0.8
       replace_audio: false
   ```
4. **Run:** `python3 ~/meta_video_editor.py ~/video_config.yaml`
5. **Finished video appears on Desktop**

Only things that change per run: clip names, song names, timestamps.

### Styled Outputs
Every run produces the clean master. Styled versions render only when `enabled: true`.

```yaml
- name: reels_cinematic
  enabled: true
  aspect: "9:16"
  style: cinematic_warm
```

Output files on Desktop:
- `my_video_01_master.mp4` — raw, no styling
- `my_video_01_reels_cinematic.mp4` — vertical warm grade

**Style options:** `none` / `cinematic_warm` / `cinematic_cool` / `vivid` / `bw`
**Aspect options:** `original` / `16:9` / `9:16` / `1:1` / `4:3`

### Music Library
See `reference_music_library.md` — 34 tracks in `~/Music/`, referenced by filename under the `music:` list.
