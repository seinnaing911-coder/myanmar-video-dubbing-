# Myanmar Video Dubbing Studio

Private/password-gated Streamlit app for generating Burmese Thiha Neural dubbing from an uploaded video and SRT file.

## Files
- `app.py`: Streamlit application
- `requirements.txt`: Python packages
- `packages.txt`: system package (FFmpeg) for Streamlit Community Cloud
- `.streamlit/config.toml`: upload size setting

## Run locally
1. Install FFmpeg and make sure `ffmpeg` and `ffprobe` are available on PATH.
2. Install Python 3.10+.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create `.streamlit/secrets.toml`:
   ```toml
   APP_PASSWORD = "replace-with-a-long-private-password"
   ```
5. Run:
   ```bash
   streamlit run app.py
   ```

## Deploy to Streamlit Community Cloud
1. Create a GitHub repository and upload these files. Do NOT upload `secrets.toml`.
2. Create an app at https://share.streamlit.io/ and select this repository and `app.py`.
3. In the app's Advanced settings / Secrets, add:
   ```toml
   APP_PASSWORD = "replace-with-a-long-private-password"
   ```
4. Deploy and open the app URL. Enter the password to use it.

## Privacy warning
The password gate protects the app interface, but Streamlit Community Cloud apps are not equivalent to a fully private server. The GitHub repository used for Community Cloud should be public, so the source code can be viewed. Do not upload private videos or sensitive content unless you accept the hosting provider's terms and data handling. For strict private hosting, use a private server/VPS or a Hugging Face private Space; these may have hosting costs. Do not commit `.streamlit/secrets.toml`.

## Notes
- Original video audio is replaced by the generated Burmese voice.
- Audio is placed at the SRT timestamps. Empty gaps remain silent.
- If speech is longer than its subtitle slot, FFmpeg `atempo` speeds it up without intentionally changing pitch; very long lines may still sound fast.
- Streamlit Community Cloud has resource, upload, processing-time and temporary-storage limits. Large videos may fail. For larger videos, run locally or use a server with more RAM/disk/CPU.
- Edge TTS requires outbound internet access.
