from __future__ import annotations

import os
import re
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
PORT = int(os.environ.get("PORT", "8080"))
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "BitChordCommunityAddon/0.1 (audio search prototype)"})
AUDIO_PRIORITY = {".flac": 0, ".wav": 1, ".ogg": 2, ".opus": 3, ".m4a": 4, ".mp3": 5, ".aiff": 6, ".aif": 6}


def audio_ext(name: str) -> str:
    match = re.search(r"\.[A-Za-z0-9]{2,5}$", name or "")
    return match.group(0).lower() if match else ""


def choose_audio(files: list[dict]) -> dict | None:
    candidates = []
    for item in files:
        name = item.get("name", "")
        ext = audio_ext(name)
        if ext in AUDIO_PRIORITY and not name.startswith("__MACOSX/"):
            candidates.append((AUDIO_PRIORITY[ext], name.lower(), item))
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][2] if candidates else None


def public_file_url(identifier: str, filename: str) -> str:
    safe_path = "/".join(quote(part, safe="") for part in filename.split("/"))
    return f"https://archive.org/download/{quote(identifier, safe='')}/{safe_path}"


@app.get("/")
def index():
    return jsonify({"name": "BitChord Community Audio", "version": "0.1.0", "manifest": "/manifest.json", "health": "/health"})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/manifest.json")
def manifest():
    # Generic manifest. Adapt this to the exact schema expected by your BitChord build.
    return jsonify({
        "id": "community.archive.audio",
        "name": "Community Audio Archive",
        "version": "0.1.0",
        "description": "Search public-domain or appropriately licensed audio hosted by Internet Archive.",
        "baseUrl": request.host_url.rstrip("/"),
        "endpoints": {"search": "/search?q={query}&limit={limit}", "stream": "/stream?id={id}"},
    })


@app.get("/search")
def search():
    query = (request.args.get("q") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 50))
    except ValueError:
        limit = 20
    if not query:
        return jsonify({"tracks": [], "total": 0})

    params = [
        ("q", f'({query}) AND mediatype:audio'),
        ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "creator"),
        ("fl[]", "date"), ("rows", str(limit)), ("page", "1"),
        ("output", "json"), ("sort[]", "downloads desc"),
    ]
    try:
        response = SESSION.get(IA_SEARCH, params=params, timeout=15)
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Internet Archive search is temporarily unavailable", "tracks": [], "total": 0}), 502

    tracks = []
    for doc in docs:
        identifier = doc.get("identifier")
        if not identifier:
            continue
        creator = doc.get("creator") or "Unknown artist"
        if isinstance(creator, list):
            creator = ", ".join(str(x) for x in creator[:3])
        title = doc.get("title") or identifier
        tracks.append({
            "id": identifier, "title": str(title), "artist": str(creator),
            "album": str(title), "audioQuality": "UNKNOWN",
            "format": "Resolve using the stream endpoint", "source": "Internet Archive",
        })
    return jsonify({"tracks": tracks, "total": len(tracks)})


@app.get("/stream")
def stream():
    identifier = (request.args.get("id") or "").strip()
    if not identifier or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        return jsonify({"error": "A valid Internet Archive identifier is required"}), 400
    try:
        response = SESSION.get(IA_METADATA + quote(identifier, safe=""), timeout=20)
        response.raise_for_status()
        metadata = response.json()
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Could not retrieve item metadata"}), 502

    selected = choose_audio(metadata.get("files", []))
    if not selected:
        return jsonify({"error": "No supported audio file found for this item"}), 404
    filename = selected.get("name", "")
    ext = audio_ext(filename)
    format_name = ext.lstrip(".").upper()
    mime = selected.get("format") or ("audio/mpeg" if ext == ".mp3" else "audio/" + ext.lstrip("."))
    return jsonify({
        "id": identifier,
        "url": public_file_url(identifier, filename),
        "mimeType": mime,
        "format": format_name,
        "size": selected.get("size"),
        "audioQuality": "LOSSLESS_CONTAINER" if ext in {".flac", ".wav", ".aiff", ".aif"} else "LOSSY_OR_UNKNOWN",
        "license": "Check the Internet Archive item page before use",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
