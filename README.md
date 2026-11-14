# Myanmar Auto Video Dubbing — Full Video Understanding

Upload one video. Gemini uploads and analyzes the complete video (visual scenes + spoken audio) in one model request, returns timestamped original dialogue and Burmese translations, and produces a Burmese voice dub with Thiha or Nilar.

## Streamlit Secrets
Keep your existing values:

```toml
APP_PASSWORD = "your-existing-password"
GEMINI_API_KEY = "your-gemini-api-key"
```

The app uses the Gemini Files API for the uploaded video, waits until processing is complete, then analyzes the video. It attempts to delete the temporary Gemini file after analysis.

Free-tier limits still apply. A new API key in the same Google Cloud project does not reset project quota.
