"""Shared VLC controls delivered through Discord's official bot API."""
import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from config import ROOT, Settings
from controller import Actor, ControlError, SharedController, StateStore, VlcClient
from library import LibraryController, MediaLibrary, PlaylistDraft
from library_ui import PlaylistView, ShowsView
from instance_lock import single_instance

log = logging.getLogger('vlc_remote')


def actor_for(interaction):
    return Actor(interaction.user.id, interaction.guild_id, interaction.channel_id,
                 frozenset(role.id for role in getattr(interaction.user, 'roles', [])),
                 interaction.permissions.manage_guild)


def clock_text(seconds):
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


async def private_reply(interaction, message):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
    else:
        await interaction.response.send_message(message, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


def help_embed(settings):
    embed = discord.Embed(
        title='GroupVid help', color=0xE87924,
        description=f'Control the host\'s VLC while watching their Discord screen share.\n'
                    f'Use playback commands in <#{settings.channel_id}>. '
                    'Start with `/vlc panel` to open the shared buttons.')
    embed.add_field(name='Play, pause and skip', inline=False, value=(
        '`/vlc play` — play or resume\n'
        '`/vlc pause` — pause\n'
        '`/vlc rewind seconds:15` — go back 15 seconds\n'
        '`/vlc forward seconds:15` — go forward 15 seconds\n'
        '`/vlc status` — check playback and refresh the panel\n'
        'Skip commands accept 1–3600 whole seconds. Buttons skip 10 or 30 seconds; '
        '**Custom skip** accepts `-15` to rewind or `15` to move forward.'))
    embed.add_field(name='Shows and playlist order', inline=False, value=(
        '`/vlc shows` — choose a show/version and episode. Use **Add episode** or '
        '**Add this version in order**. **Play episode now** replaces the running VLC queue.\n'
        '`/vlc playlist` — select an entry, then move it up/down, move it to a position, or remove it. '
        'Edits save automatically and leave current playback running.\n'
        '**Start playlist from beginning** replaces VLC\'s queue and applies your saved order. '
        '**Clear saved playlist** clears entries after confirmation; it never deletes videos.\n'
        '`/vlc next` / `/vlc previous` — change episodes in the running VLC queue.'))
    access = ('The configured control role is required for playback.' if settings.control_role_id
              else 'Everyone with access to the control channel can use playback controls.')
    embed.add_field(name='Host controls', inline=False, value=(
        f'{access}\nThe configured host and members with **Manage Server** can create the panel '
        'with `/vlc panel`, lock it with `/vlc lock`, and restore shared control with `/vlc unlock`. '
        'While locked, others can still read Status and Help.'))
    embed.add_field(name='If something stops working', inline=False, value=(
        'Keep the bot and controlled VLC window running on the host PC. '
        'For a timed-out skip, check `/vlc status` before retrying. '
        'Reopen `/vlc shows` to rescan videos, or `/vlc playlist` to refresh an expired editor. '
        'Seeking requires a seekable video.\n'
        '`/help` or `/vlc help` shares this guide with the channel; it also works while VLC is offline.'))
    return embed


class SeekModal(discord.ui.Modal, title='Skip by seconds'):
    seconds = discord.ui.TextInput(label='Seconds: negative rewinds, positive forwards',
                                  placeholder='-45 or +90', min_length=1, max_length=6)

    def __init__(self, bot):
        super().__init__(timeout=180)
        self.bot = bot

    async def on_submit(self, interaction):
        try:
            value = int(str(self.seconds).strip())
        except ValueError:
            await private_reply(interaction, 'Enter whole seconds, such as -45 or +90.')
            return
        await self.bot.perform(interaction, 'seek', value)

    async def on_error(self, interaction, error):
        log.error('Custom skip failed (%s).', type(error).__name__)
        await private_reply(interaction, 'The custom skip failed. Check Status before trying again.')


class RemoteView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        controls = [
            ('Back 30s', 'seek', -30, 0, discord.ButtonStyle.secondary),
            ('Back 10s', 'seek', -10, 0, discord.ButtonStyle.secondary),
            ('Play', 'play', None, 0, discord.ButtonStyle.success),
            ('Pause', 'pause', None, 0, discord.ButtonStyle.primary),
            ('Forward 10s', 'seek', 10, 0, discord.ButtonStyle.secondary),
            ('Forward 30s', 'seek', 30, 1, discord.ButtonStyle.secondary),
            ('Custom skip', 'custom', None, 1, discord.ButtonStyle.secondary),
            ('Status', 'status', None, 1, discord.ButtonStyle.secondary),
            ('Lock', 'lock', None, 1, discord.ButtonStyle.danger),
            ('Unlock', 'unlock', None, 1, discord.ButtonStyle.secondary),
            ('Shows', 'shows', None, 2, discord.ButtonStyle.primary),
            ('Playlist', 'playlist', None, 2, discord.ButtonStyle.primary),
            ('Previous episode', 'previous', None, 2, discord.ButtonStyle.secondary),
            ('Next episode', 'next', None, 2, discord.ButtonStyle.secondary),
            ('Help', 'help', None, 2, discord.ButtonStyle.secondary),
        ]
        for label, action, seconds, row, style in controls:
            button = discord.ui.Button(label=label, row=row, style=style,
                                       custom_id=f'vlc:v1:{action}:{seconds}')

            async def clicked(interaction, action=action, seconds=seconds):
                if action == 'help':
                    await bot.show_help(interaction)
                elif action in ('shows', 'playlist'):
                    await bot.show_media(interaction, action)
                elif action == 'custom':
                    try:
                        bot.control.authorize(actor_for(interaction), changing=True)
                        await interaction.response.send_modal(SeekModal(bot))
                    except ControlError as error:
                        await private_reply(interaction, str(error))
                else:
                    await bot.perform(interaction, action, seconds)

            button.callback = clicked
            self.add_item(button)

    async def on_error(self, interaction, error, item):
        log.error('Button failed (%s).', type(error).__name__)
        await private_reply(interaction, 'The control failed. Check Status before trying again.')


@app_commands.guild_only()
class VlcCommands(app_commands.Group, name='vlc', description='Control the shared VLC screen share'):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    @app_commands.command(description='Show playback commands, playlist instructions and troubleshooting')
    async def help(self, interaction: discord.Interaction):
        await self.bot.show_help(interaction)

    @app_commands.command(description='Create or find the shared remote (host creates it)')
    async def panel(self, interaction: discord.Interaction):
        await self.bot.show_panel(interaction)

    @app_commands.command(description='Play or resume VLC')
    async def play(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'play')

    @app_commands.command(description='Pause VLC')
    async def pause(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'pause')

    @app_commands.command(description='Rewind by a chosen number of seconds')
    async def rewind(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 1, 3600] = 10):
        await self.bot.perform(interaction, 'seek', -seconds)

    @app_commands.command(description='Skip forward by a chosen number of seconds')
    async def forward(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 1, 3600] = 10):
        await self.bot.perform(interaction, 'seek', seconds)

    @app_commands.command(description='Show current playback and update the shared remote')
    async def status(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'status')

    @app_commands.command(description='Let only the host and server managers control VLC')
    async def lock(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'lock')

    @app_commands.command(description='Restore shared VLC control')
    async def unlock(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'unlock')

    @app_commands.command(description='Browse available shows and add episodes to a playlist')
    async def shows(self, interaction: discord.Interaction):
        await self.bot.show_media(interaction, 'shows')

    @app_commands.command(description='Arrange, remove and play your saved episode playlist')
    async def playlist(self, interaction: discord.Interaction):
        await self.bot.show_media(interaction, 'playlist')

    @app_commands.command(description='Play the next episode in the running VLC playlist')
    async def next(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'next')

    @app_commands.command(description='Play the previous episode in the running VLC playlist')
    async def previous(self, interaction: discord.Interaction):
        await self.bot.perform(interaction, 'previous')


