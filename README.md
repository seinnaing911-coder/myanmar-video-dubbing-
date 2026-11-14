# Myanmar Auto Video Dubbing

Upload one video. Gemini 3.5 Transcribe detects and transcribes the source speech, Gemini 3.8 Flash translates it into Burmese, and Microsoft Edge TTS `my-MM-ThihaNeural` creates the Burmese voice. FFmpeg assembles the dubbed MP4.

## Streamlit Community Cloud
- Main file: `app.py`
- Keep the existing `APP_PASSWORD` secret.
- Add `GEMINI_API_KEY = "your Gemini API key"` to App settings → Secrets.
- Do not share the API key publicly.

The app processes audio in 15-second chunks to reduce request size.
