import asyncio
import hmac
import os
import re
import subprocess
import tempfile
from pathlib import Path

import edge_tts
import streamlit as st
from pydub import AudioSegment


# ==============================
# Myanmar Auto Video Dubbing
# Timeline TXT + segment-by-segment video retiming
# ==============================

st.set_page_config(
    page_title="Myanmar Video Dubbing Studio",
    page_icon="🎬",
    layout="centered",
)

VOICES = {
    "Thiha (အမျိုးသားအသံ)": "my-MM-ThihaNeural",
    "Nilar (အမျိုးသမီးအသံ)": "my-MM-NilarNeural",
}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))


def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value or default).strip()


def check_login():
    expected = get_secret("APP_PASSWORD")
    if not expected:
        st.error("APP_PASSWORD မသတ်မှတ်ရသေးပါ။ Streamlit Secrets ထဲတွင် APP_PASSWORD ထည့်ပါ။")
        st.stop()

    if st.session_state.get("authenticated", False):
        return

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
            st.error("Password မှားနေပါတယ်။")
    st.stop()


def run_command(command, label):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error")[-3500:]
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
        "Video ကြာချိန်စစ်ဆေးခြင်း",
    )
    duration = float(output)
    if duration <= 0:
        raise RuntimeError("Video ကြာချိန်ကို မှန်ကန်စွာ မဖတ်နိုင်ပါ။")
    return duration


def parse_stamp(stamp: str) -> float:
    stamp = stamp.replace(",", ".")
    parts = stamp.split(":")
    nums = [float(x) for x in parts]
    if len(nums) == 2:
        minutes, seconds = nums
        return minutes * 60 + seconds
    if len(nums) == 3:
        hours, minutes, seconds = nums
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError("Timestamp ပုံစံမမှန်ပါ။")


def format_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def read_timeline_txt(txt_path: str, video_duration: float):
    raw = Path(txt_path).read_text(encoding="utf-8-sig", errors="replace")
    pattern = re.compile(
        r"^\s*\[(\d{1,3}:\d{1,2}(?::\d{1,2})?(?:[.,]\d{1,3})?)\]\s*(.*?)\s*$"
    )
    entries = []
    warnings = []

    for line_no, raw_line in enumerate(raw.replace("\r", "").split("\n"), 1):
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if not match:
            warnings.append(f"TXT စာကြောင်း {line_no}: [0:00] ပုံစံမဟုတ်သဖြင့် ကျော်ထားသည်။")
            continue
        stamp, text = match.groups()
        try:
            start = parse_stamp(stamp)
        except Exception:
            warnings.append(f"TXT စာကြောင်း {line_no}: အချိန်ကုဒ်ဖတ်မရပါ။")
            continue
        text = " ".join(text.split()).strip()
        if not text:
            warnings.append(f"TXT စာကြောင်း {line_no}: စာသားဗလာဖြစ်နေသည်။")
            continue
        if start < 0 or start >= video_duration:
            warnings.append(f"TXT စာကြောင်း {line_no}: Video အပြင်ဘက်အချိန်ဖြစ်သဖြင့် ကျော်ထားသည်။")
            continue
        entries.append((start, text))

    entries.sort(key=lambda item: item[0])

    merged = []
    for start, text in entries:
        if merged and abs(start - merged[-1][0]) < 0.001:
            merged[-1] = (start, merged[-1][1] + " " + text)
        else:
            merged.append((start, text))

    if not merged:
        raise RuntimeError("TXT ထဲတွင် အသုံးပြုနိုင်သော [0:00] Timeline နှင့် စာသား မတွေ့ပါ။")

    cues = []
    for i, (start, text) in enumerate(merged):
        end = merged[i + 1][0] if i + 1 < len(merged) else video_duration
        if end - start <= 0.03:
            warnings.append(f"{format_time(start)} အပိုင်းသည် အလွန်တိုနေသဖြင့် ကျော်ထားသည်။")
            continue
        cues.append({"start": start, "end": end, "text": text})

    if not cues:
        raise RuntimeError("အသုံးပြုနိုင်သော Timeline အပိုင်း မကျန်ပါ။")
    return cues, warnings


async def create_tts(text: str, output_path: str, voice: str):
    # Default speech rate: 10% faster than normal.
    communicator = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate="+10%",
    )
    await communicator.save(output_path)


def make_video_piece(
    source_video: str,
    start: float,
    source_length: float,
    output_length: float,
    output_path: str,
):
    if source_length <= 0.03 or output_length <= 0.03:
        raise RuntimeError("Video အပိုင်းကြာချိန် အလွန်တိုနေပါသည်။")

    pts_factor = output_length / source_length
    run_command(
        [
            "ffmpeg", "-y",
            "-ss", f"{start:.6f}",
            "-i", source_video,
            "-t", f"{source_length:.6f}",
            "-map", "0:v:0",
            "-an",
            "-vf", f"setpts={pts_factor:.9f}*(PTS-STARTPTS),fps=30",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path,
        ],
        "Video အပိုင်းအမြန်နှုန်းညှိခြင်း",
    )