class RemoteBot(discord.Client):
    def __init__(self, settings):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.store = StateStore(ROOT / '.state/session.json', f'{settings.guild_id}:{settings.channel_id}')
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(VlcCommands(self), guild=discord.Object(id=settings.guild_id))
        self.tree.add_command(app_commands.Command(name='help',
                              description='How to use GroupVid playback controls and playlists',
                              callback=self.show_help), guild=discord.Object(id=settings.guild_id))
        self.tree.on_error = self.command_error
        self.session = None
        self.control = None
        self.channel = None
        self.panel_lock = asyncio.Lock()
        self.last_embed = None
        self.library = MediaLibrary(settings.media_root)
        self.draft = PlaylistDraft(ROOT / '.state/playlist.json')

    async def setup_hook(self):
        self.session = aiohttp.ClientSession(trust_env=False)
        self.control = SharedController(VlcClient(self.session, self.settings.vlc_url, self.settings.vlc_password),
                                        self.settings, self.store)
        self.media = LibraryController(self.control, self.library, self.draft)
        try:
            await asyncio.to_thread(self.library.scan)
        except ControlError as error:
            log.warning('%s', error)
        self.view = RemoteView(self)
        self.add_view(self.view)
        self.channel = await self.fetch_channel(self.settings.channel_id)
        if (not isinstance(self.channel, (discord.TextChannel, discord.VoiceChannel))
                or self.channel.guild.id != self.settings.guild_id):
            raise ValueError('Choose a server text channel or voice-channel chat belonging to DISCORD_GUILD_ID.')
        await self.tree.sync(guild=discord.Object(id=self.settings.guild_id))
        self.refresh_loop.start()

    async def on_ready(self):
        log.info('Connected as %s. Use /vlc panel in the configured channel.', self.user.name)

    async def show_help(self, interaction: discord.Interaction):
        # Informational help does not require a role, host access, cooldown or VLC
        # connection. In other channels of the same server it points to the remote.
        if interaction.guild_id != self.settings.guild_id:
            await private_reply(interaction, 'GroupVid help is available in the configured server.')
            return
        await interaction.response.send_message(embed=help_embed(self.settings), ephemeral=False,
                                                allowed_mentions=discord.AllowedMentions.none())

    async def show_media(self, interaction, section):
        try:
            self.control.authorize(actor_for(interaction))
        except ControlError as error:
            await private_reply(interaction, str(error))
            return
        await interaction.response.defer(ephemeral=False, thinking=True)
        try:
            if section == 'shows':
                await asyncio.to_thread(self.library.scan)
                view = ShowsView(self, interaction.user.id)
            else:
                view = PlaylistView(self, interaction.user.id)
            await interaction.edit_original_response(embed=view.embed(), view=view)
        except ControlError as error:
            await interaction.edit_original_response(content=str(error))

    async def command_error(self, interaction, error):
        log.error('Slash command failed (%s).', type(error).__name__)
        await private_reply(interaction, 'The command failed. Check Status before trying again, or check the bot console.')

    async def embed(self):
        try:
            status = await self.control.snapshot()
            embed = discord.Embed(title='VLC shared remote', color=0xE87924)
            embed.description = discord.utils.escape_markdown(discord.utils.escape_mentions(status.title))
            embed.add_field(name='Playback', value=status.state.title())
            position = clock_text(status.seconds)
            if status.duration:
                position += ' / ' + clock_text(status.duration)
            embed.add_field(name='Position', value=position)
        except ControlError as error:
            embed = discord.Embed(title='VLC shared remote', description=str(error), color=0x808080)
        access = 'Locked — host / Manage Server only' if self.store.locked else 'Shared control'
        if not self.store.locked and self.settings.control_role_id:
            access += ' — control role required'
        embed.add_field(name='Access', value=access, inline=False)
        embed.set_footer(text='Refreshes every 10s • Watch the host’s VLC screen share')
        return embed

    async def refresh_panel(self):
        async with self.panel_lock:
            if not self.store.panel_id:
                return
            embed = await self.embed()
            serialized = embed.to_dict()
            if serialized == self.last_embed:
                return
            try:
                await self.channel.get_partial_message(self.store.panel_id).edit(embed=embed, view=self.view)
                self.last_embed = serialized
            except discord.NotFound:
                self.store.save(locked=self.store.locked, panel_id=None)
                self.last_embed = None

    async def perform(self, interaction, action, seconds=None):
        try:
            self.control.authorize(actor_for(interaction), changing=action != 'status',
                                   host_only=action in ('lock', 'unlock'))
        except ControlError as error:
            await private_reply(interaction, str(error))
            return
        await interaction.response.defer(ephemeral=False, thinking=True)
        try:
            status = await self.control.execute(actor_for(interaction), action, seconds)
            if action in ('lock', 'unlock'):
                message = 'Remote locked to the host and server managers.' if action == 'lock' else 'Shared control restored.'
            else:
                title = discord.utils.escape_markdown(discord.utils.escape_mentions(status.title))
                action_label = {
                    'play': 'Play', 'pause': 'Pause', 'status': 'Status',
                    'next': 'Next episode', 'previous': 'Previous episode',
                }.get(action, 'Playback')
                if action == 'seek':
                    action_label = f'{"Rewind" if seconds < 0 else "Forward"} {abs(seconds)} seconds'
                message = f'{action_label} • {status.state.title()} • {clock_text(status.seconds)} • {title}'
            await interaction.edit_original_response(content=message)
        except ControlError as error:
            await interaction.edit_original_response(content=str(error))
            return
        # Playback already succeeded: a Discord panel failure must not invite a repeat seek.
        try:
            await self.refresh_panel()
        except (discord.HTTPException, OSError):
            log.warning('Playback completed, but the shared panel could not refresh.')

    async def show_panel(self, interaction):
        try:
            self.control.authorize(actor_for(interaction))
        except ControlError as error:
            await private_reply(interaction, str(error))
            return
        await interaction.response.defer(ephemeral=False, thinking=True)
        try:
            self.control.authorize(actor_for(interaction))
            async with self.panel_lock:
                if self.store.panel_id:
                    try:
                        await self.channel.fetch_message(self.store.panel_id)
                    except discord.NotFound:
                        self.store.save(locked=self.store.locked, panel_id=None)
                if not self.store.panel_id:
                    self.control.authorize(actor_for(interaction), host_only=True)
                    embed = await self.embed()
                    message = await self.channel.send(embed=embed, view=self.view)
                    self.store.save(locked=self.store.locked, panel_id=message.id)
                    self.last_embed = embed.to_dict()
                url = f'https://discord.com/channels/{self.settings.guild_id}/{self.settings.channel_id}/{self.store.panel_id}'
            await interaction.edit_original_response(content=f'[Open the shared VLC remote]({url})')
        except ControlError as error:
            await interaction.edit_original_response(content=str(error))
        except (discord.HTTPException, OSError):
            await interaction.edit_original_response(content='Could not save or open the panel. Check View Channel, Send Messages, Embed Links, and Read Message History permissions, plus local folder access.')

    @tasks.loop(seconds=10)
    async def refresh_loop(self):
        try:
            await self.refresh_panel()
        except (discord.HTTPException, OSError):
            log.warning('Panel refresh failed; check channel permissions and local folder access.')

    @refresh_loop.before_loop
    async def before_refresh(self):
        await self.wait_until_ready()

    async def close(self):
        self.refresh_loop.cancel()
        if self.session:
            await self.session.close()
        await super().close()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    try:
        settings = Settings.read()
        with single_instance(ROOT / '.state/bot.lock'):
            RemoteBot(settings).run(settings.token, log_handler=None)
    except discord.LoginFailure:
        raise SystemExit('Discord rejected the bot token. Run setup.ps1 to enter a fresh token locally.') from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except discord.Forbidden:
        raise SystemExit('Discord denied access. Install the bot in the configured server and grant its channel permissions.') from None
    except discord.HTTPException:
        raise SystemExit('Discord could not finish startup. Check server/channel IDs, network access, and the bot installation.') from None


if __name__ == '__main__':
    main()
