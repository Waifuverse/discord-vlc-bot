import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from config import Settings
from controller import Actor, ControlError, Playback, SharedController, StateStore
from library import LibraryController, MediaLibrary, PlaylistDraft
from library_ui import MoveModal, PlaylistView, ShowsView


class LibraryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.videos = self.root / 'Media'
        (self.videos / 'ExampleShow').mkdir(parents=True)
        for name in ['ExampleShow_10_Subbed.mp4', 'ExampleShow_2_Subbed.mp4', 'ExampleShow_1_Subbed.mp4',
                     'ExampleShow_2_Dubbed.mp4', 'notes.txt']:
            (self.videos / 'ExampleShow' / name).write_bytes(b'test')
        self.library = MediaLibrary(self.videos).scan()
        self.draft = PlaylistDraft(self.root / 'draft.json')
        settings = Settings('test', 1, 2, 'test', host_user_id=3)
        self.vlc = SimpleNamespace(request=AsyncMock(return_value={}),
                                   status=AsyncMock(return_value=Playback('playing', 0, 300, 'episode', 10)),
                                   playlist=AsyncMock(return_value=[{'id': 10}]))
        self.control = SharedController(self.vlc, settings, StateStore(self.root / 'session.json', 'test'), cooldown=0)
        self.media = LibraryController(self.control, self.library, self.draft)
        self.host, self.guest = Actor(3, 1, 2), Actor(4, 1, 2)
        self.bot = SimpleNamespace(media=self.media, control=self.control, library=self.library, draft=self.draft)

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def add_subbed(self):
        await self.media.edit(self.guest, 'add_shelf', shelf='ExampleShow / Subbed')

    def episode_numbers(self):
        return [self.library.episodes[row['episode']].relative_path for row in self.draft.rows]

    def interaction(self, user_id=4):
        return SimpleNamespace(user=SimpleNamespace(id=user_id, roles=[]), guild_id=1, channel_id=2,
                               permissions=SimpleNamespace(manage_guild=False),
                               response=SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock(),
                                                        send_message=AsyncMock(), send_modal=AsyncMock(), is_done=lambda: False),
                               followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())

    def track_view(self, view):
        self.addCleanup(view.stop)
        return view

    async def test_versions_and_natural_episode_order(self):
        self.assertEqual(len(self.library.episodes), 4)
        await self.add_subbed()
        self.assertEqual(self.episode_numbers(), ['ExampleShow/ExampleShow_1_Subbed.mp4', 'ExampleShow/ExampleShow_2_Subbed.mp4', 'ExampleShow/ExampleShow_10_Subbed.mp4'])

    async def test_saved_order_remove_and_clear_persist(self):
        await self.add_subbed()
        await self.media.edit(self.guest, 'move', row_id=self.draft.rows[2]['id'], position=1)
        self.assertIn('_10_', self.episode_numbers()[0])
        await self.media.edit(self.guest, 'remove', row_id=self.draft.rows[1]['id'])
        self.assertEqual(len(self.draft.rows), 2)
        restored = PlaylistDraft(self.draft.path)
        self.assertEqual(restored.rows, self.draft.rows)
        await self.media.edit(self.guest, 'clear')
        self.assertEqual(PlaylistDraft(self.draft.path).rows, [])
        self.assertEqual(len(list((self.videos / 'ExampleShow').glob('*.mp4'))), 4)
        self.vlc.status.assert_not_awaited()

    async def test_stale_editor_cannot_move_or_start(self):
        revision = self.draft.revision
        await self.add_subbed()
        with self.assertRaisesRegex(ControlError, 'changed'):
            await self.media.edit(self.guest, 'clear', revision=revision)
        with self.assertRaisesRegex(ControlError, 'changed'):
            await self.media.start(self.guest, revision=revision)
        self.vlc.status.assert_not_awaited()

    async def test_lock_and_channel_policy_apply_to_media_actions(self):
        await self.control.execute(self.host, 'lock')
        with self.assertRaisesRegex(ControlError, 'locked'):
            await self.add_subbed()
        with self.assertRaisesRegex(ControlError, 'configured'):
            await self.media.edit(Actor(3, 1, 999), 'clear')
        with self.assertRaisesRegex(ControlError, 'locked'):
            await self.media.start(self.guest)

    async def test_missing_file_detected_before_vlc_changes(self):
        await self.add_subbed()
        self.library.resolve(self.draft.rows[0]['episode']).unlink()
        with self.assertRaises(ControlError):
            await self.media.start(self.host)
        self.vlc.status.assert_not_awaited()

    async def test_unknown_path_and_outside_root_rejected(self):
        with self.assertRaises(ControlError):
            await self.media.edit(self.host, 'add', episode='../../secret.mp4')
        from dataclasses import replace
        item = next(iter(self.library.episodes.values()))
        self.library.episodes[item.key] = replace(item, relative_path='../outside.mp4')
        (self.root / 'outside.mp4').write_bytes(b'test')
        with self.assertRaises(ControlError):
            self.library.resolve(item.key)

    async def test_queue_capacity_and_invalid_moves(self):
        key = next(iter(self.library.episodes))
        self.draft.commit([{'id': str(index), 'episode': key} for index in range(100)])
        with self.assertRaisesRegex(ControlError, '100'):
            await self.media.edit(self.guest, 'add', episode=key)
        for position in (0, 101, None, '1'):
            with self.assertRaises(ControlError):
                await self.media.edit(self.guest, 'move', row_id='0', position=position)
        self.assertEqual(len(self.draft.rows), 100)

    async def test_start_applies_explicit_order_and_disables_shuffle(self):
        await self.add_subbed()
        await self.media.edit(self.guest, 'move', row_id=self.draft.rows[2]['id'], position=2)
        self.vlc.request.return_value = {'random': True, 'loop': True, 'repeat': True}
        self.vlc.playlist.return_value = [{'id': 10}, {'id': 11}, {'id': 12}]
        await self.media.start(self.host)
        calls = self.vlc.status.call_args_list
        self.assertEqual([call.args[0] for call in calls[:4]], ['pl_random', 'pl_loop', 'pl_repeat', 'pl_empty'])
        enqueued = [Path(call.kwargs['input'].split('/')[-1]).name for call in calls if call.args and call.args[0] == 'in_enqueue']
        self.assertEqual(enqueued, ['ExampleShow_1_Subbed.mp4', 'ExampleShow_10_Subbed.mp4', 'ExampleShow_2_Subbed.mp4'])

    async def test_partial_start_failure_preserves_saved_playlist(self):
        await self.add_subbed()
        before = list(self.draft.rows)
        self.vlc.status.side_effect = [Playback('stopped', 0, 0, 'VLC'), ControlError('timeout')]
        with self.assertRaisesRegex(ControlError, 'saved playlist is intact'):
            await self.media.start(self.host)
        self.assertEqual(self.draft.rows, before)

    async def test_show_select_and_add_button(self):
        view = self.track_view(ShowsView(self.bot, 4, shelf='ExampleShow / Subbed'))
        select = next(item for item in view.children if getattr(item, 'row', None) == 1)
        select._values = [self.library.shelves['ExampleShow / Subbed'][0].key]
        interaction = self.interaction()
        await select.callback(interaction)
        selected_view = self.track_view(interaction.response.edit_message.call_args.kwargs['view'])
        button = next(item for item in selected_view.children if getattr(item, 'label', None) == 'Add episode')
        await button.callback(self.interaction())
        self.assertEqual(len(self.draft.rows), 1)

    async def test_playlist_move_modal_and_remove_button(self):
        await self.add_subbed()
        view = self.track_view(PlaylistView(self.bot, 4, selected=self.draft.rows[2]['id']))
        modal = self.track_view(MoveModal(view))
        modal.position._value = '1'
        interaction = self.interaction()
        await modal.on_submit(interaction)
        updated = self.track_view(interaction.edit_original_response.call_args.kwargs['view'])
        self.assertIn('_10_', self.episode_numbers()[0])
        remove = next(item for item in updated.children if getattr(item, 'label', None) == 'Remove episode')
        removed = self.interaction()
        await remove.callback(removed)
        self.track_view(removed.edit_original_response.call_args.kwargs['view'])
        self.assertEqual(len(self.draft.rows), 2)

    async def test_clear_requires_second_click(self):
        await self.add_subbed()
        view = self.track_view(PlaylistView(self.bot, 4))
        clear = next(item for item in view.children if getattr(item, 'label', None) == 'Clear saved playlist')
        interaction = self.interaction()
        await clear.callback(interaction)
        self.assertEqual(len(self.draft.rows), 3)
        confirmed = self.track_view(interaction.response.edit_message.call_args.kwargs['view'])
        confirm = next(item for item in confirmed.children if getattr(item, 'label', None) == 'Confirm clear')
        second = self.interaction()
        await confirm.callback(second)
        self.track_view(second.edit_original_response.call_args.kwargs['view'])
        self.assertEqual(self.draft.rows, [])

    async def test_editor_is_shared_with_other_channel_members(self):
        view = self.track_view(ShowsView(self.bot, 4))
        self.assertTrue(await view.interaction_check(self.interaction(user_id=8)))
        self.assertTrue(await view.interaction_check(self.interaction()))
        queue_view = self.track_view(PlaylistView(self.bot, 4))
        self.assertTrue(await queue_view.interaction_check(self.interaction(user_id=8)))
        outside = self.interaction(user_id=8)
        outside.channel_id = 999
        self.assertFalse(await view.interaction_check(outside))

    async def test_large_library_and_playlist_use_pagination(self):
        for index in range(30):
            show = self.videos / f'Show {index}'
            show.mkdir()
            (show / '01.mp4').write_bytes(b'test')
        self.library.scan()
        view = self.track_view(ShowsView(self.bot, 4))
        self.assertTrue(any(item.label == 'More shows' and not item.disabled for item in view.children if hasattr(item, 'label')))
        for item in view.children:
            if hasattr(item, 'options'):
                self.assertLessEqual(len(item.options), 25)
        key = next(iter(self.library.episodes))
        self.draft.commit([{'id': str(index), 'episode': key} for index in range(45)])
        playlist = self.track_view(PlaylistView(self.bot, 4, page=2))
        self.assertEqual(len(playlist.children[0].options), 5)
        self.assertLessEqual(len(playlist.to_components()), 5)


if __name__ == '__main__':
    unittest.main()
