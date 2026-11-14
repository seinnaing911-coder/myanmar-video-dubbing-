import streamlit as st
import os, json, re, subprocess, tempfile, shutil, time
from pathlib import Path
import asyncio
import edge_tts
from google import genai
from google.genai import types

st.set_page_config(page_title="Myanmar Auto Dubbing", page_icon="🎬", layout="centered")

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-3500:])
    return p.stdout.strip()

def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path])
    return float(out)

def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("AI က JSON အဖြေ မပြန်လာပါ။ ထပ်စမ်းကြည့်ပါ။")
    return json.loads(text[a:b+1])

async def make_tts(text, out_path):
    communicate = edge_tts.Communicate(text, "my-MM-ThihaNeural")
    await communicate.save(out_path)

def probe_video_info(path):
    raw = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height,r_frame_rate",
               "-of", "json", path])
    return json.loads(raw)["streams"][0]

st.title("🎬 မြန်မာ Auto Video Dubbing")
st.write("Video တစ်ခုတည်းတင်ပါ။ Chinese / English အသံကို AI က စစ်ဆေးပြီး မြန်မာလို ပြန်ဆိုပေးပါမယ်။")
st.info("အကြံပြုချက် — အရင်ဆုံး ၁ မိနစ်မှ ၃ မိနစ်ခန့်ရှိသော video တစ်ခုဖြင့် စမ်းသပ်ပါ။")

# Password protection
secret_password = st.secrets.get("APP_PASSWORD", "")
if secret_password:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        pw = st.text_input("Website Password", type="password")
        if st.button("ဝင်မည်"):
            if pw == secret_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Password မှားနေပါတယ်။")
        st.stop()

api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    st.warning("Streamlit → Settings → Secrets ထဲတွင် GEMINI_API_KEY ထည့်ပေးပါ။")
    st.code('GEMINI_API_KEY = "သင်၏_Gemini_API_Key"')
    st.stop()

