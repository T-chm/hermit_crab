"""Music control — Apple Music (AppleScript) and Spotify (spogo CLI)."""

import json as _json
import shutil
import subprocess

HAS_SPOGO = shutil.which("spogo") is not None

DEFINITION = {
    "type": "function",
    "function": {
        "name": "music_control",
        "description": (
            "Control music playback on Apple Music or Spotify. "
            "ONLY use when the user explicitly asks to play, pause, skip, "
            "search, or browse music. Do NOT call for greetings or general conversation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "play", "pause", "next", "previous",
                        "current_track", "play_song", "play_artist", "play_album",
                        "artist_info", "album_info", "search",
                        "list_artists", "list_albums",
                    ],
                    "description": (
                        "play: resume playback. pause: pause playback. "
                        "next/previous: skip tracks. current_track: what's playing now. "
                        "play_song: play a specific song (set query to song name, optionally set artist). "
                        "play_artist: shuffle all songs by an artist (set query to artist name). "
                        "play_album: play an album (set query to album name). "
                        "artist_info: list albums and songs by an artist. "
                        "album_info: list tracks on an album. "
                        "search: search the library for anything. "
                        "list_artists: list all artists in the library. "
                        "list_albums: list all albums in the library."
                    ),
                },
                "app": {
                    "type": "string",
                    "enum": ["spotify", "apple_music"],
                    "description": "Which music app to use. Default: apple_music",
                },
                "query": {
                    "type": "string",
                    "description": "Song name, artist name, album name, or search query",
                },
                "artist": {
                    "type": "string",
                    "description": "Artist name — use with play_song to find a specific song by a specific artist (e.g. query='Volcano', artist='U2')",
                },
            },
            "required": ["action"],
        },
    },
}


# ---------------------------------------------------------------------------
# AppleScript helpers (Apple Music)
# ---------------------------------------------------------------------------
def _applescript(script: str, timeout: int = 15) -> str:
    """Run an AppleScript via osascript and return output."""
    r = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        return f"Error: {r.stderr.strip()}"
    return r.stdout.strip()


