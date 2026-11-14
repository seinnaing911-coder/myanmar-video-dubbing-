import asyncio
import hmac
import os
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
    expected = str(st.secrets.get("APP_PASSWORD", os.getenv("APP_PASSWORD", ""))).strip()
    if not expected:
        st.error("APP_PASSWORD မသတ်မှတ်ရသေးပါ။ Streamlit Secrets ထဲတွင် APP_PASSWORD ထည့်ပါ။")
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
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error")[-5000:]
        raise RuntimeError(f"{label} မအောင်မြင်ပါ။\n{detail}")
    return result.stdout.strip()


def get_media_duration(path: str) -> float:
    output = run_command(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        "Media duration စစ်ဆေးခြင်း",
    )
    try:
        duration = float(output)
    except ValueError as exc:
        raise RuntimeError("ဗီဒီယိုကြာချိန်ကို မဖတ်နိုင်ပါ။") from exc
    if duration <= 0:
        raise RuntimeError("ဗီဒီယိုကြာချိန် မမှန်ပါ။")
    return duration


async def create_tts(text: str, destination: str) -> None:
    communicator = edge_tts.Communicate(text=text, voice=VOICE)
    await communicator.save(destination)


def srt_time_to_seconds(t) -> float:
    return t.hours * 3600 + t.minutes * 60 + t.seconds + t.milliseconds / 1000.0


def make_video_piece(source_video: str, start: float, source_length: float,
                     output_length: float, output_path: str):
    """Retimes VIDEO only. Speech audio is never sped up or slowed down."""
    if source_length <= 0.02 or output_length <= 0.02:
        raise RuntimeError("Video အပိုင်းကြာချိန် အလွန်တိုနေပါသည်။")
    # setpts multiplier: target duration / source duration
    pts_factor = output_length / source_length
    run_command(
        [
            "ffmpeg", "-y", "-ss", f"{start:.6f}", "-i", source_video,
            "-t", f"{source_length:.6f}", "-an",
            "-vf", f"setpts={pts_factor:.9f}*(PTS-STARTPTS),fps=30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
            output_path,
        ],
        "Video အပိုင်းအမြန်နှုန်းညှိခြင်း",
    )


def make_dubbed_timeline(video_path: str, srt_path: str, work_dir: str, progress):
    video_duration = get_media_duration(video_path)
    subtitles = pysrt.open(srt_path, encoding="utf-8")
    if not subtitles:
        raise RuntimeError("SRT ဖိုင်ထဲတွင် စာတန်း မတွေ့ပါ။")

    valid = []
    for sub in subtitles:
        line = " ".join(sub.text.replace("\ufeff", "").split()).strip()
        start = max(0.0, srt_time_to_seconds(sub.start))
        end = min(video_duration, srt_time_to_seconds(sub.end))
        if line and end - start > 0.03:
            valid.append((line, start, end))
    valid.sort(key=lambda item: (item[1], item[2]))
    if not valid:
        raise RuntimeError("အသုံးပြုနိုင်တဲ့ SRT စာကြောင်း မတွေ့ပါ။")

    async def generate_all():
        paths = []
        for i, (line, _, _) in enumerate(valid, start=1):
            audio_path = os.path.join(work_dir, f"speech_{i:05d}.mp3")
            await create_tts(line, audio_path)
            paths.append(audio_path)
            progress(i / len(valid), f"မြန်မာအသံ ထုတ်နေပါသည် ({i}/{len(valid)})")
        return paths

    speech_paths = asyncio.run(generate_all())

    video_pieces = []
    audio_timeline = AudioSegment.empty().set_frame_rate(24000).set_channels(1)
    source_cursor = 0.0
    used_count = 0

    for i, ((line, raw_start, end), speech_path) in enumerate(zip(valid, speech_paths), start=1):
        start = max(raw_start, source_cursor)
        if end <= start + 0.03:
            continue

        # Keep the silent gap at normal video speed and preserve matching audio silence.
        if start > source_cursor + 0.02:
            gap = start - source_cursor
            gap_path = os.path.join(work_dir, f"video_gap_{i:05d}.mp4")
            make_video_piece(video_path, source_cursor, gap, gap, gap_path)
            video_pieces.append(gap_path)
            audio_timeline += AudioSegment.silent(
                duration=int(gap * 1000), frame_rate=24000
            ).set_channels(1)

        speech = AudioSegment.from_file(speech_path, format="mp3")
        speech = speech.set_channels(1).set_frame_rate(24000)
        speech_duration = len(speech) / 1000.0
        source_duration = end - start

        # Fit the picture to the NATURAL speech duration. Do not alter speech speed.
        speech_video_path = os.path.join(work_dir, f"video_speech_{i:05d}.mp4")
        make_video_piece(
            video_path, start, source_duration, speech_duration, speech_video_path
        )
        video_pieces.append(speech_video_path)
        audio_timeline += speech
        source_cursor = end
        used_count += 1

    if source_cursor < video_duration - 0.02:
        tail = video_duration - source_cursor
        tail_path = os.path.join(work_dir, "video_tail.mp4")
        make_video_piece(video_path, source_cursor, tail, tail, tail_path)
        video_pieces.append(tail_path)
        audio_timeline += AudioSegment.silent(
            duration=int(tail * 1000), frame_rate=24000
        ).set_channels(1)

    if not video_pieces or used_count == 0:
        raise RuntimeError("အသုံးပြုနိုင်တဲ့ စာတန်း/အသံ မတွေ့ပါ။")

    # Re-encode-compatible MP4 pieces are joined in timeline order.
    concat_file = os.path.join(work_dir, "video_concat.txt")
    with open(concat_file, "w", encoding="utf-8") as f:
        for piece in video_pieces:
            escaped = piece.replace("'", r"'\''")
            f.write(f"file '{escaped}'\n")

    joined_video = os.path.join(work_dir, "joined_video.mp4")
    run_command(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
         "-c", "copy", "-an", "-movflags", "+faststart", joined_video],
        "Video အပိုင်းများ ပေါင်းစပ်ခြင်း",
    )

    mp3_output = os.path.join(work_dir, "dubbed_audio.mp3")
    audio_timeline.export(mp3_output, format="mp3", bitrate="192k")
    output_duration = len(audio_timeline) / 1000.0
    return joined_video, mp3_output, output_duration, used_count


