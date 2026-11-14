import asyncio
import hashlib
import hmac
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import edge_tts
import pysrt
import streamlit as st
from pydub import AudioSegment

st.set_page_config(
    page_title="Myanmar Video Dubbing Studio",
    page_icon="🎬",
    layout="centered",
)

VOICE = "my-MM-ThihaNeural"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))


def check_login() -> bool:
    """Simple single-password gate. Set APP_PASSWORD in Streamlit Secrets."""
    expected = str(st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", ""))).strip()
    if not expected:
        st.error(
            "APP_PASSWORD မသတ်မှတ်ရသေးပါ။ "
            "Streamlit Secrets ထဲတွင် APP_PASSWORD ထည့်ပါ။"
        )
        st.stop()

    if st.session_state.get("authenticated", False):
        return True

    st.title("🔐 Private Dubbing Studio")
    st.caption("ကိုယ်ပိုင်အသုံးပြုရန် Password ဖြင့် ဝင်ပါ။")
    with st.form("login_form"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if submitted:
        if hmac.compare_digest(password, expected):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Password မှားနေပါတယ်။ ထပ်စမ်းကြည့်ပါ။")
    st.stop()


def run_command(command: list[str], label: str) -> str:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error")[-5000:]
        raise RuntimeError(f"{label} မအောင်မြင်ပါ။\n{detail}")
    return result.stdout.strip()


def get_media_duration(path: str) -> float:
    output = run_command(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        "Media duration စစ်ဆေးခြင်း",
    )
    try:
        duration = float(output)
    except ValueError as exc:
        raise RuntimeError("ဗီဒီယိုကြာချိန်ကို မဖတ်နိုင်ပါ။") from exc
    if duration <= 0:
        raise RuntimeError("ဗီဒီယိုကြာချိန် မမှန်ပါ။")
    return duration


def atempo_filter(speed: float) -> str:
    """Build FFmpeg atempo chain; speed > 1 makes speech faster."""
    factors = []
    while speed > 2.0:
        factors.append(2.0)
        speed /= 2.0
    while speed < 0.5:
        factors.append(0.5)
        speed /= 0.5
    factors.append(speed)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


async def create_tts(text: str, destination: str) -> None:
    communicator = edge_tts.Communicate(text=text, voice=VOICE)
    await communicator.save(destination)


def srt_time_to_seconds(t) -> float:
    return (
        t.hours * 3600
        + t.minutes * 60
        + t.seconds
        + t.milliseconds / 1000.0
    )


def make_dub_audio(video_path: str, srt_path: str, work_dir: str, progress):
    video_duration = get_media_duration(video_path)
    subtitles = pysrt.open(srt_path, encoding="utf-8")
    if not subtitles:
        raise RuntimeError("SRT ဖိုင်ထဲတွင် စာတန်းမတွေ့ပါ။")

    timeline = AudioSegment.silent(
        duration=int(video_duration * 1000),
        frame_rate=24000,
    ).set_channels(1)

    valid = []
    for sub in subtitles:
        line = " ".join(sub.text.replace("\ufeff", "").split()).strip()
        start = max(0.0, srt_time_to_seconds(sub.start))
        end = min(video_duration, srt_time_to_seconds(sub.end))
        if line and end > start:
            valid.append((sub.index, line, start, end))

    if not valid:
        raise RuntimeError("အသုံးပြုနိုင်တဲ့ SRT စာကြောင်း မတွေ့ပါ။")

    async def generate_all():
        results = []
        total = len(valid)
        for count, (index, line, start, end) in enumerate(valid, start=1):
            mp3_path = os.path.join(work_dir, f"tts_{count:05d}.mp3")
            await create_tts(line, mp3_path)
            results.append((mp3_path, start, end))
            progress(count / total, f"မြန်မာအသံ ထုတ်နေပါသည် ({count}/{total})")
        return results

    generated = asyncio.run(generate_all())

    for count, (audio_path, start, end) in enumerate(generated, start=1):
        slot_seconds = end - start
        slot_ms = max(1, int(slot_seconds * 1000))
        clip = AudioSegment.from_file(audio_path, format="mp3")
        clip = clip.set_channels(1).set_frame_rate(24000)

        # စကားသံက subtitle အချိန်ထက်ရှည်လျှင် pitch မပြောင်းဘဲ အမြန်နှုန်းမြှင့်ပါ။
        if len(clip) > slot_ms:
            speed = len(clip) / slot_ms
            fitted_path = os.path.join(work_dir, f"fit_{count:05d}.mp3")
            run_command(
                [
                    "ffmpeg", "-y", "-i", audio_path,
                    "-vn", "-af", atempo_filter(speed),
                    "-codec:a", "libmp3lame", "-q:a", "3",
                    fitted_path,
                ],
                "အသံအချိန်ညှိခြင်း",
            )
            clip = AudioSegment.from_file(fitted_path, format="mp3")
            clip = clip.set_channels(1).set_frame_rate(24000)

        # Video timeline အပြင်ဘက်သို့ အသံမကျော်စေရန် ဖြတ်တောက်ပါ။
        clip = clip[:slot_ms]
        timeline = timeline.overlay(clip, position=int(start * 1000))

    mp3_output = os.path.join(work_dir, "dubbed_audio.mp3")
    timeline.export(mp3_output, format="mp3", bitrate="192k")
    return mp3_output, video_duration, len(valid)


def mux_video(video_path: str, audio_path: str, output_path: str, duration: float):
    # Re-encode video to H.264 for broad MP4 compatibility; original audio is replaced.
    run_command(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{duration:.3f}",
            "-movflags", "+faststart",
            "-shortest",
            output_path,
        ],
        "Final MP4 ထုတ်လုပ်ခြင်း",
    )


check_login()

st.title("🎬 Myanmar Video Dubbing Studio")
st.caption("မြန်မာ Thiha Neural အသံဖြင့် SRT အချိန်အတိုင်း Video Dubbing ပြုလုပ်ပါ။")

with st.sidebar:
    st.subheader("အသံဆက်တင်")
    st.info(f"Voice: {VOICE}")
    st.caption(f"Upload ကန့်သတ်ချက်: {MAX_UPLOAD_MB} MB / ဖိုင်")
    if st.button("Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

video_file = st.file_uploader(
    "၁။ မူရင်းဗီဒီယို Upload လုပ်ပါ",
    type=["mp4", "mov", "mkv"],
    help="MP4 ကို အကြံပြုပါတယ်။",
)
srt_file = st.file_uploader(
    "၂။ မြန်မာဘာသာပြန်ပြီးသား SRT Upload လုပ်ပါ",
    type=["srt"],
)

st.warning(
    "မှတ်ချက် - Dubbing ပြုလုပ်ရာတွင် မူရင်းဗီဒီယိုအသံကို အစားထိုးပြီး "
    "မြန်မာအသံကို ထည့်ပေးပါမည်။ Subtitle မရှိသောအချိန်များတွင် တိတ်ဆိတ်နေပါမည်။"
)

if video_file and srt_file:
    video_mb = video_file.size / (1024 * 1024)
    srt_mb = srt_file.size / (1024 * 1024)
    st.write(f"Video: **{video_file.name}** ({video_mb:.1f} MB)")
    st.write(f"SRT: **{srt_file.name}** ({srt_mb:.2f} MB)")

    if video_mb > MAX_UPLOAD_MB or srt_mb > MAX_UPLOAD_MB:
        st.error(f"ဖိုင်တစ်ဖိုင်ချင်းစီသည် {MAX_UPLOAD_MB} MB ထက် မကြီးရပါ။")
    elif st.button("🚀 START DUBBING", type="primary", use_container_width=True):
        status = st.empty()
        bar = st.progress(0)
        try:
            with tempfile.TemporaryDirectory(prefix="myanmar_dub_") as work_dir:
                video_path = os.path.join(work_dir, "source_video" + Path(video_file.name).suffix.lower())
                srt_path = os.path.join(work_dir, "source_subtitle.srt")
                mp4_output = os.path.join(work_dir, "final_output.mp4")

                with open(video_path, "wb") as f:
                    f.write(video_file.getbuffer())
                with open(srt_path, "wb") as f:
                    f.write(srt_file.getbuffer())

                status.info("ဗီဒီယိုနှင့် SRT ကို စစ်ဆေးနေပါသည်...")
                bar.progress(5)

                def update_tts(value, message):
                    bar.progress(min(75, 5 + int(value * 70)))
                    status.info(message)

                audio_path, duration, subtitle_count = make_dub_audio(
                    video_path, srt_path, work_dir, update_tts
                )

                status.info("မြန်မာအသံကို ဗီဒီယိုနှင့် ပေါင်းစပ်နေပါသည်...")
                bar.progress(80)
                mux_video(video_path, audio_path, mp4_output, duration)
                bar.progress(100)
                status.success(f"ပြီးပါပြီ။ စာတန်း {subtitle_count} ကြောင်းကို အသံထုတ်ပြီးပါပြီ။")

                with open(mp4_output, "rb") as f:
                    mp4_bytes = f.read()
                with open(audio_path, "rb") as f:
                    mp3_bytes = f.read()

                st.session_state["result_mp4"] = mp4_bytes
                st.session_state["result_mp3"] = mp3_bytes
                st.session_state["result_name"] = Path(video_file.name).stem
                st.session_state["result_duration"] = duration

        except Exception as exc:
            st.error("လုပ်ဆောင်မှု မအောင်မြင်ပါ။")
            st.exception(exc)

if st.session_state.get("result_mp4") and st.session_state.get("result_mp3"):
    st.divider()
    st.subheader("✅ ရလဒ်များ")
    st.video(st.session_state["result_mp4"])
    st.audio(st.session_state["result_mp3"], format="audio/mp3")

    base = st.session_state.get("result_name", "dubbed_video")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "⬇️ Download MP4 Video",
            data=st.session_state["result_mp4"],
            file_name=f"{base}_myanmar_dub.mp4",
            mime="video/mp4",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "⬇️ Download MP3 Audio",
            data=st.session_state["result_mp3"],
            file_name=f"{base}_myanmar_dub.mp3",
            mime="audio/mpeg",
            use_container_width=True,
        )

st.divider()
st.caption("သင့်ဖိုင်များကို server ၏ ယာယီဖိုလ်ဒါတွင်သာ process လုပ်ပြီး job ပြီးဆုံးလျှင် ယာယီဖိုင်များကို ဖျက်ပစ်ပါသည်။")
