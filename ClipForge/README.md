# ClipForge Local — Windows audio clip maker

## Quick start
1. Install **Python 3.11 or 3.12** from python.org (check **Add Python to PATH**).
2. Install **FFmpeg** from ffmpeg.org and add its `bin` folder to your Windows PATH. Confirm `ffmpeg -version` in a new Command Prompt.
3. Extract this ZIP to a normal writable folder (e.g. Documents\ClipForge).
4. Double-click **start_windows.bat**. It creates a virtual environment, installs Python dependencies, and starts the local server.
5. Open **http://127.0.0.1:8765** if the browser does not open automatically. Keep the command window running.
6. Optional offline speech-to-text: in the app folder run `.venv\Scripts\python -m pip install faster-whisper`. The first transcription downloads a Whisper model; later runs can use the cached model. Set `WHISPER_MODEL=small` before launch for higher quality (slower).

## Features
- Upload local audio/video; extract audio with FFmpeg.
- Import **direct HTTPS public media files** (MP3, WAV, OGG, M4A, FLAC, MP4, WebM), limited to 500 MB.
- Preview and choose timestamp ranges; export one clip or a batch of up to 50 MP3 clips.
- Local SQLite source/clip library with searchable titles/tags and audio soundboard.
- Microphone recording with browser permission, saved to the local library.
- Optional Faster-Whisper transcription with timestamped, searchable segments.

## Source permissions
Import media that you own, is public domain, is openly licensed, or you otherwise have permission to use. The URL importer only accepts direct downloadable media files, **not YouTube watch URLs**, streaming manifests, DRM-protected sources, or login-required services. For YouTube, use the official player to identify timestamps and import an audio/video file you are authorized to possess, such as your own exported recording. For podcast RSS, find the episode's permitted direct enclosure URL and paste that link. Internet Archive items with downloadable audio files can be imported by direct file URL subject to the item's rights.

## Notes and limitations
- This is a working local-first MVP, not a hardened multi-user internet-facing service. Server listens on 127.0.0.1 only. Do not expose the port publicly.
- The waveform is computed from real decoded PCM audio samples using FFmpeg. No simulated waveform is used.
- Browser recording captures microphone input, **not system/tab audio**.
- URL imports reject redirects and private network targets, but are intended for trusted public URLs. Avoid importing untrusted media files.
- Batch jobs run sequentially; long jobs and transcriptions may block a request. Data lives in `data/`; back it up.
- Clips are MP3; original uploads are transcoded to MP3. Other export formats are future enhancements.


## YouTube links

Paste a YouTube watch, short, live, or youtu.be URL into the URL field and press Import URL. ClipForge opens an embedded preview and original link instead of trying to treat the YouTube page as a downloadable MP3. To trim/transcribe, import an audio/video file you own or are authorized to use. This does not download or bypass YouTube streams.


## YouTube audio import (v1.2)
Paste an HTTPS YouTube watch, Shorts, live-archive, or youtu.be URL. The app shows an embedded preview. If you own the content or have permission and are authorized to download it, check the confirmation box and click **Import authorized YouTube audio**. The backend uses yt-dlp to fetch an available audio stream, then FFmpeg converts it to MP3 and adds it to the source library. Live streams, playlists, restricted content, and videos requiring login are not supported. Do not use this feature to bypass access controls, DRM, or rights restrictions. YouTube's terms may restrict downloading without express permission from the service.

If a supported video fails, update yt-dlp using `.venv\Scripts\python -m pip install -U yt-dlp` in Command Prompt, then restart the app. YouTube changes can break extraction unexpectedly.

**Upgrade:** Stop ClipForge, back up the existing `data` directory, replace `app.py`, `static/index.html`, `requirements.txt` and `README.md`, and run `start_windows.bat`. Keep your original `data` folder to preserve the library.


## Real waveform editor (v1.3)
Select a source and wait for **Waveform ready**. FFmpeg and ffprobe must be on PATH.
The waveform is calculated from decoded mono PCM and cached only in the browser for the current source.
Drag the green start handle and orange end handle to adjust the selection, or edit the numeric timestamps.
Click elsewhere on the waveform to seek. The white cursor tracks playback.
Clip export and batch clipping use the same timestamp fields.

## v1.4: Real waveform troubleshooting

The waveform now displays **REAL AUDIO** and a count of analyzed peak windows beneath the canvas. It is computed by `GET /api/source/{id}/waveform` from FFmpeg-decoded PCM. No sine-wave placeholder exists.

If you still see the old illustrative waveform, you are running old files. Stop the server, replace BOTH `app.py` and `static/index.html`, restart `start_windows.bat`, then press Ctrl+Shift+R. Verify the page header says **LOCAL v1.4**.

If the waveform shows an error, open Command Prompt and check `ffmpeg -version` and `ffprobe -version`. Restart the server after updating PATH. Click **Reload waveform** after selecting a source.


## ClipForge Studio v1.5 additions (2026-11)

**Upgrade without losing your library:** Stop the old server. Make a backup of your existing `ClipForge/data/` folder (includes `library.sqlite3`, media, clips). Copy `app.py` and `static/index.html` from this package into the EXISTING `ClipForge` folder, replacing those two files. Do not replace/delete your `data/` folder or `.venv/`. Restart `start_windows.bat`. For a new installation, unzip and run `start_windows.bat`.

- Waveform zoom and keyboard playback controls: Space, Left/Right arrows, I/O, +/-; click waveform or transcript segments to seek.
- New media folder in Studio tools > Storage: changes only where **future imports** are stored; previous source paths in SQLite remain intact. Database and clips still use the installation's `data/` folder. OneDrive syncing may interfere with large media/database files.
- Local transcription now runs as a background job with status and progress; install optional packages using `.venv\Scripts\python -m pip install faster-whisper numpy`. The progress estimate is based on decoded audio position, not exact elapsed time. Model first-use may download from the internet. FFmpeg PCM bypasses PyAV decode issues.
- Transcript search and click-to-seek, manual speaker labels (automatic speaker diarization **not included**).
- Silence detection via FFmpeg; audio cleanup creates a **new** source and leaves original untouched.
- Soundboard named profiles and number keys 1–9; export presets MP3, speech MP3 and WAV.
- 8-track episode builder with start offsets and per-clip gain, exported to MP3. This is a basic mixer, **not** a drag-and-drop DAW.
- Suggested highlights are **heuristic**, not generative AI. Cross-source search uses **local keyword overlap**, not vector embeddings.
- Library backup downloads the SQLite database **only**; back up `data/media`, `data/clips`, and any custom media folder separately.
- Background jobs are kept in memory and are lost on server restart.

**Windows:** Requires FFmpeg and FFprobe in PATH. No external cloud APIs are required for normal operation; YouTube imports and first-time model downloads require network access.
