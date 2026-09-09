import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
from aiohttp import web
import discord

from bot import RemoteBot, RemoteView, SeekModal, VlcCommands, help_embed
from config import Settings, local_vlc_url
from controller import Actor, ControlError, SharedController, StateStore, VlcClient
from setup_config import prepare_env
from instance_lock import single_instance


class RemoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = {'state': 'paused', 'time': 100, 'length': 600,
                      'information': {'category': {'meta': {'filename': 'C:\\private\\movie.mp4'}}}}
        self.commands = []
        self.response_status = 200
        self.invalid_json = False
        self.headers = []
        app = web.Application()
        app.router.add_get('/requests/status.json', self.handle)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await self.site.start()
        port = self.site._server.sockets[0].getsockname()[1]
        self.session = aiohttp.ClientSession()
        self.vlc = VlcClient(self.session, f'http://127.0.0.1:{port}', 'test-password')
        self.settings = Settings('fake-token', 111111111111111111, 222222222222222222,
                                 'test-password', host_user_id=333333333333333333)
        self.path = Path(self.temp.name) / 'state.json'
        self.store = StateStore(self.path, 'test-scope')
        self.control = SharedController(self.vlc, self.settings, self.store, cooldown=0)
        self.host = self.actor(self.settings.host_user_id)
        self.guest = self.actor(444444444444444444)

    def actor(self, user_id, **kwargs):
        return Actor(user_id, kwargs.get('guild_id', self.settings.guild_id),
                     kwargs.get('channel_id', self.settings.channel_id),
                     kwargs.get('roles', frozenset()), kwargs.get('manage_guild', False))

    async def handle(self, request):
        self.headers.append(request.headers.get('Authorization'))
        if self.response_status != 200:
            return web.Response(status=self.response_status)
        if self.invalid_json:
            return web.Response(text='not json')
        command = request.query.get('command')
        if command:
            self.commands.append(dict(request.query))
            if command in ('pl_forceresume', 'pl_play'):
                self.state['state'] = 'playing'
            elif command == 'pl_forcepause':
                self.state['state'] = 'paused'
            elif command == 'seek':
                self.state['time'] = int(request.query['val'])
        await asyncio.sleep(0.005)
        return web.json_response(self.state)

    async def asyncTearDown(self):
        await self.session.close()
        await self.runner.cleanup()
        self.temp.cleanup()

    async def test_pause_and_play_are_idempotent(self):
        for _ in range(2):
            self.assertEqual((await self.control.execute(self.guest, 'pause')).state, 'paused')
        for _ in range(2):
            self.assertEqual((await self.control.execute(self.guest, 'play')).state, 'playing')
        self.assertNotIn('pl_pause', [command['command'] for command in self.commands])

    async def test_play_starts_stopped_playlist(self):
        self.state['state'] = 'stopped'
        self.assertEqual((await self.control.execute(self.guest, 'play')).state, 'playing')
        self.assertEqual(self.commands[0]['command'], 'pl_play')

    async def test_concurrent_skips_accumulate(self):
        await asyncio.gather(*(self.control.execute(self.actor(100 + index), 'seek', 10) for index in range(5)))
        self.assertEqual(self.state['time'], 150)
        self.assertEqual([command['val'] for command in self.commands], ['110', '120', '130', '140', '150'])

    async def test_seek_clamps_at_both_boundaries(self):
        self.assertEqual((await self.control.execute(self.guest, 'seek', -3600)).seconds, 0)
        self.assertEqual((await self.control.execute(self.guest, 'seek', 3600)).seconds, 599)

    async def test_invalid_and_unseekable_requests_do_not_mutate(self):
        for seconds in (0, 3601, -3601, 1.2, '10', True, None):
            with self.assertRaises(ControlError):
                await self.control.execute(self.guest, 'seek', seconds)
        self.state['length'] = 0
        with self.assertRaises(ControlError):
            await self.control.execute(self.guest, 'seek', -10)
        self.assertFalse(self.commands)

    async def test_guild_channel_and_dm_boundaries(self):
        for actor in (self.actor(4, guild_id=None, channel_id=None),
                      self.actor(4, guild_id=999), self.actor(4, channel_id=999)):
            with self.assertRaises(ControlError):
                await self.control.execute(actor, 'pause')
        self.assertFalse(self.headers)

    async def test_host_lock_persists_and_blocks_guest_but_allows_status(self):
        await self.control.execute(self.host, 'lock')
        self.assertTrue(StateStore(self.path, 'test-scope').locked)
        with self.assertRaises(ControlError):
            await self.control.execute(self.guest, 'play')
        self.assertEqual((await self.control.execute(self.guest, 'status')).state, 'paused')
        self.assertEqual((await self.control.execute(self.host, 'play')).state, 'playing')
        with self.assertRaises(ControlError):
            await self.control.execute(self.guest, 'unlock')
        await self.control.execute(self.actor(7, manage_guild=True), 'unlock')
        self.assertFalse(StateStore(self.path, 'test-scope').locked)

    async def test_lock_does_not_depend_on_vlc_availability(self):
        self.response_status = 503
        await self.control.execute(self.host, 'lock')
        self.assertTrue(self.store.locked)

    async def test_role_restriction_and_host_bypass(self):
        from dataclasses import replace
        self.control.settings = replace(self.settings, control_role_id=777)
        with self.assertRaises(ControlError):
            await self.control.execute(self.guest, 'pause')
        await self.control.execute(self.actor(8, roles=frozenset([777])), 'pause')
        await self.control.execute(self.host, 'pause')

    async def test_cooldown_prevents_duplicate_click(self):
        self.control.cooldown = 1
        await self.control.execute(self.guest, 'seek', 10)
        with self.assertRaises(ControlError):
            await self.control.execute(self.guest, 'seek', 10)
        self.assertEqual(self.state['time'], 110)

    async def test_error_messages_are_safe(self):
        self.response_status = 401
        with self.assertRaisesRegex(ControlError, 'rejected the password') as raised:
            await self.vlc.status()
        self.assertNotIn('test-password', str(raised.exception))
        self.response_status = 302
        with self.assertRaises(ControlError):
            await self.vlc.status()
        self.response_status, self.invalid_json = 200, True
        with self.assertRaisesRegex(ControlError, 'unreadable'):
            await self.vlc.status()

    async def test_basic_auth_and_path_redaction(self):
        status = await self.vlc.status()
        self.assertEqual(status.title, 'movie.mp4')
        self.assertEqual(self.headers[0], 'Basic OnRlc3QtcGFzc3dvcmQ=')

    async def test_persistent_view_and_slash_command_schema(self):
        view = RemoteView(None)
        self.assertTrue(view.is_persistent())
        self.assertEqual(len({button.custom_id for button in view.children}), 15)
        self.assertEqual(len(view.to_components()), 3)
        self.assertEqual({command.name for command in VlcCommands(None).commands},
                         {'panel', 'play', 'pause', 'rewind', 'forward', 'status', 'lock', 'unlock',
                          'shows', 'playlist', 'next', 'previous', 'help'})
        self.assertEqual(SeekModal(None).to_dict()['title'], 'Skip by seconds')
        view.stop()

    def interaction(self, actor=None):
        actor = actor or self.guest
        return SimpleNamespace(
            user=SimpleNamespace(id=actor.user_id, roles=[SimpleNamespace(id=role) for role in actor.roles]),
            guild_id=actor.guild_id, channel_id=actor.channel_id,
            permissions=SimpleNamespace(manage_guild=actor.manage_guild),
            response=SimpleNamespace(defer=AsyncMock(), send_modal=AsyncMock(), send_message=AsyncMock(),
                                     is_done=lambda: False),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    def ui_bot(self):
        ui = SimpleNamespace(control=self.control, store=self.store, settings=self.settings,
                             panel_lock=asyncio.Lock(), last_embed=None,
                             refresh_panel=AsyncMock(), embed=AsyncMock(return_value=discord.Embed(title='Remote')),
                             channel=SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=12345)),
                                                     fetch_message=AsyncMock(), get_partial_message=Mock()))

        async def perform(interaction, action, seconds=None):
            await RemoteBot.perform(ui, interaction, action, seconds)

        ui.perform = perform
        async def show_help(interaction):
            await RemoteBot.show_help(ui, interaction)

        ui.show_help = show_help
        ui.view = RemoteView(ui)
        self.addCleanup(ui.view.stop)
        return ui

    async def test_playback_buttons_reach_vlc(self):
        ui = self.ui_bot()
        expected = [('Back 30s', 70), ('Back 10s', 60), ('Forward 10s', 70), ('Forward 30s', 100)]
        for label, position in expected:
            interaction = self.interaction()
            button = next(button for button in ui.view.children if button.label == label)
            await button.callback(interaction)
            self.assertEqual(self.state['time'], position)
            interaction.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)
        for label, state in [('Play', 'playing'), ('Pause', 'paused'), ('Status', 'paused')]:
            button = next(button for button in ui.view.children if button.label == label)
            await button.callback(self.interaction())
            self.assertEqual(self.state['state'], state)
        self.assertEqual(ui.refresh_panel.await_count, 7)

    async def test_help_slash_and_button_respond_publicly_without_vlc(self):
        ui = self.ui_bot()
        self.response_status = 503
        await self.control.execute(self.host, 'lock')
        commands = VlcCommands(ui)
        interaction = self.interaction()
        await commands.get_command('help').callback(commands, interaction)
        payload = interaction.response.send_message.call_args.kwargs
        self.assertFalse(payload['ephemeral'])
        self.assertEqual(payload['embed'].title, 'GroupVid help')
        button = next(button for button in ui.view.children if button.label == 'Help')
        click = self.interaction()
        await button.callback(click)
        click.response.send_message.assert_awaited_once()
        self.assertFalse(self.headers)
        ui.refresh_panel.assert_not_awaited()

    async def test_help_routes_people_from_other_channels_without_role(self):
        from dataclasses import replace
        ui = self.ui_bot()
        ui.settings = replace(self.settings, control_role_id=777)
        self.control.settings = ui.settings
        interaction = self.interaction(self.actor(8, channel_id=999))
        await ui.show_help(interaction)
        embed = interaction.response.send_message.call_args.kwargs['embed']
        self.assertIn(str(self.settings.channel_id), embed.description)
        self.assertIn('control role', str(embed.to_dict()))

    async def test_show_and_playlist_commands_open_public_shared_views(self):
        ui = self.ui_bot()
        ui.library = SimpleNamespace(shelves={}, episodes={}, scan=Mock())
        ui.draft = SimpleNamespace(rows=[], revision=0)
        for section in ('shows', 'playlist'):
            interaction = self.interaction()
            await RemoteBot.show_media(ui, interaction, section)
            interaction.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)
            view = interaction.edit_original_response.call_args.kwargs['view']
            self.addCleanup(view.stop)
            self.assertTrue(await view.interaction_check(self.interaction(self.actor(8))))
        self.assertFalse(self.headers)

    async def test_public_playback_reply_identifies_requested_skip(self):
        interaction = self.interaction()
        await self.ui_bot().perform(interaction, 'seek', -15)
        interaction.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)
        message = interaction.edit_original_response.call_args.kwargs['content']
        self.assertIn('Rewind 15 seconds', message)
        self.assertIn('1:25', message)
        self.assertEqual(self.state['time'], 85)

    async def test_help_documents_all_commands_and_fits_discord_limits(self):
        embed = help_embed(self.settings)
        rendered = embed.description + '\n' + '\n'.join(field.value for field in embed.fields)
        for command in VlcCommands(None).commands:
            self.assertIn('/vlc ' + command.name, rendered)
        self.assertIn('/help', rendered)
        self.assertIn('/vlc rewind seconds:15', rendered)
        self.assertIn('Start playlist from beginning', rendered)
        self.assertLessEqual(len(embed), 6000)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        self.assertNotIn(self.settings.token, rendered)
        self.assertNotIn(self.settings.vlc_password, rendered)

    async def test_custom_skip_opens_and_submits_modal(self):
        ui = self.ui_bot()
        interaction = self.interaction()
        button = next(button for button in ui.view.children if button.label == 'Custom skip')
        await button.callback(interaction)
        modal = interaction.response.send_modal.call_args.args[0]
        self.addCleanup(modal.stop)
        modal.seconds._value = '-45'
        await modal.on_submit(self.interaction())
        self.assertEqual(self.state['time'], 55)

    async def test_modal_rechecks_lock_and_rejects_bad_input(self):
        ui = self.ui_bot()
        modal = SeekModal(ui)
        self.addCleanup(modal.stop)
        for value in ('nonsense', '0', '3601'):
            modal.seconds._value = value
            await modal.on_submit(self.interaction())
        self.assertFalse(self.commands)
        await self.control.execute(self.host, 'lock')
        modal.seconds._value = '-45'
        interaction = self.interaction()
        await modal.on_submit(interaction)
        self.assertIn('locked', interaction.response.send_message.call_args.args[0])
        self.assertTrue(interaction.response.send_message.call_args.kwargs['ephemeral'])
        self.assertFalse(self.commands)

    async def test_lock_unlock_buttons_and_guest_denial(self):
        ui = self.ui_bot()
        lock = next(button for button in ui.view.children if button.label == 'Lock')
        unlock = next(button for button in ui.view.children if button.label == 'Unlock')
        await lock.callback(self.interaction(self.host))
        self.assertTrue(self.store.locked)
        await unlock.callback(self.interaction())
        self.assertTrue(self.store.locked)
        await unlock.callback(self.interaction(self.host))
        self.assertFalse(self.store.locked)

    async def test_slash_skips_use_correct_direction(self):
        commands = VlcCommands(self.ui_bot())
        await commands.get_command('rewind').callback(commands, self.interaction(), 45)
        self.assertEqual(self.state['time'], 55)
        await commands.get_command('forward').callback(commands, self.interaction(), 90)
        self.assertEqual(self.state['time'], 145)

    async def test_panel_created_once_and_reused(self):
        ui = self.ui_bot()
        await RemoteBot.show_panel(ui, self.interaction())
        ui.channel.send.assert_not_awaited()
        await RemoteBot.show_panel(ui, self.interaction(self.host))
        self.assertEqual(self.store.panel_id, 12345)
        guest = self.interaction()
        await RemoteBot.show_panel(ui, guest)
        guest.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)
        ui.channel.send.assert_awaited_once()
        self.assertIn('/12345', guest.edit_original_response.call_args.kwargs['content'])
        self.assertEqual(StateStore(self.path, 'test-scope').panel_id, 12345)

    async def test_deleted_panel_is_cleared_without_losing_lock(self):
        ui = self.ui_bot()
        self.store.save(locked=True, panel_id=12345)
        message = SimpleNamespace(edit=AsyncMock(side_effect=discord.NotFound(
            SimpleNamespace(status=404, reason='Not Found'), 'Unknown Message')))
        ui.channel.get_partial_message.return_value = message
        await RemoteBot.refresh_panel(ui)
        self.assertIsNone(self.store.panel_id)
        self.assertTrue(self.store.locked)

    async def test_panel_failure_does_not_report_failed_playback(self):
        ui = self.ui_bot()
        ui.refresh_panel.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason='Forbidden'), 'No access')
        interaction = self.interaction()
        with self.assertLogs('vlc_remote', level='WARNING'):
            await ui.perform(interaction, 'seek', 10)
        self.assertEqual(self.state['time'], 110)
        self.assertEqual(len(self.commands), 1)
        self.assertIn('1:50', interaction.edit_original_response.call_args.kwargs['content'])

    async def test_startup_registers_persistent_view_and_guild_commands(self):
        with patch('bot.ROOT', Path(self.temp.name)):
            bot = RemoteBot(self.settings)
        async with bot:
            channel = Mock(spec=discord.TextChannel)
            channel.guild = SimpleNamespace(id=self.settings.guild_id)
            bot.fetch_channel = AsyncMock(return_value=channel)
            bot.tree.sync = AsyncMock()
            with patch.object(bot.refresh_loop, 'start') as start_refresh:
                await bot.setup_hook()
                start_refresh.assert_called_once()
            bot.tree.sync.assert_awaited_once()
            self.assertEqual(bot.tree.sync.call_args.kwargs['guild'].id, self.settings.guild_id)
            self.assertTrue(bot.view.is_persistent())
            schema = bot.tree.get_command('vlc', guild=discord.Object(id=self.settings.guild_id)).to_dict(bot.tree)
            self.assertEqual(len(schema['options']), 13)
            help_command = bot.tree.get_command('help', guild=discord.Object(id=self.settings.guild_id))
            self.assertIsNotNone(help_command)
            help_interaction = self.interaction()
            await help_command.callback(help_command.binding, help_interaction)
            self.assertFalse(help_interaction.response.send_message.call_args.kwargs['ephemeral'])
        self.assertTrue(bot.session.closed)