def make_unchanged_piece(source_video, start, length, output_path):
    make_video_piece(source_video, start, length, length, output_path)


def build_dubbed_video(video_path, cues, work_dir, voice, progress):
    original_duration = get_media_duration(video_path)
    audio_parts = []
    video_parts = []
    warnings = []

    # Preserve the opening section before the first script timestamp.
    first_start = cues[0]["start"]
    if first_start > 0.03:
        opening_path = os.path.join(work_dir, "video_piece_000.mp4")
        make_unchanged_piece(video_path, 0.0, first_start, opening_path)
        video_parts.append(opening_path)
        audio_parts.append(
            AudioSegment.silent(duration=int(round(first_start * 1000)), frame_rate=24000)
            .set_channels(1)
        )

    for index, cue in enumerate(cues, start=1):
        source_start = cue["start"]
        source_end = cue["end"]
        source_length = source_end - source_start

        speech_path = os.path.join(work_dir, f"speech_{index:05d}.mp3")
        asyncio.run(create_tts(cue["text"], speech_path, voice))

        speech = AudioSegment.from_file(speech_path, format="mp3")
        speech = speech.set_channels(1).set_frame_rate(24000)
        speech_duration = len(speech) / 1000.0

        # Keep video speed within a practical range when speech is short.
        # If speech is longer than the source segment, extend the video segment
        # to the speech length so the next segment starts only after this line.
        minimum_output_length = source_length / 2.0  # maximum 2x speed-up
        output_length = max(speech_duration, minimum_output_length)

        if speech_duration > source_length * 2.0:
            warnings.append(
                f"{format_time(source_start)}: အသံသည် မူရင်း Video အပိုင်းထက် အလွန်ရှည်သဖြင့် "
                "Video ကို ၂ ဆထက်ပို၍ နှေးအောင်ညှိထားသည်။"
            )
        elif speech_duration < minimum_output_length - 0.03:
            warnings.append(
                f"{format_time(source_start)}: အသံတိုသောကြောင့် Video ကို အများဆုံး ၂ ဆသာ မြန်စေပြီး "
                "ကျန်အချိန်တွင် အသံတိတ်ထားသည်။"
            )

        piece_path = os.path.join(work_dir, f"video_piece_{index:05d}.mp4")
        make_video_piece(
            video_path,
            source_start,
            source_length,
            output_length,
            piece_path,
        )
        video_parts.append(piece_path)

        # Audio occupies the start of its corresponding retimed video segment.
        target_ms = int(round(output_length * 1000))
        if len(speech) < target_ms:
            speech += AudioSegment.silent(
                duration=target_ms - len(speech),
                frame_rate=24000,
            ).set_channels(1)
        elif len(speech) > target_ms:
            speech = speech[:target_ms]
        audio_parts.append(speech)

        progress(
            0.10 + 0.78 * (index / len(cues)),
            f"အပိုင်း {index}/{len(cues)} — အသံနှင့် Video ကို ညှိနေသည်",
        )

    # Join all video pieces in source order.
    concat_list = os.path.join(work_dir, "video_concat.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for path in video_parts:
            safe_path = os.path.abspath(path).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    joined_video = os.path.join(work_dir, "joined_video.mp4")
    run_command(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            "-movflags", "+faststart",
            joined_video,
        ],
        "Video အပိုင်းများပေါင်းစပ်ခြင်း",
    )

    # Join audio in the exact same order and duration as the video pieces.
    full_audio = AudioSegment.empty()
    for part in audio_parts:
        full_audio += part

    audio_output = os.path.join(work_dir, "dubbed_audio.mp3")
    full_audio.export(audio_output, format="mp3", bitrate="192k")

    output_duration = len(full_audio) / 1000.0
    final_output = os.path.join(work_dir, "myanmar_dubbed_video.mp4")
    run_command(
        [
            "ffmpeg", "-y",
            "-i", joined_video,
            "-i", audio_output,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{output_duration:.3f}",
            "-movflags", "+faststart",
            final_output,
        ],
        "နောက်ဆုံး MP4 ထုတ်လုပ်ခြင်း",
    )

    return final_output, output_duration, warnings


# ==============================
# User interface
# ==============================

check_login()

st.title("🎬 Myanmar Auto Video Dubbing")
st.caption("Video တစ်ခုနှင့် Timeline ပါသော မြန်မာ TXT Script တစ်ခုတင်ပြီး Dubbing ပြုလုပ်ပါ။")

