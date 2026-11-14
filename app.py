import asyncio
import hmac
import os
import re
import subprocess
import tempfile
import json
from pathlib import Path

from google import genai
from google.genai import types
from deep_translator import GoogleTranslator

import edge_tts
import pysrt
import streamlit as st
from pydub import AudioSegment

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


def get_gemini_key() -> str:
    try:
        value = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        value = ""
    return str(value or os.getenv("GEMINI_API_KEY", "")).strip()


def extract_audio(video_path: str, audio_path: str) -> None:
    run_command([
        "ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
        "-b:a", "64k", audio_path,
    ], "ဗီဒီယိုမှ အသံထုတ်ယူခြင်း")



def translate_to_burmese(text: str, client=None) -> tuple[str, str]:
    """Gemini ဖြင့် ဘာသာပြန်ရန်ကြိုးစားပြီး မရလျှင် Google Translate သုံးသည်။"""
    clean = text.strip()
    if not clean:
        return "", ""
    if client is not None:
        prompt = (
            "Translate the following spoken dialogue into natural, concise Burmese "
            "(Myanmar). Preserve names and meaning. Return only the Burmese translation.\n\n"
            + clean
        )
        last_error = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-3.8-flash", contents=[prompt]
                )
                result = (response.text or "").strip()
                result = re.sub(r"^```(?:text)?\s*|\s*```$", "", result).strip()
                if result:
                    return result, ""
                last_error = "Gemini မှ ဘာသာပြန်စာသား ဗလာပြန်လာသည်။"
            except Exception as exc:
                last_error = str(exc)
                if attempt < 2:
                    import time
                    time.sleep(2 ** attempt)
        # Gemini မရပါက အောက်က Google Translate ကို ဆက်သုံးပါ။
    try:
        result = GoogleTranslator(source="auto", target="my").translate(clean)
        if result and result.strip():
            note = "Gemini မရသဖြင့် Google Translate ကို အသုံးပြုထားသည်။" if client else ""
            return result.strip(), note
        raise RuntimeError("Google Translate မှ စာသားမရပါ။")
    except Exception as exc:
        detail = last_error if client else ""
        raise RuntimeError(
            "မြန်မာဘာသာပြန်မရပါ။ "
            + (f"Gemini: {detail}; " if detail else "")
            + f"Google Translate: {exc}"
        ) from exc


def _seconds(value) -> float:
    """Accept numeric seconds or HH:MM:SS,mmm timestamps from Gemini."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    return parse_srt_timestamp(text)


def transcribe_translate_video(video_path: str, srt_path: str, work_dir: str,
                               progress) -> tuple[int, list[str], dict]:
    """Upload the complete video once; Gemini understands visuals + dialogue in one request."""
    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError("Streamlit Secrets ထဲတွင် GEMINI_API_KEY မတွေ့ပါ။")

    client = genai.Client(api_key=api_key)
    uploaded_file = None
    warnings = []
    progress(0.03, "အဆင့် ၁/၅ — Video တစ်ခုလုံးကို Gemini သို့ တင်နေသည်")
    try:
        uploaded_file = client.files.upload(file=video_path)
        if not getattr(uploaded_file, "name", None) or not getattr(uploaded_file, "uri", None):
            raise RuntimeError("Gemini File API မှ Video ဖိုင်အချက်အလက် မရရှိပါ။")

        # Gemini needs the uploaded video to become ACTIVE before analysis.
        import time
        max_wait_seconds = 15 * 60
        waited = 0
        while True:
            state = getattr(uploaded_file, "state", None)
            state_name = getattr(state, "name", str(state or "")).upper()
            if "ACTIVE" in state_name:
                break
            if "FAILED" in state_name:
                raise RuntimeError("Gemini က Video ကို ပြင်ဆင်မရပါ။ MP4 ဖိုင်ဖြင့် ထပ်စမ်းကြည့်ပါ။")
            if waited >= max_wait_seconds:
                raise RuntimeError("Gemini Video ပြင်ဆင်ချိန် ၁၅ မိနစ်ကျော်သွားပါသည်။")
            progress(min(0.20, 0.08 + (waited / max_wait_seconds) * 0.12),
                     f"အဆင့် ၁/၅ — Gemini က Video ကို ပြင်ဆင်နေသည် ({waited // 5 + 1})")
            time.sleep(5)
            waited += 5
            uploaded_file = client.files.get(name=uploaded_file.name)

        progress(0.25, "အဆင့် ၂/၅ — Gemini AI က Video မြင်ကွင်းနှင့် အသံကို စစ်ဆေးနေသည်")
        prompt = r"""You are an expert video understanding, transcription, and Burmese dubbing assistant.
