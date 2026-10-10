from __future__ import annotations

import os
import re
from urllib.parse import quote

import requests
from flask import Flask, jsonify, redirect, request
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Render terminates TLS at its proxy. Without this, request.host_url is http://
# and the manifest advertises an insecure baseUrl, which phone apps often block.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

PORT = int(os.environ.get("PORT", "8080"))
IA_SEARCH = "https://archive.org/advancedsearch.php"
IA_METADATA = "https://archive.org/metadata/"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "BitChordCommunityAddon/0.2 (audio search prototype)"})

AUDIO_PRIORITY = {".flac": 0, ".wav": 1, ".aiff": 2, ".aif": 2, ".ogg": 3, ".opus": 4, ".m4a": 5, ".mp3": 6}
LOSSLESS = {".flac", ".wav", ".aiff", ".aif"}
MIME = {
    ".flac": "audio/flac", ".wav": "audio/wav", ".aiff": "audio/aiff", ".aif": "audio/aiff",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
}


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


def audio_ext(name: str) -> str:
    match = re.search(r"\.[A-Za-z0-9]{2,5}$", name or "")
    return match.group(0).lower() if match else ""


def audio_files(files: list[dict]) -> list[dict]:
    out = []
    for item in files:
        name = item.get("name", "")
        if audio_ext(name) in AUDIO_PRIORITY and not name.startswith("__MACOSX/"):
            out.append(item)
    out.sort(key=lambda f: (AUDIO_PRIORITY[audio_ext(f["name"])], f["name"].lower()))
    return out


def public_file_url(identifier: str, filename: str) -> str:
    safe_path = "/".join(quote(part, safe="") for part in filename.split("/"))
    return f"https://archive.org/download/{quote(identifier, safe='')}/{safe_path}"


def track_dict(identifier: str, f: dict, album: str, artist: str) -> dict:
    ext = audio_ext(f["name"])
    return {
        "id": f"{identifier}|{f['name']}",
        "title": f.get("title") or os.path.splitext(os.path.basename(f["name"]))[0],
        "artist": f.get("creator") or artist,
        "album": album,
        "format": ext.lstrip(".").upper(),
        "audioQuality": "LOSSLESS" if ext in LOSSLESS else "LOSSY",
        "size": f.get("size"),
        "streamUrl": public_file_url(identifier, f["name"]),
        "source": "Internet Archive",
    }


def get_metadata(identifier: str) -> dict:
    r = SESSION.get(IA_METADATA + quote(identifier, safe=""), timeout=20)
    r.raise_for_status()
    return r.json()


@app.get("/")
def index():
    return jsonify({"name": "BitChord Community Audio", "version": "0.2.0",
                    "manifest": "/manifest.json", "health": "/health"})


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/manifest.json")
def manifest():
    # Generic manifest. Adapt to the exact schema your BitChord / LastWave build expects.
    base = request.host_url.rstrip("/")
    return jsonify({
        "id": "community.archive.audio",
        "name": "Community Audio Archive",
        "version": "0.2.0",
        "description": "Search public-domain or appropriately licensed audio hosted by Internet Archive.",
        "baseUrl": base,
        "endpoints": {
            "search": "/search?q={query}&limit={limit}",
            "tracks": "/tracks?id={id}",
            "stream": "/stream?id={id}",
        },
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

    # Only return items that actually contain a FLAC file (default). Use flac=0 to disable.
    flac_only = request.args.get("flac", "1") != "0"
    q = f"({query}) AND mediatype:audio"
    if flac_only:
        q += " AND format:Flac"

    params = [
        ("q", q),
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
            "album": str(title), "audioQuality": "LOSSLESS" if flac_only else "UNKNOWN",
            "format": "FLAC" if flac_only else "Resolve using the stream endpoint",
            "source": "Internet Archive",
        })
    return jsonify({"tracks": tracks, "total": len(tracks)})


@app.get("/tracks")
def tracks():
    """Track-level listing for one item (an item is usually a whole album)."""
    identifier = (request.args.get("id") or "").split("|")[0].strip()
    if not identifier or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        return jsonify({"error": "A valid Internet Archive identifier is required"}), 400
    try:
        meta = get_metadata(identifier)
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Could not retrieve item metadata"}), 502

    info = meta.get("metadata", {})
    album = str(info.get("title") or identifier)
    artist = info.get("creator") or "Unknown artist"
    if isinstance(artist, list):
        artist = ", ".join(str(x) for x in artist[:3])

    files = audio_files(meta.get("files", []))
    # Keep only the best format present, so a FLAC album doesn't list MP3 duplicates.
    if files:
        best = audio_ext(files[0]["name"])
        files = [f for f in files if audio_ext(f["name"]) == best]
        files.sort(key=lambda f: f["name"].lower())
    out = [track_dict(identifier, f, album, str(artist)) for f in files]
    return jsonify({"tracks": out, "total": len(out)})


@app.get("/stream")
def stream():
    """
    /stream?id=<item>                 best audio file in the item
    /stream?id=<item>|<file>          that specific file (ids from /tracks)
    /stream?id=<item>&file=<file>     same, explicit
    Add &redirect=1 to get a 302 straight to the audio file instead of JSON,
    for players that expect the stream URL itself to serve audio.
    """
    raw_id = (request.args.get("id") or "").strip()
    identifier, _, filename = raw_id.partition("|")
    filename = request.args.get("file") or filename
    if not identifier or not re.fullmatch(r"[A-Za-z0-9._-]+", identifier):
        return jsonify({"error": "A valid Internet Archive identifier is required"}), 400
    try:
        meta = get_metadata(identifier)
    except (requests.RequestException, ValueError):
        return jsonify({"error": "Could not retrieve item metadata"}), 502

    files = audio_files(meta.get("files", []))
    selected = None
    if filename:
        selected = next((f for f in files if f["name"] == filename), None)
    elif files:
        selected = files[0]
    if not selected:
        return jsonify({"error": "No supported audio file found for this item"}), 404

    name = selected["name"]
    ext = audio_ext(name)
    url = public_file_url(identifier, name)
    if request.args.get("redirect") == "1":
        return redirect(url, code=302)
    return jsonify({
        "id": raw_id, "url": url, "mimeType": MIME.get(ext, "audio/" + ext.lstrip(".")),
        "format": ext.lstrip(".").upper(), "size": selected.get("size"),
        "audioQuality": "LOSSLESS" if ext in LOSSLESS else "LOSSY",
        "license": "Check the Internet Archive item page before use",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
