# Security and local data

This bot controls a VLC instance on the host PC. Discord carries the screen share; the bot only handles controls, video titles and playlist choices.

- `.env` contains a Discord bot token and VLC HTTP password. It is ignored by Git and must stay on the host PC. `config.env.template` is deliberately blank.
- The bot accepts only loopback HTTP addresses for VLC. The launcher binds the interface to loopback, and requests do not follow redirects. No public VLC endpoint or port forwarding is needed.
- Show and playlist actions resolve files inside `MEDIA_ROOT`. They do not accept arbitrary network URLs or filesystem paths from Discord users.
- Normal replies and library titles are public in the configured channel. Anyone with its access can control playback unless a role restriction or host lock applies. Voice-call membership is not required.
- The VLC password is passed to the local VLC process at launch. Other sufficiently privileged users on the same PC may inspect process arguments. This setup assumes a trusted host PC.
- `.state` holds session/playlist state and may contain logs. Keep it local. Mask credentials, identifiers and personal paths before sharing diagnostic output.

If a real token is exposed, reset it in the Discord Developer Portal and update the local `.env`. Removing it from the latest Git version does not remove it from earlier commits or copies.

Report vulnerabilities using the repository's private vulnerability reporting feature **if it is enabled**. Otherwise contact the repository owner privately; do not post working credentials in an issue. This file does not imply private reporting has been enabled.
