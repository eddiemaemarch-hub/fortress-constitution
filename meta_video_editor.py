#!/usr/bin/env python3
"""
Meta Glasses Video Editor
Splices MOV clips, adds music, and renders optional styled versions.
Usage: python3 meta_video_editor.py config.yaml
"""

import subprocess
import sys
import os
import yaml
import shutil


def check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg not installed. Run: brew install ffmpeg")
        sys.exit(1)


def get_clip_duration(filepath):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", filepath],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


# ---------------------------------------------------------------------------
# Color grade presets — FFmpeg eq + curves filters
# ---------------------------------------------------------------------------
COLOR_PRESETS = {
    "none": "",
    "cinematic_warm": (
        "eq=contrast=1.1:saturation=1.15:brightness=-0.02,"
        "curves=r='0/0 0.5/0.55 1/1':g='0/0 0.5/0.5 1/0.95':b='0/0 0.5/0.45 1/0.85',"
        "vignette=PI/4"
    ),
    "cinematic_cool": (
        "eq=contrast=1.12:saturation=0.95:brightness=-0.03,"
        "curves=r='0/0 0.5/0.48 1/0.92':g='0/0 0.5/0.5 1/0.97':b='0/0 0.5/0.55 1/1.05',"
        "vignette=PI/4"
    ),
    "vivid": (
        "eq=contrast=1.05:saturation=1.4:brightness=0.01"
    ),
    "bw": (
        "hue=s=0,eq=contrast=1.15:brightness=-0.01"
    ),
}

# ---------------------------------------------------------------------------
# Aspect ratio crop — centered
# ---------------------------------------------------------------------------
ASPECT_CROPS = {
    "original": "",                                    # no crop
    "16:9":  "crop=iw:iw*9/16:(iw-iw)/2:(ih-iw*9/16)/2",
    "9:16":  "crop=ih*9/16:ih:(iw-ih*9/16)/2:0",      # vertical / Reels
    "1:1":   "crop=min(iw\\,ih):min(iw\\,ih):(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/2",
    "4:3":   "crop=ih*4/3:ih:(iw-ih*4/3)/2:0",
}