# ---------------------------------------------------------------------------
# spogo helpers (Spotify)
# ---------------------------------------------------------------------------
def _spogo(args: list, timeout: int = 15) -> str:
    """Run a spogo CLI command and return output."""
    r = subprocess.run(
        ["spogo"] + args,
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        return f"Error: {r.stderr.strip()}"
    return r.stdout.strip()


def _spogo_json(args: list, timeout: int = 15):
    """Run a spogo command with --json and parse the output."""
    out = _spogo(args + ["--json"], timeout=timeout)
    if out.startswith("Error"):
        return None
    try:
        return _json.loads(out)
    except (_json.JSONDecodeError, ValueError):
        return None


def _spotify_no_spogo():
    return (
        "Spotify requires the spogo CLI for full control. "
        "Install it with: brew install steipete/tap/spogo && spogo auth import --browser chrome"
    )


# ---------------------------------------------------------------------------
# Spotify actions via spogo
# ---------------------------------------------------------------------------
def _spotify_execute(action: str, query: str, artist: str) -> str:
    """Handle all Spotify actions via spogo CLI."""
    if not HAS_SPOGO:
        return _spotify_no_spogo()

    if action == "play":
        _spogo(["play"])
        return "Resumed playback on Spotify."

    elif action == "pause":
        _spogo(["pause"])
        return "Paused Spotify."

    elif action == "next":
        _spogo(["next"])
        return "Skipped to next track on Spotify."

    elif action == "previous":
        _spogo(["prev"])
        return "Went to previous track on Spotify."

    elif action == "current_track":
        result = _spogo(["status", "--plain"])
        if result.startswith("Error"):
            return "No track is currently playing on Spotify."
        return f"Now playing on Spotify: {result}"

    elif action == "play_song" and query:
        search_query = f"{query} {artist}".strip() if artist else query
        data = _spogo_json(["search", "track", search_query, "--limit", "5"])
        if not data:
            return f"No results for '{search_query}' on Spotify."
        # data is a list of track objects; find best match
        tracks = data if isinstance(data, list) else data.get("tracks", data.get("items", []))
        if not tracks:
            return f"No results for '{search_query}' on Spotify."
        # If artist specified, try to match
        picked = tracks[0]
        if artist:
            for t in tracks:
                t_artists = ""
                if isinstance(t.get("artists"), list):
                    t_artists = " ".join(a.get("name", "") for a in t["artists"])
                elif isinstance(t.get("artist"), str):
                    t_artists = t["artist"]
                if artist.lower() in t_artists.lower():
                    picked = t
                    break
        uri = picked.get("uri") or picked.get("id", "")
        name = picked.get("name", query)
        _spogo(["play", uri])
        return f"Now playing on Spotify: {name}"

    elif action == "play_artist" and query:
        data = _spogo_json(["search", "artist", query, "--limit", "1"])
        if not data:
            return f"Could not find artist '{query}' on Spotify."
        artists = data if isinstance(data, list) else data.get("artists", data.get("items", []))
        if not artists:
            return f"Could not find artist '{query}' on Spotify."
        uri = artists[0].get("uri") or artists[0].get("id", "")
        name = artists[0].get("name", query)
        _spogo(["play", uri, "--type", "artist", "--shuffle"])
        return f"Playing {name} on Spotify (shuffled)."

    elif action == "play_album" and query:
        data = _spogo_json(["search", "album", query, "--limit", "1"])
        if not data:
            return f"Could not find album '{query}' on Spotify."
        albums = data if isinstance(data, list) else data.get("albums", data.get("items", []))
        if not albums:
            return f"Could not find album '{query}' on Spotify."
        uri = albums[0].get("uri") or albums[0].get("id", "")
        name = albums[0].get("name", query)
        _spogo(["play", uri, "--type", "album"])
        return f"Playing album '{name}' on Spotify."

    elif action == "search" and query:
        result = _spogo(["search", "track", query, "--limit", "15", "--plain"])
        if result.startswith("Error") or not result:
            return f"No results for '{query}' on Spotify."
        return f"Spotify search results for '{query}':\n{result}"

    elif action == "artist_info" and query:
        data = _spogo_json(["search", "artist", query, "--limit", "1"])
        if not data:
            return f"Could not find artist '{query}' on Spotify."
        artists = data if isinstance(data, list) else data.get("artists", data.get("items", []))
        if not artists:
            return f"Could not find artist '{query}' on Spotify."
        artist_id = artists[0].get("id") or artists[0].get("uri", "")
        name = artists[0].get("name", query)
        info = _spogo(["artist", "info", artist_id, "--plain"])
        if info.startswith("Error"):
            return f"Found {name} but could not fetch details."
        return info

    elif action == "album_info" and query:
        data = _spogo_json(["search", "album", query, "--limit", "1"])
        if not data:
            return f"Could not find album '{query}' on Spotify."
        albums = data if isinstance(data, list) else data.get("albums", data.get("items", []))
        if not albums:
            return f"Could not find album '{query}' on Spotify."
        album_id = albums[0].get("id") or albums[0].get("uri", "")
        info = _spogo(["album", "info", album_id, "--plain"])
        if info.startswith("Error"):
            name = albums[0].get("name", query)
            return f"Found '{name}' but could not fetch details."
        return info

    elif action == "list_artists":
        result = _spogo(["library", "artists", "--limit", "50", "--plain"], timeout=30)
        if result.startswith("Error") or not result:
            return "Could not read your Spotify library."
        return f"Artists in your Spotify library:\n{result}"

    elif action == "list_albums":
        result = _spogo(["library", "albums", "--limit", "50", "--plain"], timeout=30)
        if result.startswith("Error") or not result:
            return "Could not read your Spotify library."
        return f"Albums in your Spotify library:\n{result}"

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# Apple Music actions via AppleScript
# ---------------------------------------------------------------------------
def _apple_music_execute(action: str, query: str, artist: str) -> str:
    """Handle all Apple Music actions via AppleScript."""
    safe_query = query.replace("'", "'\\''") if query else ""
    safe_artist = artist.replace("'", "'\\''") if artist else ""

    if action == "play":
        _applescript('tell application "Music" to play')
        return "Resumed playback on Apple Music."

    elif action == "pause":
        _applescript('tell application "Music" to pause')
        return "Paused Apple Music."

    elif action == "next":
        _applescript('tell application "Music" to next track')
        return "Skipped to next track on Apple Music."

    elif action == "previous":
        _applescript('tell application "Music" to previous track')
        return "Went to previous track on Apple Music."

    elif action == "current_track":
        info = _applescript(
            'tell application "Music" to get '
            '{name of current track, artist of current track, album of current track}'
        )
        if info.startswith("Error"):
            return "No track is currently playing."
        return f"Now playing on Apple Music: {info}"

    elif action == "play_song" and safe_query:
        if safe_artist:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only songs)\n'
                f'  if (count of results) = 0 then return "NOT_FOUND"\n'
                f'  repeat with t in results\n'
                f'    if artist of t contains "{safe_artist}" then\n'
                f'      play t\n'
                f'      return name of current track & " by " & artist of current track\n'
                f'    end if\n'
                f'  end repeat\n'
                f'  play item 1 of results\n'
                f'  return name of current track & " by " & artist of current track\n'
                f'end tell'
            )
        else:
            result = _applescript(
                f'tell application "Music"\n'
                f'  set results to (search playlist "Library" for "{safe_query}" only songs)\n'
                f'  if (count of results) > 0 then\n'
                f'    play item 1 of results\n'
                f'    return name of current track & " by " & artist of current track\n'
                f'  else\n'
                f'    return "NOT_FOUND"\n'
                f'  end if\n'
                f'end tell'
            )
        if "NOT_FOUND" in result or result.startswith("Error"):
            msg = f"Could not find '{query}'"
            if artist:
                msg += f" by {artist}"
            return msg + " in your Apple Music library."
        return f"Now playing: {result}"

    elif action == "play_artist" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose artist contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set shuffle enabled to true\n'
            f'  play item 1 of results\n'
            f'  return "Playing " & artist of current track & " — " & name of current track & " (" & (count of results) & " tracks, shuffled)"\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find artist '{query}' in your Apple Music library."
        return result

    elif action == "play_album" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (search playlist "Library" for "{safe_query}" only albums)\n'
            f'  if (count of results) > 0 then\n'
            f'    play item 1 of results\n'
            f'    return "Playing album: " & album of current track\n'
            f'  else\n'
            f'    return "NOT_FOUND"\n'
            f'  end if\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find album '{query}' in your Apple Music library."
        return result

    elif action == "artist_info" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose artist contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set albumList to {{}}\n'
            f'  set songList to {{}}\n'
            f'  repeat with t in results\n'
            f'    set aName to album of t\n'
            f'    if aName is not in albumList then set end of albumList to aName\n'
            f'    if (count of songList) < 20 then\n'
            f'      set end of songList to (name of t & " (" & album of t & ")")\n'
            f'    end if\n'
            f'  end repeat\n'
            f'  set albumCount to count of albumList\n'
            f'  set songCount to count of results\n'
            f'  set output to "Artist: {safe_query}" & return & "Songs: " & songCount & ", Albums: " & albumCount & return & return & "Albums:" & return\n'
            f'  repeat with a in albumList\n'
            f'    set output to output & "- " & a & return\n'
            f'  end repeat\n'
            f'  set output to output & return & "Songs (first 20):" & return\n'
            f'  repeat with s in songList\n'
            f'    set output to output & "- " & s & return\n'
            f'  end repeat\n'
            f'  return output\n'
            f'end tell',
            timeout=30,
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find artist '{query}' in your Apple Music library."
        return result

    elif action == "album_info" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (every track of playlist "Library" whose album contains "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set output to "Album: " & album of (item 1 of results) & return & "Artist: " & artist of (item 1 of results) & return & "Tracks:" & return\n'
            f'  repeat with t in results\n'
            f'    set output to output & (track number of t) & ". " & (name of t) & " (" & (round ((duration of t) / 60) rounding down) & ":" & text -2 thru -1 of ("0" & (round ((duration of t) mod 60))) & ")" & return\n'
            f'  end repeat\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"Could not find album '{query}' in your Apple Music library."
        return result

    elif action == "search" and safe_query:
        result = _applescript(
            f'tell application "Music"\n'
            f'  set results to (search playlist "Library" for "{safe_query}")\n'
            f'  if (count of results) = 0 then return "NOT_FOUND"\n'
            f'  set output to "Search results for \\"{safe_query}\\":" & return\n'
            f'  set maxItems to 15\n'
            f'  if (count of results) < maxItems then set maxItems to (count of results)\n'
            f'  repeat with i from 1 to maxItems\n'
            f'    set t to item i of results\n'
            f'    set output to output & "- " & (name of t) & " by " & (artist of t) & " (" & (album of t) & ")" & return\n'
            f'  end repeat\n'
            f'  if (count of results) > 15 then set output to output & "... and " & ((count of results) - 15) & " more results"\n'
            f'  return output\n'
            f'end tell'
        )
        if "NOT_FOUND" in result or result.startswith("Error"):
            return f"No results found for '{query}' in your Apple Music library."
        return result

    elif action == "list_artists":
        result = _applescript(
            'tell application "Music"\n'
            '  set allTracks to every track of playlist "Library"\n'
            '  set artistList to {}\n'
            '  repeat with t in allTracks\n'
            '    set aName to artist of t\n'
            '    if aName is not in artistList then set end of artistList to aName\n'
            '  end repeat\n'
            '  set totalCount to count of artistList\n'
            '  set maxShow to 50\n'
            '  if totalCount < maxShow then set maxShow to totalCount\n'
            '  set output to "Artists in your library (" & totalCount & " total):" & return\n'
            '  repeat with i from 1 to maxShow\n'
            '    set output to output & "- " & item i of artistList & return\n'
            '  end repeat\n'
            '  if totalCount > 50 then set output to output & "... and " & (totalCount - 50) & " more"\n'
            '  return output\n'
            'end tell',
            timeout=30,
        )
        if result.startswith("Error"):
            return "Could not read your Apple Music library."
        return result

    elif action == "list_albums":
        result = _applescript(
            'tell application "Music"\n'
            '  set allTracks to every track of playlist "Library"\n'
            '  set albumList to {}\n'
            '  set albumArtists to {}\n'
            '  repeat with t in allTracks\n'
            '    set aName to album of t\n'
            '    if aName is not in albumList then\n'
            '      set end of albumList to aName\n'
            '      set end of albumArtists to artist of t\n'
            '    end if\n'
            '  end repeat\n'
            '  set totalCount to count of albumList\n'
            '  set maxShow to 50\n'
            '  if totalCount < maxShow then set maxShow to totalCount\n'
            '  set output to "Albums in your library (" & totalCount & " total):" & return\n'
            '  repeat with i from 1 to maxShow\n'
            '    set output to output & "- " & item i of albumList & " (" & item i of albumArtists & ")" & return\n'
            '  end repeat\n'
            '  if totalCount > 50 then set output to output & "... and " & (totalCount - 50) & " more"\n'
            '  return output\n'
            'end tell',
            timeout=30,
        )
        if result.startswith("Error"):
            return "Could not read your Apple Music library."
        return result

    return f"Unknown action: {action}"


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------
def execute(args: dict) -> str:
    """Route to the correct backend based on the app parameter."""
    action = args.get("action", "")
    app = args.get("app", "apple_music")
    query = args.get("query", "")
    artist = args.get("artist", "")

    if app == "spotify":
        return _spotify_execute(action, query, artist)
    return _apple_music_execute(action, query, artist)