class ConfigurationTests(unittest.TestCase):
    def test_duplicate_bot_start_is_rejected_and_lock_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bot.lock'
            with single_instance(path):
                with self.assertRaisesRegex(SystemExit, 'already running'):
                    with single_instance(path):
                        pass
            with single_instance(path):
                pass

    def test_only_loopback_urls_accepted(self):
        for url in ('http://example.com', 'https://127.0.0.1', 'http://127.0.0.1:80/a',
                    'http://user:secret@127.0.0.1', 'http://127.0.0.1:99999',
                    'http://127.0.0.1?x=y'):
            with self.assertRaises(ValueError):
                local_vlc_url(url)
        self.assertEqual(local_vlc_url('http://127.0.0.1:8080/'), 'http://127.0.0.1:8080')

    def test_settings_secrets_not_in_repr(self):
        settings = Settings('fake-token', 1, 2, 'private-password')
        self.assertNotIn('fake-token', repr(settings))
        self.assertNotIn('private-password', repr(settings))

    def test_corrupt_state_is_not_silently_unlocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            for data in ('invalid', '[]', json.dumps({'scope': 'same', 'locked': 'true'})):
                path.write_text(data)
                with self.assertRaises(ValueError):
                    StateStore(path, 'same')

    def test_prepare_creates_actual_env_without_overwriting(self):
        from dotenv import dotenv_values
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            with patch('builtins.print'):
                prepare_env(path)
            values = dotenv_values(path)
            self.assertGreaterEqual(len(values['VLC_PASSWORD']), 32)
            self.assertEqual(values['DISCORD_TOKEN'], '')
            original = path.read_bytes() + b'# preserve user edits\n'
            path.write_bytes(original)
            with patch('builtins.print'):
                prepare_env(path)
            self.assertEqual(path.read_bytes(), original)

    def test_local_env_ignores_ambient_credentials_and_supports_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('DISCORD_TOKEN=local-token\nDISCORD_GUILD_ID=111111111111111111\n'
                            'DISCORD_CHANNEL_ID=222222222222222222\nVLC_PASSWORD=literal-${SECRET}\n',
                            encoding='utf-8-sig')
            with patch('config.ROOT', Path(directory)), patch.dict('os.environ', {'DISCORD_TOKEN': 'other-bot'}):
                settings = Settings.read()
            self.assertEqual(settings.token, 'local-token')
            self.assertEqual(settings.vlc_password, 'literal-${SECRET}')


if __name__ == '__main__':
    unittest.main()
