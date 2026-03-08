"""Music control — Apple Music and Spotify playback via AppleScript."""

import subprocess

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
# Helpers
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


def _music_app_name(app: str) -> str:
    return "Spotify" if app == "spotify" else "Music"


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------
def execute(args: dict) -> str:
    """Execute a music control action and return a result string."""
    action = args.get("action", "")
    app = args.get("app", "apple_music")
    query = args.get("query", "")
    artist = args.get("artist", "")
    app_name = _music_app_name(app)

    # Escape single quotes
    safe_query = query.replace("'", "'\\''") if query else ""
    safe_artist = artist.replace("'", "'\\''") if artist else ""

    if action == "play":
        _applescript(f'tell application "{app_name}" to play')
        return f"Resumed playback on {app_name}."

    elif action == "pause":
        _applescript(f'tell application "{app_name}" to pause')
        return f"Paused {app_name}."

    elif action == "next":
        _applescript(f'tell application "{app_name}" to next track')
        return f"Skipped to next track on {app_name}."

    elif action == "previous":
        _applescript(f'tell application "{app_name}" to previous track')
        return f"Went to previous track on {app_name}."

    elif action == "current_track":
        info = _applescript(
            f'tell application "{app_name}" to get '
            f'{{name of current track, artist of current track, album of current track}}'
        )
        if info.startswith("Error"):
            return "No track is currently playing."
        return f"Now playing on {app_name}: {info}"

    elif action == "play_song" and safe_query:
        if app == "spotify":
            _applescript(f'tell application "Spotify" to play')
            return f"Spotify doesn't support search via AppleScript. Resumed playback. Try searching in the Spotify app for '{query}'."
        else:
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
        if app == "spotify":
            _applescript(f'tell application "Spotify" to play')
            return f"Spotify doesn't support search via AppleScript. Resumed playback."
        else:
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
        if app == "spotify":
            _applescript(f'tell application "Spotify" to play')
            return f"Spotify doesn't support search via AppleScript. Resumed playback."
        else:
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
        if app == "spotify":
            return "Spotify library browsing is not supported via AppleScript."
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
        if app == "spotify":
            return "Spotify library browsing is not supported via AppleScript."
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
        if app == "spotify":
            return "Spotify library search is not supported via AppleScript."
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
        if app == "spotify":
            return "Spotify library browsing is not supported via AppleScript."
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
        if app == "spotify":
            return "Spotify library browsing is not supported via AppleScript."
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