def build_video_filter(style, aspect, text_overlays, stabilize, clip_count, label):
    """Build the video filter chain for one output version."""
    parts = []

    # 1. Concat all clips
    v_inputs = "".join(f"[sv{label}{i}]" for i in range(clip_count))
    parts.append(f"{v_inputs}concat=n={clip_count}:v=1:a=0[concat_{label}];")

    chain = f"[concat_{label}]"

    # 2. Stabilize (deshake)
    if stabilize:
        chain_out = f"stab_{label}"
        parts.append(f"{chain}deshake[{chain_out}];")
        chain = f"[{chain_out}]"

    # 3. Aspect ratio crop
    crop = ASPECT_CROPS.get(aspect, "")
    if crop:
        chain_out = f"crop_{label}"
        parts.append(f"{chain}{crop}[{chain_out}];")
        chain = f"[{chain_out}]"

    # 4. Scale to output resolution
    chain_out = f"scale_{label}"
    parts.append(f"{chain}scale=1920:1080:force_original_aspect_ratio=decrease,"
                 f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1[{chain_out}];")
    chain = f"[{chain_out}]"

    # 5. Color grade
    grade = COLOR_PRESETS.get(style, "")
    if grade:
        chain_out = f"grade_{label}"
        parts.append(f"{chain}{grade}[{chain_out}];")
        chain = f"[{chain_out}]"

    # 6. Text overlays
    for j, overlay in enumerate(text_overlays):
        text = overlay["text"].replace("'", "\\'").replace(":", "\\:")
        start = overlay.get("start", 0)
        end = overlay.get("end", start + 3)
        pos = overlay.get("position", "bottom_center")
        fontsize = overlay.get("fontsize", 48)

        x_map = {"bottom_center": "(w-text_w)/2", "top_center": "(w-text_w)/2",
                 "bottom_left": "50", "bottom_right": "w-text_w-50"}
        y_map = {"bottom_center": "h-text_h-60", "top_center": "60",
                 "bottom_left": "h-text_h-60", "bottom_right": "h-text_h-60"}
        x = x_map.get(pos, "(w-text_w)/2")
        y = y_map.get(pos, "h-text_h-60")

        chain_out = f"text_{label}_{j}"
        parts.append(
            f"{chain}drawtext=text='{text}':fontsize={fontsize}:fontcolor=white:"
            f"x={x}:y={y}:enable='between(t,{start},{end})':"
            f"shadowcolor=black:shadowx=2:shadowy=2[{chain_out}];"
        )
        chain = f"[{chain_out}]"

    # Final video output label
    parts.append(f"{chain}null[vout_{label}]")
    return "".join(parts)


def build_filter_complex(clip_count, music_tracks, total_duration, versions):
    """Build complete filter_complex for all outputs."""
    parts = []

    # --- Normalize each clip (shared across all versions) ---
    for i in range(clip_count):
        parts.append(
            f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[norm_v{i}];"
        )
        parts.append(
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[norm_a{i}];"
        )

    # --- Split normalized video for each version ---
    for label, _ in versions:
        for i in range(clip_count):
            parts.append(f"[norm_v{i}]split=1[sv{label}{i}];")

    # --- Original audio concat ---
    a_inputs = "".join(f"[norm_a{i}]" for i in range(clip_count))
    parts.append(f"{a_inputs}concat=n={clip_count}:v=0:a=1[orig_audio];")

    # --- Build video filter for each version ---
    for label, ver_cfg in versions:
        style = ver_cfg.get("style", "none")
        aspect = ver_cfg.get("aspect", "original")
        text_overlays = ver_cfg.get("text_overlays", [])
        stabilize = ver_cfg.get("stabilize", False)
        vf = build_video_filter(style, aspect, text_overlays, stabilize, clip_count, label)
        parts.append(vf + ";")

    # --- Music tracks ---
    music_streams = []
    for i, track in enumerate(music_tracks):
        idx = clip_count + i
        start = track.get("start", 0)
        end = track.get("end", total_duration)
        fade_in = track.get("fade_in", 1.0)
        fade_out = track.get("fade_out", 1.0)
        hard_cut = track.get("hard_cut", False)
        volume = track.get("volume", 0.8)
        duration = end - start

        parts.append(f"[{idx}:a]atrim=0:{duration},asetpts=PTS-STARTPTS[m{i}_trim];")

        if hard_cut:
            parts.append(f"[m{i}_trim]volume={volume}[m{i}_vol];")
        else:
            fade_filter = (f"afade=t=in:st=0:d={fade_in},"
                           f"afade=t=out:st={max(0, duration - fade_out)}:d={fade_out}")
            parts.append(f"[m{i}_trim]{fade_filter},volume={volume}[m{i}_vol];")

        parts.append(f"[m{i}_vol]adelay={int(start*1000)}|{int(start*1000)}[m{i}_delayed];")
        music_streams.append(f"[m{i}_delayed]")

    # --- Mix audio ---
    if music_streams:
        replace_audio = any(t.get("replace_audio", False) for t in music_tracks)
        if replace_audio:
            all_music = "".join(music_streams)
            parts.append(f"{all_music}amix=inputs={len(music_streams)}:duration=longest[aout]")
        else:
            all_audio = "[orig_audio]" + "".join(music_streams)
            parts.append(
                f"{all_audio}amix=inputs={1+len(music_streams)}:duration=longest[aout]"
            )
    else:
        parts.append("[orig_audio]anull[aout]")

    return "".join(parts)


def render(cmd, output):
    print(f"\nRendering → {output}")
    result = subprocess.run(cmd, text=True)
    if result.returncode == 0:
        size = os.path.getsize(output) / (1024 * 1024)
        print(f"Done: {output} ({size:.1f} MB)")
        return True
    else:
        # Fallback: software encoder
        print("Hardware encoder failed, retrying with software encoder...")
        cmd = [c if c != "h264_videotoolbox" else "libx264" for c in cmd]
        result = subprocess.run(cmd, text=True)
        return result.returncode == 0


def edit_video(config_path):
    check_ffmpeg()

    with open(config_path) as f:
        config = yaml.safe_load(f)

    clips = config.get("clips", [])
    music_tracks = config.get("music", [])
    clips_dir = config.get("clips_dir", os.path.expanduser("~/Downloads"))
    music_dir = config.get("music_dir", os.path.expanduser("~/Music"))
    output_dir = config.get("output_dir", os.path.expanduser("~/Desktop"))
    project_name = config.get("project_name", "video")

    if not clips:
        print("ERROR: No clips specified.")
        sys.exit(1)

    # --- Resolve clip paths ---
    clip_paths = []
    for clip in clips:
        path = clip if os.path.isabs(clip) else os.path.join(clips_dir, clip)
        if not os.path.exists(path):
            print(f"ERROR: Clip not found: {path}")
            sys.exit(1)
        clip_paths.append(path)

    # --- Resolve music paths ---
    music_paths = []
    for track in music_tracks:
        path = track["file"] if os.path.isabs(track["file"]) else os.path.join(music_dir, track["file"])
        if not os.path.exists(path):
            print(f"ERROR: Music not found: {path}")
            sys.exit(1)
        music_paths.append(path)

    total_duration = sum(get_clip_duration(p) for p in clip_paths)
    print(f"Project: {project_name}")
    print(f"Clips: {len(clip_paths)} | Duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")

    # --- Collect output versions ---
    # Master (always rendered)
    master_cfg = config.get("master", {"style": "none", "aspect": "original"})
    versions = [("master", master_cfg)]

    # Styled versions (only if enabled: true)
    for ver in config.get("styled_versions", []):
        if ver.get("enabled", False):
            label = ver.get("name", "styled").replace(" ", "_").replace("-", "_")
            versions.append((label, ver))

    print(f"Versions to render: {[v[0] for v in versions]}")

    # --- Build filter complex ---
    filter_complex = build_filter_complex(
        len(clip_paths), music_tracks, total_duration, versions
    )

    # --- Render each version ---
    os.makedirs(output_dir, exist_ok=True)

    for label, ver_cfg in versions:
        out_file = os.path.join(output_dir, f"{project_name}_{label}.mp4")
        cmd = ["ffmpeg", "-y"]
        for p in clip_paths:
            cmd += ["-i", p]
        for p in music_paths:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex", filter_complex,
            "-map", f"[vout_{label}]",
            "-map", "[aout]",
            "-c:v", "h264_videotoolbox",
            "-b:v", "8M",
            "-c:a", "aac",
            "-b:a", "192k",
            out_file
        ]
        render(cmd, out_file)

    print(f"\nAll done. Files saved to: {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 meta_video_editor.py config.yaml")
        sys.exit(1)
    edit_video(sys.argv[1])
