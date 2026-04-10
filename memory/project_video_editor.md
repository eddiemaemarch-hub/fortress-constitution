---
name: Meta Glasses Video Editor
description: FFmpeg-based video editor for Meta Ray-Ban MOV footage — splice clips, add music, cinematic styles
type: project
---

## Setup
- Script: `~/fortress-constitution/meta_video_editor.py`
- Config: `~/fortress-constitution/video_config.yaml`
- Footage: AirDrop MOV clips from iPhone → `~/Downloads`
- Music: `~/Music` (34 MP3s)
- Output: `~/Desktop`

## Run Command
```bash
python3 ~/fortress-constitution/meta_video_editor.py ~/fortress-constitution/video_config.yaml
```

## Workflow
1. Shoot on Meta Ray-Ban glasses
2. AirDrop clips from iPhone → Mac mini Downloads folder
3. Edit `video_config.yaml` — fill in clip names, music, timestamps
4. Run script → finished MP4 lands on Desktop

## Config Controls
- `clips` — list of MOV filenames in order
- `music` — tracks with start/end times, fade in/out, volume, replace_audio
- `master` — always renders, no styling (clean raw cut)
- `styled_versions` — optional versions, only render when `enabled: true`
- `style` — none / cinematic_warm / cinematic_cool / vivid / bw
- `aspect` — original / 16:9 / 9:16 / 1:1 / 4:3
- `stabilize` — deshake filter (true/false)
- `text_overlays` — text with position, timing, fontsize

## Music Library (34 MP3s in ~/Music)
- bally_baby_hustlin_mf.mp3
- bankroll_fresh_dirty_game.mp3
- black_sherif_kwaku_the_traveller.mp3
- bossman_dlow_motion_party.mp3
- bvsmp_i_need_you.mp3
- chris_brown_go_crazy.mp3
- creep_dog_instrumental.mp3
- creep_dog_instrumental_alt.mp3
- gmy_ville_sticky.mp3
- jam_pony_clear.mp3
- jam_pony_man_made.mp3
- justin_bieber_peaches.mp3
- mo3_everybody_aint_your_friend.mp3
- mo3_oh_yeah.mp3
- nba_youngboy_crossed_me.mp3
- pride_to_the_side_alt.mp3
- pride_to_the_side_yo_gotti.mp3
- r_kelly_ima_flirt.mp3
- r_kelly_story.mp3
- rick_ross_john_doe.mp3
- robin_thicke_magic.mp3
- standing_ovation_alt.mp3
- standing_ovation_young_jeezy.mp3
- ti_asap.mp3
- ti_live_your_life.mp3
- ti_motivation.mp3
- ti_war.mp3
- usher_superstar.mp3
- xscape_softest_place_on_earth.mp3
- yo_gotti_fuck_you.mp3
- young_dolph_preach.mp3
- young_jeezy_gangsta_music.mp3
- young_jock_i_know_you_see_it.mp3
- ytb_fatt_get_back.mp3

## Notes
- Meta glasses export format: MOV (H.264)
- Mac mini M4 uses hardware encoder (h264_videotoolbox) — fast renders
- ti_war.mp3 is ~1MB — may be a short/partial file, verify length before use
- Footage transfer: AirDrop only (Meta View app not available on Mac)
