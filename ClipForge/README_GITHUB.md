# ClipForge Studio — Public Testing Snapshot

ClipForge Studio is a **local-first Windows podcast production tool** with a clip library, waveform editor, soundboard, multitrack episode editor, and teleprompter.

## Getting started
1. Install Python 3.11 or 3.12 and ensure `py -3` works.
2. Install FFmpeg and FFprobe and add their binaries to PATH.
3. Download the repository ZIP or clone it.
4. Run `start_windows.bat` from the project folder.
5. Open http://127.0.0.1:8765.

The launcher creates a local `.venv` and installs the dependencies in `requirements.txt`. Transcription is optional; install with `.venv\\Scripts\\python -m pip install faster-whisper numpy`. A Whisper model may be downloaded on first use.

## Privacy and safety
This distribution intentionally excludes all local recordings, transcripts, SQLite databases, backups, profiles and personal media. Runtime data is created locally in `data/`. **Never commit `data/` or `.venv/`.**

The server is designed to listen on `127.0.0.1` only; do not expose it to the internet. Only import content you have rights to use. See `README.md` for more detail on supported media and limitations.

## Testing
See `CONTRIBUTING.md` for reporting issues. This is a **source testing build**, not a signed Windows installer. The navigation/color fixes are included, but end-to-end Windows testing is still needed.

## Licensing
No open-source license has been selected for this snapshot. Add a `LICENSE` file before inviting outside code contributions or granting reuse rights.