uploaded = st.file_uploader("မူရင်း Video ကိုရွေးပါ", type=["mp4", "mov", "mkv", "webm"])
voice = st.selectbox("မြန်မာအသံ", ["my-MM-ThihaNeural", "my-MM-NilarNeural"], index=0)
if uploaded and st.button("ဘာသာပြန်ပြီး Dubbing လုပ်မည်", type="primary"):
    work = tempfile.mkdtemp(prefix="myanmar_dub_")
    try:
        input_path = os.path.join(work, "original_video" + Path(uploaded.name).suffix.lower())
        with open(input_path, "wb") as f:
            f.write(uploaded.getbuffer())
        video_len = duration(input_path)
        if video_len > 1200:
            st.error("လက်ရှိဗားရှင်းတွင် Video အရှည် ၂၀ မိနစ်အထိသာ လက်ခံနိုင်ပါတယ်။")
            st.stop()

        status = st.status("Video ကို ပြင်ဆင်နေပါတယ်...", expanded=True)
        audio_path = os.path.join(work, "source_audio.wav")
        run(["ffmpeg", "-y", "-i", input_path, "-vn", "-ac", "1", "-ar", "16000",
             "-c:a", "pcm_s16le", audio_path])

        status.update(label="AI က မူရင်းအသံကို နားထောင်ပြီး မြန်မာလို ဘာသာပြန်နေပါတယ်...")
        client = genai.Client(api_key=api_key)
        audio_file = client.files.upload(file=audio_path, config={"mime_type": "audio/wav"})
        prompt = """
Listen to the entire audio. It may contain Chinese, English, or both.
Translate every spoken sentence into natural conversational Burmese.
Return ONLY valid JSON in this exact shape:
{"segments":[{"start":0.0,"end":2.4,"text":"မြန်မာဘာသာပြန်စာသား"}]}
Times must be seconds from the beginning of the audio. Use accurate utterance start/end times.
Keep segments in chronological order, do not overlap them, omit music and non-speech.
Do not return the original language; text must be Burmese. Do not add explanations.
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[audio_file, prompt],
            config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json")
        )
        data = parse_json(response.text)
        segments = data.get("segments", [])
        cleaned = []
        for s in segments:
            try:
                start, end = float(s["start"]), float(s["end"])
                txt = str(s["text"]).strip()
                if txt and end > start and start < video_len:
                    cleaned.append({"start": max(0, start), "end": min(video_len, end), "text": txt})
            except Exception:
                continue
        cleaned.sort(key=lambda x: x["start"])
        if not cleaned:
            raise ValueError("စကားပြောစာသား မတွေ့ပါ။ အသံပါသော Video ဖြင့် ထပ်စမ်းပါ။")

        status.update(label="မြန်မာအသံ ဖန်တီးပြီး Video နဲ့ အချိန်ညှိနေပါတယ်...")
        pieces = []
        cursor = 0.0
        for i, seg in enumerate(cleaned):
            start = max(cursor, seg["start"])
            end = max(start, seg["end"])
            if start > cursor + 0.08:
                gap = os.path.join(work, f"part_{len(pieces):04d}.mp4")
                gapdur = start - cursor
                run(["ffmpeg", "-y", "-ss", str(cursor), "-i", input_path, "-t", str(gapdur),
                     "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
                     "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", gap])
                pieces.append(gap)
            if end <= start + 0.05:
                cursor = max(cursor, end)
                continue
            tts_path = os.path.join(work, f"voice_{i:04d}.mp3")
            asyncio.run(make_tts(seg["text"], tts_path))
            tts_dur = duration(tts_path)
            src_dur = end - start
            factor = tts_dur / src_dur
            clip = os.path.join(work, f"part_{len(pieces):04d}.mp4")
            # Adjust video playback duration to match normal-speed Burmese speech.
            run(["ffmpeg", "-y", "-ss", str(start), "-i", input_path, "-i", tts_path,
                 "-t", str(src_dur), "-filter:v", f"setpts={factor:.8f}*(PTS-STARTPTS)",
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", clip])
            pieces.append(clip)
            cursor = end

        if cursor < video_len - 0.08:
            gap = os.path.join(work, f"part_{len(pieces):04d}.mp4")
            gapdur = video_len - cursor
            run(["ffmpeg", "-y", "-ss", str(cursor), "-i", input_path, "-t", str(gapdur),
                 "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
                 "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", gap])
            pieces.append(gap)

        concat_file = os.path.join(work, "concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for p in pieces:
                f.write("file '" + p.replace("'", "'\\''") + "'\n")
        output_mp4 = os.path.join(work, "Myanmar_Dubbed.mp4")
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
             "-c", "copy", output_mp4])

        # Export a separate MP3 of the finished Burmese dubbing track.
        output_mp3 = os.path.join(work, "Myanmar_Voice.mp3")
        run(["ffmpeg", "-y", "-i", output_mp4, "-vn", "-q:a", "2", output_mp3])

        status.update(label="ပြီးပါပြီ!", state="complete", expanded=False)
        st.success("Dubbing ပြီးပါပြီ။")
        with open(output_mp4, "rb") as f:
            st.download_button("📥 မြန်မာ Dubbing Video (MP4) ဒေါင်းလုဒ်", f, "Myanmar_Dubbed.mp4", "video/mp4")
        with open(output_mp3, "rb") as f:
            st.download_button("📥 မြန်မာအသံ (MP3) ဒေါင်းလုဒ်", f, "Myanmar_Voice.mp3", "audio/mpeg")
        with st.expander("ဘာသာပြန်စာသားများ ကြည့်ရန်"):
            for n, s in enumerate(cleaned, 1):
                st.write(f"{n}. {s['text']}")
        st.caption("မှတ်ချက် — AI ၏ စကားပြောအချိန်ခန့်မှန်းမှု မတိကျနိုင်ပါ။ အရေးကြီးသော Video များတွင် ရလဒ်ကို စစ်ဆေးပါ။")
    except Exception as e:
        st.error("လုပ်ဆောင်ရာတွင် အမှားဖြစ်သွားပါတယ်။")
        st.code(str(e))
        st.info("Gemini API Key မှန်/မမှန် စစ်ဆေးပြီး Video တိုတစ်ခုဖြင့် ထပ်စမ်းပါ။")
    finally:
        shutil.rmtree(work, ignore_errors=True)
