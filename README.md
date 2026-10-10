# BitChord Community Audio Addon (prototype)

This is a small, self-hostable audio-search service intended as a starting point for replacing an older BitChord source. It searches Internet Archive metadata and returns direct links to supported audio files. It does **not** restore the original Ricky addon or provide access to commercial music catalogues.

## Compatibility warning
BitChord's custom addon manifest/result contract can vary by version and is not fully established here. This project exposes a conventional manifest and HTTP endpoints, but it is **not guaranteed to be directly installable in BitChord without adapting the schema to your installed version**.

## Run
Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py
```

Check `http://127.0.0.1:8080/health`, `http://127.0.0.1:8080/manifest.json`, and `http://127.0.0.1:8080/search?q=beethoven&limit=10`.

For a phone to reach this service, it must be deployed to a public HTTPS host or a server on the same network. A phone cannot normally reach `127.0.0.1` on your computer.

## Endpoints
- `GET /manifest.json` addon metadata
- `GET /health` health check
- `GET /search?q=<query>&limit=20` search Internet Archive audio items
- `GET /stream?id=<identifier>` resolve the preferred supported audio file

## Quality reporting
The service prefers FLAC, WAV, Ogg/Opus, M4A, then MP3. It reports the selected file extension and size when available. A FLAC file is not proof that the original recording was lossless; the archive source may itself have been transcoded. Always check item licensing and file provenance.

## Limitations
- Some search results will not contain playable files.
- Search metadata and licenses vary by item.
- This is a prototype, not a verified BitChord-compatible production addon.