def mux_video(video_path: str, audio_path: str, output_path: str, duration: float):
    run_command(
        [
            "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{duration:.3f}", "-movflags", "+faststart", output_path,
        ],
        "Final MP4 ထုတ်လုပ်ခြင်း",
    )


check_login()

st.title("🎬 Myanmar Video Dubbing Studio")
st.caption("Thiha Neural မြန်မာအသံကို ပုံမှန်အမြန်နှုန်းထားပြီး Video အပိုင်းကိုသာ အချိန်ညှိပေးပါသည်။")

with st.sidebar:
    st.subheader("အသံဆက်တင်")
    st.info(f"Voice: {VOICE}")
    st.caption(f"Upload ကန့်သတ်ချက်: {MAX_UPLOAD_MB} MB / ဖိုင်")
    if st.button("Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

video_file = st.file_uploader("၁။ မူရင်းဗီဒီယို Upload လုပ်ပါ",
                              type=["mp4", "mov", "mkv"])
srt_file = st.file_uploader("၂။ မြန်မာဘာသာပြန်ပြီးသား SRT Upload လုပ်ပါ",
                            type=["srt"])

st.info(
    "အသံကို အမြန်/အနှေး မပြောင်းပါ။ စာတန်းတစ်ကြောင်း၏ အသံကြာချိန်နှင့် "
    "ကိုက်ညီစေရန် သက်ဆိုင်ရာ Video အပိုင်းကိုသာ အနှေး/အမြန် ပြောင်းပါမည်။ "
    "ထို့ကြောင့် Output Video ကြာချိန်သည် မူရင်းထက် ပြောင်းလဲနိုင်ပါသည်။"
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
                video_path = os.path.join(
                    work_dir, "source_video" + Path(video_file.name).suffix.lower()
                )
                srt_path = os.path.join(work_dir, "source_subtitle.srt")
                mp4_output = os.path.join(work_dir, "final_output.mp4")

                with open(video_path, "wb") as f:
                    f.write(video_file.getbuffer())
                with open(srt_path, "wb") as f:
                    f.write(srt_file.getbuffer())

                status.info("ဗီဒီယိုနှင့် SRT ကို စစ်ဆေးနေပါသည်...")
                bar.progress(5)

                def update_tts(value, message):
                    bar.progress(min(65, 5 + int(value * 60)))
                    status.info(message)

                joined_video, audio_path, duration, count = make_dubbed_timeline(
                    video_path, srt_path, work_dir, update_tts
                )
                status.info("မြန်မာအသံနှင့် Video ကို ပေါင်းစပ်နေပါသည်...")
                bar.progress(85)
                mux_video(joined_video, audio_path, mp4_output, duration)
                bar.progress(100)
                status.success(
                    f"ပြီးပါပြီ။ စာတန်း {count} ကြောင်းကို ပုံမှန်အသံအမြန်နှုန်းဖြင့် ထုတ်ပြီးပါပြီ။"
                )

                st.session_state["result_mp4"] = Path(mp4_output).read_bytes()
                st.session_state["result_mp3"] = Path(audio_path).read_bytes()
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
        st.download_button("⬇️ Download MP4 Video",
                           data=st.session_state["result_mp4"],
                           file_name=f"{base}_myanmar_dub.mp4",
                           mime="video/mp4", use_container_width=True)
    with col2:
        st.download_button("⬇️ Download MP3 Audio",
                           data=st.session_state["result_mp3"],
                           file_name=f"{base}_myanmar_dub.mp3",
                           mime="audio/mpeg", use_container_width=True)

st.divider()
st.caption("ဖိုင်များကို ယာယီဖိုလ်ဒါတွင်သာ Process လုပ်ပြီး ပြီးဆုံးပါက ဖျက်ပစ်ပါသည်။")
