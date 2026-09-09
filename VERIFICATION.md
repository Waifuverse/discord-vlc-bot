# Verification

Local playback checks were performed on Windows with Python 3.12.10, VLC 3.0.23, discord.py 2.7.1 and aiohttp 3.14.3. No credentials, server identifiers or private library inventory are included here.

## Automated coverage

Run `python -m unittest discover -s tests -v` after installing dependencies. The suite uses local HTTP fixtures and Discord interaction doubles; it does not need real credentials or installed VLC.

- Idempotent pause/play, ordered concurrent seeks, boundary clamping, invalid skips and unseekable media.
- Server/channel/role restrictions, cooldowns, host and Manage Server permissions, and persisted host lock.
- Local-only VLC URLs, HTTP authentication, safe errors, corrupt-state handling and duplicate-process locking.
- Persistent button definitions, all thirteen `/vlc` subcommands, `/help`, public replies and help while VLC is offline or locked.
- Show/version grouping, natural sorting, folder containment, missing files, playlist capacity and stale-editor conflicts.
- Shared library editors, pagination, add/move/remove actions and two-click clearing.
- Saved draft edits independent of playback, failure preservation and disabling shuffle/repeat when applying a queue.
- Private configuration generation/preservation, portable media paths, blank public template and publication checks.

The repository includes a Windows GitHub Actions matrix for Python 3.11, 3.12 and 3.13, dependency validation, PowerShell parsing and tracked-file privacy checks. Consult the Actions tab for actual hosted results.

## Real VLC integration

A separate VLC process played generated audio on a temporary loopback port. Pause/resume and repeated pause worked; rewind moved 60s to 45s, forward moved 45s to 75s, and three concurrent ten-second skips accumulated to 105s.

Local video checks also verified opening media, a custom three-episode order, backward/forward seeking, resume, Next/Previous and saved playlist edits leaving VLC's active queue unchanged. Video timestamps settled within two seconds of requested positions, accounting for container/keyframe rounding. The rendered video was inspected visually.

A configured Discord installation successfully authenticated, connected to the Gateway and registered `/help` and `/vlc`. Command and channel permissions were checked through Discord's API. These checks do not substitute for interactions from another member's Discord client or verify every possible role override.

## Live acceptance checklist for your installation

1. Run setup, fill in `.env`, start the launcher, and screen-share the controlled VLC window with audio.
2. Run `/help` and `/vlc help`. As host, run `/vlc panel`; confirm another member sees the replies and commands.
3. Have that member press Play/Pause and use `/vlc rewind seconds:15`, `/vlc forward seconds:15` and Custom skip; watch the host's VLC respond.
4. Lock the remote: guests should be denied playback changes but retain Status/Help access. Unlock and retry.
5. Browse Shows, add episodes, reorder and start a playlist. Test Next/Previous and refresh a second person's outdated editor.
6. Restart the bot: confirm the main panel, saved list and host lock survive. Reopen temporary library editors.

Human Discord-client interactions, stream audio/video quality and your channel-specific permissions require this final live check.
