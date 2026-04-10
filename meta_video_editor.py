#!/usr/bin/env python3
"""
Meta Glasses Video Editor
Splices MOV clips and adds music tracks with fade/mix control.
Usage: python3 meta_video_editor.py config.yaml
"""

import subprocess
import sys
import os
import yaml
import tempfile
import shutil


def check_ffmpeg():
    if shutil.which("ffmpeg") is None:
        print("ERROR: ffmpeg not installed. Run: brew install ffmpeg")
        sys.exit(1)


def build_filter_complex(clips, music_tracks, total_duration):
    """Build ffmpeg filter_complex string for concat + audio mixing."""
    filter_parts = []
    inputs = []

    # Input index tracking
    clip_count = len(clips)
    music_count = len(music_tracks)

    # --- Normalize all clips to same resolution/fps ---
    for i in range(clip_count):
        filter_parts.append(
            f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
            f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v{i}];"
        )
        filter_parts.append(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}];")

    # --- Concat video + original audio ---
    v_inputs = "".join(f"[v{i}]" for i in range(clip_count))
    a_inputs = "".join(f"[a{i}]" for i in range(clip_count))
    filter_parts.append(f"{v_inputs}concat=n={clip_count}:v=1:a=0[vout];")
    filter_parts.append(f"{a_inputs}concat=n={clip_count}:v=0:a=1[orig_audio];")

    # --- Process each music track ---
    music_streams = []
    for i, track in enumerate(music_tracks):
        idx = clip_count + i  # ffmpeg input index for this music file
        start = track.get("start", 0)
        end = track.get("end", total_duration)
        fade_in = track.get("fade_in", 1.0)
        fade_out = track.get("fade_out", 1.0)
        hard_cut = track.get("hard_cut", False)
        volume = track.get("volume", 0.8)  # 0.0 - 1.0

        duration = end - start

        # Trim music to desired length
        filter_parts.append(
            f"[{idx}:a]atrim=0:{duration},asetpts=PTS-STARTPTS[m{i}_trim];"
        )

        # Apply fade in/out or hard cut
        if hard_cut:
            filter_parts.append(f"[m{i}_trim]volume={volume}[m{i}_vol];")
        else:
            fade_filter = f"afade=t=in:st=0:d={fade_in},afade=t=out:st={max(0, duration - fade_out)}:d={fade_out}"
            filter_parts.append(f"[m{i}_trim]{fade_filter},volume={volume}[m{i}_vol];")

        # Delay music to start at the right time in the video
        filter_parts.append(
            f"[m{i}_vol]adelay={int(start * 1000)}|{int(start * 1000)}[m{i}_delayed];"
        )
        music_streams.append(f"[m{i}_delayed]")

    # --- Mix original audio with music ---
    if music_streams:
        replace_audio = any(t.get("replace_audio", False) for t in music_tracks)
        if replace_audio:
            # Use only music, drop original audio
            if len(music_streams) == 1:
                filter_parts.append(f"{music_streams[0]}anull[aout]")
            else:
                music_concat = "".join(music_streams)
                filter_parts.append(
                    f"{music_concat}amix=inputs={len(music_streams)}:duration=longest[aout]"
                )
        else:
            # Mix music under original audio
            all_audio = "[orig_audio]" + "".join(music_streams)
            filter_parts.append(
                f"{all_audio}amix=inputs={1 + len(music_streams)}:duration=longest[aout]"
            )
    else:
        filter_parts.append("[orig_audio]anull[aout]")

    return "".join(filter_parts)


def get_clip_duration(filepath):
    """Get duration of a video clip in seconds."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", filepath],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def edit_video(config_path):
    check_ffmpeg()

    with open(config_path) as f:
        config = yaml.safe_load(f)

    clips = config.get("clips", [])
    music_tracks = config.get("music", [])
    output = config.get("output", "final_video.mp4")
    clips_dir = config.get("clips_dir", os.path.expanduser("~/Downloads"))
    music_dir = config.get("music_dir", os.path.expanduser("~/Music"))

    if not clips:
        print("ERROR: No clips specified in config.")
        sys.exit(1)

    # Resolve full paths
    clip_paths = []
    for clip in clips:
        path = clip if os.path.isabs(clip) else os.path.join(clips_dir, clip)
        if not os.path.exists(path):
            print(f"ERROR: Clip not found: {path}")
            sys.exit(1)
        clip_paths.append(path)

    music_paths = []
    for track in music_tracks:
        path = track["file"] if os.path.isabs(track["file"]) else os.path.join(music_dir, track["file"])
        if not os.path.exists(path):
            print(f"ERROR: Music file not found: {path}")
            sys.exit(1)
        music_paths.append(path)

    # Calculate total duration
    total_duration = sum(get_clip_duration(p) for p in clip_paths)
    print(f"Total video duration: {total_duration:.1f}s ({total_duration/60:.1f} min)")

    # Build ffmpeg command
    cmd = ["ffmpeg", "-y"]

    # Add clip inputs
    for path in clip_paths:
        cmd += ["-i", path]

    # Add music inputs
    for path in music_paths:
        cmd += ["-i", path]

    # Build filter complex
    filter_complex = build_filter_complex(clips, music_tracks, total_duration)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "h264_videotoolbox",  # Apple hardware encoder (fast on M4)
        "-b:v", "8M",
        "-c:a", "aac",
        "-b:a", "192k",
        output
    ]

    print(f"\nRendering to {output}...")
    print("Press Ctrl+C to cancel.\n")

    result = subprocess.run(cmd, text=True)

    if result.returncode == 0:
        size = os.path.getsize(output) / (1024 * 1024)
        print(f"\nDone. Output: {output} ({size:.1f} MB)")
    else:
        # Fallback to software encoder if hardware fails
        print("Hardware encoder failed, trying software encoder...")
        cmd = [c if c != "h264_videotoolbox" else "libx264" for c in cmd]
        subprocess.run(cmd)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 meta_video_editor.py config.yaml")
        sys.exit(1)
    edit_video(sys.argv[1])
