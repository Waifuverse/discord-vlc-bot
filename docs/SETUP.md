# Set up your first watch session

**Only the person screen-sharing VLC needs to do the setup below.** Friends just use Discord; they do not need Python, VLC, a bot token or their own copy of the videos. [Skip to the instructions for friends.](#for-friends-joining-a-session)

The host runs the bot and VLC on the same Windows PC. Discord carries the screen share, and the bot lets people control that one VLC player. Each host creates their own Discord bot application.

## 1. Install Python and VLC on the host PC

Use Windows 10 or 11 and the Discord desktop app. You also need permission to add a bot to your Discord server.

- Install Python from the [official Windows downloads page](https://www.python.org/downloads/windows/). Python **3.11, 3.12 and 3.13** are tested with this project. For a new installation, choose a Python 3.13 Windows installer matching your PC. Enable **Add python.exe to PATH** if the installer offers it.
- Install [VLC from VideoLAN](https://www.videolan.org/vlc/) in its normal installation folder. This project uses VLC 3.x.

After installing Python, open a new PowerShell window and run:

```powershell
python --version
```

It should print your Python version. If Windows opens the Store or says Python cannot be found, fix the Python installation/PATH before continuing.

## 2. Download and extract the project

1. Open [discord-vlc-bot on GitHub](https://github.com/Waifuverse/discord-vlc-bot).
2. Click the green **Code** button, then **Download ZIP**.
3. In File Explorer, right-click the downloaded ZIP and choose **Extract All**.
4. Open the extracted folder that contains `setup.ps1` and `Start VLC Remote.cmd`. Keep this folder somewhere you plan to leave it; it will hold your configuration and saved playlist.
5. Click File Explorer's address bar, type `powershell`, and press Enter. This opens PowerShell in that folder.

Use the extracted files, not the files viewed inside the ZIP. You do not need Git for this method.

## 3. Run setup and open your configuration

In that PowerShell window, run these commands one at a time:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
notepad .env
```

Wait for setup to finish before opening Notepad. It installs the bot's dependencies and creates the real `.env` file with a generated VLC password. Leave Notepad open for the next steps.

**Edit `.env`, not `config.env.template`.** The template is the blank file shared on GitHub. Your generated `.env` is private and is ignored by Git. Rerunning setup preserves an existing `.env`.

## 4. Create your bot and invite it to your server

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), choose **New Application**, and name it, for example, **Watch Party Remote**. Use a new application dedicated to this project.
2. Open **Bot → Reset Token**, complete Discord's verification, and copy the token into `.env` immediately after `DISCORD_TOKEN=`. Save it locally; never paste the token into Discord or GitHub.
3. Open **Installation**. Enable **Guild Install**, then choose **Discord Provided Link** under **Install Link**.
4. Under **Default Install Settings → Guild Install**, select scopes **bot** and **applications.commands**. Set permissions to **View Channels**, **Send Messages**, **Embed Links** and **Read Message History**. Save changes.
5. Copy the installation link, open it in your browser, choose **Add to server**, select your server and authorize it.

Leave privileged intents off and **Interactions Endpoint URL** empty for this project. The bot will appear offline until you start it in step 7. [Discord's official application setup reference](https://docs.discord.com/developers/quick-start/getting-started).

## 5. Fill in the server, channel and host IDs

In Discord, turn on **User Settings → Advanced → Developer Mode**. Choose a regular text channel for the remote, such as `#watch-party`.

Fill in the corresponding lines in the `.env` already open in Notepad:

| Line in `.env` | What to put after `=` |
| --- | --- |
| `DISCORD_TOKEN=` | The bot token from step 4. |
| `DISCORD_GUILD_ID=` | Right-click your server icon → **Copy Server ID**. |
| `DISCORD_CHANNEL_ID=` | Right-click your chosen text channel → **Copy Channel ID**. |
| `HOST_USER_ID=` | Right-click your own user in the server member list → **Copy User ID**. This lets you create and lock the remote. |
| `CONTROL_ROLE_ID=` | Leave empty to allow everyone in the control channel to use it. |
| `MEDIA_ROOT=media` | Keep `media` for the included folder, or use your existing video folder as described below. |
| `VLC_URL=...` | Keep the generated default `http://127.0.0.1:8080`. |
| `VLC_PASSWORD=...` | Keep the password setup generated; do not erase it. |

IDs are long numbers, not channel names or usernames. Discord's [guide to copying IDs](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID) shows where to find them.

Press **Ctrl+S**. Keep the filename `.env`, not `.env.txt`. Close Notepad before screen-sharing.

## 6. Choose your video folder and allow shared control

For the default setup, place your videos in show folders inside the project's `media` folder:

```text
media/
  Example Show/
    Episode_01_Subbed.mp4
    Episode_02_Subbed.mp4
    Episode_01_Dubbed.mp4
  Another Show/
    Episode_01.mkv
```

Alternatively, point `MEDIA_ROOT` at an existing folder. For example, if your shows are inside `D:\Videos\Watch Party`, use:

```dotenv
MEDIA_ROOT="D:/Videos/Watch Party"
```

The first folder becomes the show name. `Subbed` and `Dubbed` in filenames create separate versions; other files appear as **Unlabelled**. Episodes sort numerically. [Supported video formats and folder details](../media/README.md).

In the control channel's permissions, let your friends **View Channel**, **Send Messages** and **Use Application Commands**. Confirm the bot has the four permissions listed in step 4. If commands are restricted in **Server Settings → Integrations → your bot**, allow the intended members and channel there too.

With `CONTROL_ROLE_ID` blank, everyone with control-channel access can change playback, even if they are not in the voice call. The host can use `/vlc lock` whenever they want exclusive control.

## 7. Start VLC, the bot and the screen share

1. Double-click **Start VLC Remote.cmd** in the project folder.
2. Wait for VLC to open and for the console to say **Connected as ... Use /vlc panel in the configured channel.** Leave the console open.
3. In your control channel, type `/vlc panel`, select your bot's command from Discord's suggestions and send it. As the configured host, you should receive the shared remote with buttons.
4. Click **Shows**, choose a show/version and episode, then **Play episode now**. You can also open a video directly from **Media → Open File** in the VLC window the launcher opened.
5. Join a Discord voice call and screen-share that **VLC window**, with audio enabled. Ask a friend to watch the stream.

Use the VLC window opened by this launcher if you have more than one VLC window. Keep the PC awake and both VLC and the bot running throughout the session.

## 8. Test the controls together

Ask your friend to try each action in the configured text channel:

| Action | What should happen |
| --- | --- |
| `/help` | Everyone sees the command guide. |
| `/vlc pause` | The host's video pauses. |
| `/vlc play` | Playback resumes. |
| `/vlc rewind` with `seconds` set to `15` | Playback moves back about 15 seconds. |
| `/vlc forward` with `seconds` set to `15` | Playback moves forward about 15 seconds. |

For slash commands, pick the command from Discord's menu, fill its options, then press Enter. The panel's **Custom skip** also accepts `-15` or `+15`.

The host can run `/vlc lock` to prevent guests changing playback, then `/vlc unlock` to restore shared control. Guests can still read Help and Status while locked.

## Build and reorder a shared playlist

1. Open **Shows** or run `/vlc shows`.
2. Choose a show/version. Select an episode and press **Add episode**, or use **Add this version in order** to add the whole version.
3. Open **Playlist** or run `/vlc playlist`.
4. Select an entry and use **Move up**, **Move down** or **Move to position**. Positions start at **1**. Use **Remove episode** to remove an entry.
5. Click **Start playlist from beginning** when the order is ready. VLC replaces its active queue and plays that order automatically.

For example, to watch episodes 1, 3, 2, add all three in order, select episode 3 in Playlist and press **Move up** once, then start the playlist.

The saved list holds up to 100 entries. Edits do not interrupt the currently playing video; start the playlist again to apply a changed order. **Next episode** and **Previous episode** follow the active VLC queue. **Clear saved playlist** asks for a second click and never deletes video files.

Everyone with control access can use the shared editor. If another person changes the list first, refresh or reopen your editor before trying again. Reopen Shows after adding new files; restart the bot after changing `MEDIA_ROOT`.

## For friends joining a session

You only need Discord:

1. Join the host's voice call and open their VLC screen share.
2. Open the text channel the host chose for the remote.
3. Use the shared **Play**, **Pause** and skip buttons, or run `/help` for the command list.
4. To skip exactly 15 seconds, use `/vlc rewind` or `/vlc forward` and set `seconds` to `15`.
5. Use **Shows** to pick an episode or **Playlist** to help arrange the viewing order.

These controls affect the shared video for everyone. If the host has locked the remote or restricted it to a role, ask them for access. You do not need to install this project or get a bot token.

## Starting again next time

Double-click **Start VLC Remote.cmd**, start your Discord screen share and use the existing remote panel. The saved playlist and host lock survive restarts; reopen temporary Shows/Playlist editors. To stop the bot, focus its console and press **Ctrl+C**. Close VLC separately when finished.

## If something does not work

| Problem | What to check |
| --- | --- |
| Setup cannot find `setup.ps1` | Open PowerShell from the extracted folder containing that file. |
| Python is not recognized | Install a tested Python version, enable its PATH option and open a new PowerShell window. |
| `.env` is missing | Run setup successfully first; edit the generated file rather than renaming the template. |
| Bot stays offline | Read the launcher error. Check the token in `.env` and save it. Keep the launcher open. |
| Slash commands are missing | Check the server ID, `applications.commands` scope, bot login and channel/integration permissions. Use your server, not a DM. |
| Only the host can use controls | Leave `CONTROL_ROLE_ID` empty for shared access, restart after editing, run `/vlc unlock` and check channel permissions. |
| VLC does not respond | From the project folder run `powershell -ExecutionPolicy Bypass -File .\check-vlc.ps1`. Make sure you are using the controlled VLC window. |
| VLC rejects its password | Close the controlled VLC window and relaunch it to pick up the current `.env` password. |
| Shows is empty | Check that `MEDIA_ROOT` exists and contains supported videos. Reopen Shows; restart after configuration changes. |
| An editor stops responding | Run `/vlc shows` or `/vlc playlist` again to open a fresh editor. |
| Friends hear no audio | Check audio in Discord's sharing settings and confirm VLC is audible on the host PC. |

For more detail, see the [command reference and troubleshooting](../README.md). Keep your `.env` private when requesting help; share the error text without tokens or passwords.