with st.sidebar:
    st.subheader("အသံဆက်တင်")
    st.caption("မြန်မာအသံရွေးချယ်နိုင်ပါသည်။")
    st.caption(f"Upload ကန့်သတ်ချက်: {MAX_UPLOAD_MB} MB")
    st.caption("အသံနှုန်း: ပုံမှန်ထက် ၁၀% မြန်")
    if st.button("Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

voice_label = st.selectbox("🎙️ မြန်မာအသံရွေးချယ်ပါ", list(VOICES.keys()))
voice_name = VOICES[voice_label]

video_file = st.file_uploader(
    "မူရင်း Video တင်ပါ",
    type=["mp4", "mov", "mkv", "webm"],
)
txt_file = st.file_uploader(
    "မြန်မာ TXT Script တင်ပါ",
    type=["txt"],
)

with st.expander("TXT Script ရေးသားပုံ ဥပမာ", expanded=True):
    st.code(
        "[0:00] မင်္ဂလာပါ။ ဒီနေ့မှာ အကြောင်းအရာတစ်ခုကို ပြောပြပါမယ်။\n"
        "[0:06] အခု ဒီနေရာကို ကြည့်လိုက်ပါ။\n"
        "[0:13] နောက်တစ်ဆင့်ကို ဆက်သွားကြရအောင်။",
        language="text",
    )
    st.caption(
        "အချိန်ကုဒ်ကို [မိနစ်:စက္ကန့်] ပုံစံရေးပါ။ "
        "စာကြောင်းတစ်ကြောင်းစီ၏ အချိန်သည် အဲဒီအသံစမည့် မူရင်း Video အချိန်ဖြစ်သည်။"
    )

st.info(
    "လုပ်ဆောင်ပုံ — Script တစ်ကြောင်းချင်းအတွက် မြန်မာအသံဖန်တီးမည်။ "
    "သက်ဆိုင်ရာ မူရင်း Video အပိုင်းကိုလည်း ဖြတ်ပြီး အသံကြာချိန်နှင့် ကိုက်ညီအောင် "
    "အမြန်နှုန်းညှိမည်။ Video အပိုင်းများကို မူရင်းအစဉ်အတိုင်း ပြန်ပေါင်းမည်။"
)

if video_file is not None:
    video_mb = video_file.size / (1024 * 1024)
    st.write(f"Video: **{video_file.name}** ({video_mb:.1f} MB)")
if txt_file is not None:
    st.write(f"TXT: **{txt_file.name}**")

ready = video_file is not None and txt_file is not None
if not ready:
    st.warning("စတင်ရန် Video နဲ့ TXT Script နှစ်ခုလုံး တင်ပေးပါ။")

if video_file is not None and video_file.size > MAX_UPLOAD_MB * 1024 * 1024:
    st.error(f"Video ဖိုင်သည် {MAX_UPLOAD_MB} MB ထက် မကြီးရပါ။")
elif ready and st.button(
    "🚀 START AUTO DUBBING",
    type="primary",
    use_container_width=True,
):
    progress_bar = st.progress(0)
    status = st.empty()

    def update_progress(value, message):
        progress_bar.progress(max(0.0, min(1.0, float(value))))
        status.write(message)

    try:
        with tempfile.TemporaryDirectory(prefix="myanmar_dub_") as work_dir:
            video_path = os.path.join(
                work_dir,
                "source_video" + Path(video_file.name).suffix.lower(),
            )
            txt_path = os.path.join(work_dir, "burmese_script.txt")

            with open(video_path, "wb") as f:
                f.write(video_file.getbuffer())
            with open(txt_path, "wb") as f:
                f.write(txt_file.getbuffer())

            update_progress(0.03, "အဆင့် ၁ — Video ကြာချိန်နှင့် Timeline စစ်ဆေးနေသည်")
            duration = get_media_duration(video_path)
            cues, parse_warnings = read_timeline_txt(txt_path, duration)

            st.write(f"အသုံးပြုမည့် Script အပိုင်း: **{len(cues)} ပိုင်း**")
            for warning in parse_warnings:
                st.warning(warning)

            update_progress(0.08, "အဆင့် ၂ — မြန်မာအသံနှင့် Video အပိုင်းများ ဖန်တီးနေသည်")
            final_path, final_duration, timing_warnings = build_dubbed_video(
                video_path,
                cues,
                work_dir,
                voice_name,
                update_progress,
            )

            update_progress(0.96, "အဆင့် ၃ — နောက်ဆုံးဖိုင် ပြင်ဆင်နေသည်")
            with open(final_path, "rb") as f:
                output_bytes = f.read()

            st.success("Dubbing ပြီးပါပြီ။")
            st.video(output_bytes)
            st.download_button(
                "⬇️ မြန်မာအသံထည့်ပြီး Video ကို Download လုပ်ပါ",
                data=output_bytes,
                file_name="myanmar_dubbed_video.mp4",
                mime="video/mp4",
                use_container_width=True,
            )
            st.caption(f"နောက်ဆုံး Video ကြာချိန်: {final_duration:.1f} စက္ကန့်")

            for warning in timing_warnings:
                st.warning(warning)

            progress_bar.progress(1.0)
            status.write("ပြီးပါပြီ။")
    except Exception as exc:
        st.error("လုပ်ဆောင်ရာတွင် အမှားဖြစ်သွားပါသည်။")
        st.exception(exc)
