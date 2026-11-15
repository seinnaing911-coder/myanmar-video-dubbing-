#!/usr/bin/env python3
"""Create a Burmese dubbed MP4 from an MP4 source and Burmese SRT subtitles.

This is an adapted, parameterized version of the pipeline supplied by the user.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import edge_tts
import pysrt

VOICE = "my-MM-ThihaNeural"


def run(command: list[str]) -> None:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-2000:] or "FFmpeg command failed")


def subtitle_seconds(item: pysrt.SubRipItem) -> tuple[float, float]:
    start = item.start.hours * 3600 + item.start.minutes * 60 + item.start.seconds + item.start.milliseconds / 1000
    end = item.end.hours * 3600 + item.end.minutes * 60 + item.end.seconds + item.end.milliseconds / 1000
    return start, end


async def generate_audio(subtitles: pysrt.SubRipFile, audio_dir: Path) -> None:
    for index, subtitle in enumerate(subtitles):
        text = subtitle.text.replace("\\n", " ").strip()
        if not text:
            continue
        audio_path = audio_dir / f"audio_{index}.mp3"
        communicator = edge_tts.Communicate(text, VOICE)
        await communicator.save(str(audio_path))


def audio_duration(audio_path: Path) -> float:
    result = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        text=True,
    ).strip()
    return float(result)


def process(video: Path, srt: Path, output: Path) -> None:
    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")
    if not srt.exists():
        raise FileNotFoundError(f"Subtitle not found: {srt}")

    subtitles = pysrt.open(str(srt), encoding="utf-8")
    if len(subtitles) == 0:
        raise ValueError("The SRT file does not contain any subtitle lines")

    work_dir = Path(tempfile.mkdtemp(prefix="dubwave-"))
    audio_dir = work_dir / "temp_audio"
    clip_dir = work_dir / "temp_clips"
    audio_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)

    try:
        asyncio.run(generate_audio(subtitles, audio_dir))
        processed_clips: list[Path] = []

        for index, subtitle in enumerate(subtitles):
            text = subtitle.text.replace("\\n", " ").strip()
            audio_path = audio_dir / f"audio_{index}.mp3"
            if not text or not audio_path.exists():
                continue

            start_sec, end_sec = subtitle_seconds(subtitle)
            duration = end_sec - start_sec
            if duration <= 0:
                continue

            clip_path = clip_dir / f"clip_{index}.mp4"
            run([
                "ffmpeg", "-y", "-ss", str(start_sec), "-i", str(video), "-t", str(duration),
                "-c:v", "libx264", "-c:a", "aac", str(clip_path),
            ])

            generated_duration = audio_duration(audio_path)
            if generated_duration <= 0:
                continue
            speed_factor = duration / generated_duration
            synced_path = clip_dir / f"synced_{index}.mp4"
            run([
                "ffmpeg", "-y", "-i", str(clip_path), "-i", str(audio_path),
                "-filter_complex", f"[0:v]setpts={1 / speed_factor}*PTS[v]",
                "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-c:a", "aac",
                "-shortest", str(synced_path),
            ])
            if synced_path.exists():
                processed_clips.append(synced_path)

        if not processed_clips:
            raise ValueError("No usable subtitle clips were produced")

        filelist = work_dir / "filelist.txt"
        filelist.write_text("".join(f"file '{clip.as_posix()}'\\n" for clip in processed_clips), encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(filelist), "-c", "copy", str(output)])
        if not output.exists() or output.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create the final output")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--srt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    process(args.video, args.srt, args.output)
    print(f"Created {args.output}")


if __name__ == "__main__":
    main()