Analyze the ENTIRE uploaded video, not just a short excerpt. Understand both the visual scenes and the audio.
The spoken language is mainly Chinese or English. Produce natural conversational Burmese suitable for dubbing.

Return ONLY valid JSON with this exact structure:
{
  "video_summary_my": "A concise Burmese summary of the whole video and its story/context",
  "scenes": [
    {"start": 0.0, "end": 5.0, "description_my": "What is visibly happening in this scene, in Burmese"}
  ],
  "segments": [
    {"start": 0.0, "end": 2.5, "speaker": "Speaker 1", "original_text": "Original spoken words", "burmese_text": "Natural Burmese translation"}
  ]
}

Rules:
- Inspect the whole video from beginning to end. Do not invent unseen events.
- Transcribe every audible spoken line. Do not summarize dialogue and do not omit short lines.
- Include only speech that can be heard. Do not create dialogue from subtitles or visual context alone.
- Preserve the original language words in original_text and translate the meaning into natural Burmese in burmese_text.
- Use seconds from the beginning of the video for start and end. Use decimal seconds (example: 12.35).
- Timestamps must follow the actual speech timing. Each end must be later than its start.
- Keep each segment short (usually one sentence or phrase) for dubbing.
- Identify speakers consistently as Speaker 1, Speaker 2, etc. If uncertain, use Speaker.
- In scenes, give a concise description of important visual actions, characters, and scene changes. Do not make a separate scene for every frame.
- If there is no speech, return an empty segments array.
- JSON only. No Markdown fences and no extra explanation."""

        progress(0.35, "အဆင့် ၂/၅ — Gemini က Video တစ်ခုလုံးကို နားလည်ပြီး စာသားထုတ်နေသည်")
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[prompt, uploaded_file],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        response_text = (response.text or "").strip()
        if not response_text:
            raise RuntimeError("Gemini မှ Video analysis စာသားဗလာ ပြန်လာပါသည်။")
        response_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text, flags=re.I).strip()
        try:
            analysis = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Gemini ရဲ့ Video analysis JSON ကို ဖတ်မရပါ။ Video အလွန်ရှည်နေနိုင်ပါတယ်။\n"
                + response_text[:1500]
            ) from exc

        raw_segments = analysis.get("segments", [])
        cues = []
        for item in raw_segments:
            try:
                start = max(0.0, _seconds(item.get("start", 0)))
                end = _seconds(item.get("end", 0))
                line = " ".join(str(item.get("burmese_text", "")).split()).strip()
                if line and end > start + 0.05:
                    cues.append((start, end, line))
            except Exception:
                warnings.append("အချိန်ပုံစံမမှန်သော စာကြောင်းတစ်ခုကို ကျော်ထားသည်။")

        if not cues:
            raise RuntimeError("Gemini က Video ထဲတွင် အသုံးပြုနိုင်သော စကားပြောစာသား မတွေ့ပါ။")

        cues.sort(key=lambda x: (x[0], x[1]))
        normalized = []
        for start, end, line in cues:
            if normalized and start < normalized[-1][1]:
                start = normalized[-1][1]
            if end > start + 0.05:
                normalized.append((start, end, line))

        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (start, end, line) in enumerate(normalized, start=1):
                f.write(f"{i}\n{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n{line}\n\n")

        # Keep a user-readable transcript with original speech, Burmese translation and scene notes.
        analysis["segments"] = [
            {
                "start": item.get("start"),
                "end": item.get("end"),
                "speaker": item.get("speaker", "Speaker"),
                "original_text": item.get("original_text", ""),
                "burmese_text": item.get("burmese_text", ""),
            }
            for item in raw_segments
        ]
        Path(os.path.join(work_dir, "video_analysis.json")).write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        progress(1.0, f"အဆင့် ၂/၅ ပြီးပါပြီ — Video နားလည်၊ စာသားထုတ်ပြီး ({len(normalized)} ပိုင်း)")
        return len(normalized), warnings, analysis
    finally:
        # Remove uploaded source from Gemini storage after processing when possible.
        if uploaded_file is not None and getattr(uploaded_file, "name", None):
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

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


async def create_tts(text: str, destination: str, voice: str) -> None:
    communicator = edge_tts.Communicate(text=text, voice=voice)
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


def parse_srt_timestamp(value: str) -> float:
    value = value.strip().replace('.', ',')
    match = re.fullmatch(r'(\d{1,3}):(\d{1,2}):(\d{1,2}),(\d{1,3})', value)
    if not match:
        raise ValueError(f"အချိန်ပုံစံ မမှန်ပါ: {value}")
    h, m, sec, ms = (int(x) for x in match.groups())
    return h * 3600 + m * 60 + sec + int(str(ms).ljust(3, '0')[:3]) / 1000.0


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    sec, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def auto_fix_srt(source_path: str, fixed_path: str, video_duration: float):
    """Repair common SRT formatting/timing issues and return a concise report."""
    raw = Path(source_path).read_text(encoding='utf-8-sig', errors='replace')
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\s*\n', raw.strip())
    fixed_blocks, warnings = [], []
    cue_count = 0
    for block in blocks:
        lines = [line.strip('\ufeff') for line in block.split('\n')]
        time_index = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if time_index is None:
            continue
        time_line = lines[time_index]
        match = re.search(r'(.+?)\s*-->\s*(.+?)(?:\s+.*)?$', time_line)
        if not match:
            warnings.append('ဖတ်မရသော timestamp တစ်ခုကို ကျော်ထားသည်')
            continue
        try:
            start = parse_srt_timestamp(match.group(1).strip())
            end = parse_srt_timestamp(match.group(2).strip().split()[0])
        except ValueError:
            # Also accept timestamps with a dot separator and normalize them.
            try:
                start = parse_srt_timestamp(match.group(1).strip().replace('.', ','))
                end = parse_srt_timestamp(match.group(2).strip().split()[0].replace('.', ','))
            except ValueError:
                warnings.append('အချိန်ပုံစံမမှန်သော စာတန်းတစ်ခုကို ကျော်ထားသည်')
                continue
        if start < 0:
            start = 0.0
            warnings.append('အနုတ်အချိန်ကို 00:00:00,000 သို့ ပြင်ထားသည်')
        if start >= video_duration:
            warnings.append('ဗီဒီယိုအဆုံးကျော်နေသော စာတန်းတစ်ခုကို ဖယ်ထားသည်')
            continue
        if end > video_duration:
            end = video_duration
            warnings.append('ဗီဒီယိုအရှည်ထက်ကျော်သော အဆုံးအချိန်ကို ညှိထားသည်')
        if end <= start + 0.03:
            warnings.append('ကြာချိန်မရှိ/အနုတ်ဖြစ်နေသော စာတန်းတစ်ခုကို ဖယ်ထားသည်')
            continue
        text_lines = [line.strip() for line in lines[time_index + 1:] if line.strip()]
        if not text_lines:
            warnings.append('စာသားဗလာဖြစ်နေသော စာတန်းတစ်ခုကို ဖယ်ထားသည်')
            continue
        cue_count += 1
        fixed_blocks.append('\n'.join([
            str(cue_count),
            f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}",
            *text_lines,
        ]))
    if not fixed_blocks:
        raise RuntimeError('ပြင်ဆင်ပြီးနောက် အသုံးပြုနိုင်သော SRT စာတန်း မကျန်ပါ။ Timestamp များကို စစ်ဆေးပါ။')
    Path(fixed_path).write_text('\n\n'.join(fixed_blocks) + '\n', encoding='utf-8')
    return cue_count, list(dict.fromkeys(warnings))


def make_dubbed_timeline(video_path: str, srt_path: str, work_dir: str, voice: str, progress):
    video_duration = get_media_duration(video_path)
    fixed_srt_path = os.path.join(work_dir, 'auto_fixed_subtitles.srt')
    fixed_count, fix_warnings = auto_fix_srt(srt_path, fixed_srt_path, video_duration)
    subtitles = pysrt.open(fixed_srt_path, encoding="utf-8")
    if not subtitles:
        raise RuntimeError("SRT ဖိုင်ထဲတွင် စာတန်း မတွေ့ပါ။")

    valid = []
    for sub in subtitles:
        line = " ".join(sub.text.replace("\\ufeff", "").split()).strip()
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
            await create_tts(line, audio_path, voice)
            paths.append(audio_path)
            progress((i / len(valid)) * 0.55, f"မြန်မာအသံ ဖန်တီးခြင်း ({i}/{len(valid)})")
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
        progress(0.55 + (i / len(valid)) * 0.45, f"Video အချိန်ကိုက်ညှိခြင်း ({i}/{len(valid)})")

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
    return joined_video, mp3_output, output_duration, used_count, fix_warnings


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

st.title("🎬 Myanmar Auto Video Dubbing")
st.caption("Video တစ်ခုတည်းတင်ပါ။ Gemini AI က မြင်ကွင်းနှင့် အသံကို တစ်ပြိုင်နက်နားလည်၊ စာသားထုတ်၊ မြန်မာလိုပြန်ဆိုပြီး Dubbing လုပ်ပေးပါမည်။")

with st.sidebar:
    st.subheader("အသံဆက်တင်")
    st.caption("မြန်မာအသံရွေးချယ်မှုကို အောက်တွင် ပြုလုပ်နိုင်ပါသည်။")
    st.caption(f"Upload ကန့်သတ်ချက်: {MAX_UPLOAD_MB} MB")
    st.caption("Video မြင်ကွင်း + အသံနားလည်ခြင်း: Gemini AI")
    if st.button("Logout", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()

selected_voice_label = st.selectbox("🎙️ မြန်မာအသံရွေးချယ်ပါ", list(VOICES.keys()), index=0)
selected_voice = VOICES[selected_voice_label]

video_file = st.file_uploader("မူရင်းဗီဒီယို Upload လုပ်ပါ", type=["mp4", "mov", "mkv", "webm"])

st.info(
    "လုပ်ဆောင်ပုံ — Video တစ်ခုလုံးကို Gemini သို့ တင်မည် → မြင်ကွင်းနှင့် အသံကို နားလည်၊ စကားပြောစာသားထုတ်ပြီး မြန်မာလို ပြန်ဆိုမည် → "
    "ရွေးချယ်ထားသော မြန်မာအသံထုတ်မည် → Video နှင့် အသံကို ပေါင်းစပ်မည်။ "
    "အသံကို အမြန်/အနှေး မပြောင်းဘဲ Video အပိုင်းကိုသာ အသံနှင့် ကိုက်ညီအောင် ညှိပါမည်။"
)

if video_file:
    video_mb = video_file.size / (1024 * 1024)
    st.write(f"Video: **{video_file.name}** ({video_mb:.1f} MB)")
    if video_mb > MAX_UPLOAD_MB:
        st.error(f"ဖိုင်သည် {MAX_UPLOAD_MB} MB ထက် မကြီးရပါ။")
    elif st.button("🚀 START AUTO DUBBING", type="primary", use_container_width=True):
        status = st.empty()
        bar = st.progress(0)
        st.caption(f"ရွေးချယ်ထားသောအသံ: {selected_voice_label}")
        try:
            with tempfile.TemporaryDirectory(prefix="myanmar_auto_dub_") as work_dir:
                video_path = os.path.join(
                    work_dir, "source_video" + Path(video_file.name).suffix.lower()
                )
                srt_path = os.path.join(work_dir, "ai_translated.srt")
                mp4_output = os.path.join(work_dir, "final_output.mp4")
                with open(video_path, "wb") as f:
                    f.write(video_file.getbuffer())

                status.info("အဆင့် ၁/၅ — Video တစ်ခုလုံးကို Gemini သို့ တင်နေသည် (၁၀%)")
                def update_ai(value, message):
                    overall = 10 + int(value * 45)
                    bar.progress(max(1, min(60, overall)))
                    status.info(f"{message} | စုစုပေါင်း {overall}%")

                cue_count, ai_warnings, video_analysis = transcribe_translate_video(
                    video_path, srt_path, work_dir, update_ai
                )
                st.session_state["video_analysis"] = video_analysis
                status.info("အဆင့် ၃/၅ — ရွေးချယ်ထားသော မြန်မာအသံ ဖန်တီးခြင်း (၅၅% မှ ၇၇%)")
                def update_tts(value, message):
                    overall = 55 + int(value * 40)
                    bar.progress(min(95, overall))
                    stage = "အဆင့် ၃/၅" if value <= 0.55 else "အဆင့် ၄/၅"
                    status.info(f"{stage} — {message} | စုစုပေါင်း {overall}%")

                joined_video, audio_path, duration, count, fix_warnings = make_dubbed_timeline(
                    video_path, srt_path, work_dir, selected_voice, update_tts
                )
                status.info("အဆင့် ၅/၅ — နောက်ဆုံး MP4 ဖိုင်ပေါင်းစပ်ခြင်း (၉၅% မှ ၁၀၀%)")
                bar.progress(95)
                mux_video(joined_video, audio_path, mp4_output, duration)
                bar.progress(100)
                status.success(f"အဆင့် ၅/၅ ပြီးပါပြီ — ၁၀၀% | {selected_voice_label} အသံဖြင့် မြန်မာအသံ {count} ပိုင်း ထုတ်လုပ်ပြီးပါပြီ။")
                if ai_warnings or fix_warnings:
                    with st.expander("လုပ်ဆောင်မှု မှတ်တမ်း"):
                        for warning in ai_warnings + fix_warnings:
                            st.write("• " + warning)

                st.session_state["result_mp4"] = Path(mp4_output).read_bytes()
                st.session_state["result_mp3"] = Path(audio_path).read_bytes()
                st.session_state["result_name"] = Path(video_file.name).stem
        except Exception as exc:
            st.error("လုပ်ဆောင်မှု မအောင်မြင်ပါ။")
            st.exception(exc)

if st.session_state.get("result_mp4") and st.session_state.get("result_mp3"):
    st.divider()
    st.subheader("✅ ရလဒ်များ")
    analysis = st.session_state.get("video_analysis", {})
    if analysis:
        with st.expander("🎬 AI က နားလည်ထားသော Video အကြောင်းအရာနှင့် စာသား", expanded=False):
            summary = analysis.get("video_summary_my", "")
            if summary:
                st.markdown("**Video အကျဉ်းချုပ်**")
                st.write(summary)
            scenes = analysis.get("scenes", [])
            if scenes:
                st.markdown("**မြင်ကွင်းများ**")
                for scene in scenes:
                    st.write(f"{scene.get('start', '')}s–{scene.get('end', '')}s: {scene.get('description_my', '')}")
            transcript = analysis.get("segments", [])
            if transcript:
                st.markdown("**အသံစာသားနှင့် မြန်မာဘာသာပြန်**")
                for seg in transcript:
                    st.write(f"{seg.get('speaker', 'Speaker')} | {seg.get('start', '')}s–{seg.get('end', '')}s")
                    original = seg.get("original_text", "")
                    if original:
                        st.caption(original)
                    st.write(seg.get("burmese_text", ""))
    st.video(st.session_state["result_mp4"])
    st.audio(st.session_state["result_mp3"], format="audio/mp3")
    base = st.session_state.get("result_name", "dubbed_video")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("⬇️ Download MP4 Video", data=st.session_state["result_mp4"],
                           file_name=f"{base}_myanmar_dub.mp4", mime="video/mp4",
                           use_container_width=True)
    with col2:
        st.download_button("⬇️ Download MP3 Audio", data=st.session_state["result_mp3"],
                           file_name=f"{base}_myanmar_dub.mp3", mime="audio/mpeg",
                           use_container_width=True)

st.divider()
st.caption("ဖိုင်များကို ယာယီဖိုလ်ဒါတွင်သာ Process လုပ်ပြီး ပြီးဆုံးပါက ဖျက်ပစ်ပါသည်။")
