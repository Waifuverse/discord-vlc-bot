"""Shared Discord show browsing and playlist editing with per-action access checks."""
import logging

import discord

from controller import Actor, ControlError


def actor(interaction):
    return Actor(interaction.user.id, interaction.guild_id, interaction.channel_id,
                 frozenset(role.id for role in getattr(interaction.user, 'roles', [])),
                 interaction.permissions.manage_guild)


def safe(value):
    return discord.utils.escape_markdown(discord.utils.escape_mentions(str(value)))


class EditorView(discord.ui.View):
    def __init__(self, bot, owner_id):
        super().__init__(timeout=600)
        self.bot, self.owner_id = bot, owner_id

    async def interaction_check(self, interaction):
        try:
            self.bot.control.authorize(actor(interaction))
            return True
        except ControlError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return False

    async def on_error(self, interaction, error, item):
        logging.getLogger('vlc_remote').error('Library control failed (%s).', type(error).__name__)
        text = str(error) if isinstance(error, ControlError) else 'The editor could not finish. Reopen it to refresh.'
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    def button(self, label, callback, row, *, disabled=False, style=discord.ButtonStyle.secondary):
        button = discord.ui.Button(label=label, row=row, style=style, disabled=disabled)
        button.callback = callback
        self.add_item(button)


class ShowsView(EditorView):
    def __init__(self, bot, owner_id, shelf=None, page=0, selected=None):
        super().__init__(bot, owner_id)
        self.shelf = shelf if shelf in bot.library.shelves else next(iter(bot.library.shelves), None)
        self.entries = bot.library.shelves.get(self.shelf, [])
        self.page = max(0, min(page, (len(self.entries) - 1) // 25))
        self.selected = selected if any(item.key == selected for item in self.entries) else None
        # Show shelves themselves are paginated to stay within Discord's 25-option limit.
        self.shelf_names = list(bot.library.shelves)
        self.shelf_page = self.shelf_names.index(self.shelf) // 25 if self.shelf else 0
        names = self.shelf_names[self.shelf_page * 25:(self.shelf_page + 1) * 25]
        if names:
            menu = discord.ui.Select(placeholder='Choose show and version', row=0, options=[
                discord.SelectOption(label=f'{name} ({len(bot.library.shelves[name])})'[:100],
                                     value=str(self.shelf_names.index(name)), default=name == self.shelf)
                for name in names])

            async def choose_shelf(interaction):
                await self.replace(interaction, shelf=self.shelf_names[int(menu.values[0])])

            menu.callback = choose_shelf
            self.add_item(menu)
        entries = self.entries[self.page * 25:(self.page + 1) * 25]
        if entries:
            episodes = discord.ui.Select(placeholder='Choose an episode', row=1, options=[
                discord.SelectOption(label=item.label[:100], value=item.key, default=item.key == self.selected)
                for item in entries])

            async def choose_episode(interaction):
                await self.replace(interaction, shelf=self.shelf, page=self.page, selected=episodes.values[0])

            episodes.callback = choose_episode
            self.add_item(episodes)

        async def play(interaction):
            await interaction.response.defer()
            try:
                result = await bot.media.start(actor(interaction), episode=self.selected)
                await interaction.edit_original_response(embed=self.embed(f'Playing {result.title}'), view=self)
            except ControlError as error:
                await interaction.followup.send(str(error), ephemeral=True)

        async def add(interaction):
            await self.add_items(interaction, 'add', episode=self.selected)

        async def add_version(interaction):
            await self.add_items(interaction, 'add_shelf', shelf=self.shelf)

        async def queue(interaction):
            view = PlaylistView(bot, owner_id)
            await interaction.response.edit_message(embed=view.embed(), view=view)
            self.stop()

        async def previous(interaction):
            await self.replace(interaction, shelf=self.shelf, page=self.page - 1)

        async def following(interaction):
            await self.replace(interaction, shelf=self.shelf, page=self.page + 1)

        async def earlier_shows(interaction):
            await self.replace(interaction, shelf=self.shelf_names[(self.shelf_page - 1) * 25])

        async def later_shows(interaction):
            await self.replace(interaction, shelf=self.shelf_names[(self.shelf_page + 1) * 25])

        self.button('Play episode now', play, 2, disabled=self.selected is None, style=discord.ButtonStyle.success)
        self.button('Add episode', add, 2, disabled=self.selected is None)
        self.button('Add this version in order', add_version, 2, disabled=not self.entries)
        self.button('Playlist', queue, 2)
        self.button('Previous episodes', previous, 3, disabled=self.page == 0)
        self.button('More episodes', following, 3, disabled=(self.page + 1) * 25 >= len(self.entries))
        self.button('Previous shows', earlier_shows, 4, disabled=self.shelf_page == 0)
        self.button('More shows', later_shows, 4, disabled=(self.shelf_page + 1) * 25 >= len(self.shelf_names))

    def embed(self, notice=None):
        content = f'**{safe(self.shelf or "No videos found")}**\n'
        content += '\n'.join(safe(item.label) for item in self.entries[self.page * 25:(self.page + 1) * 25])
        if notice:
            content = safe(notice) + '\n\n' + content
        embed = discord.Embed(title='Available shows', description=content[:3900], color=0xE87924)
        embed.set_footer(text=f'{len(self.bot.library.episodes)} videos • Shared view: everyone can select • Play now replaces the VLC queue')
        return embed

    async def replace(self, interaction, **kwargs):
        view = ShowsView(self.bot, self.owner_id, **kwargs)
        await interaction.response.edit_message(embed=view.embed(), view=view)
        self.stop()

    async def add_items(self, interaction, action, **kwargs):
        await interaction.response.defer()
        try:
            size = await self.bot.media.edit(actor(interaction), action, **kwargs)
            await interaction.edit_original_response(embed=self.embed(f'Added. Playlist now has {size} episodes.'), view=self)
        except ControlError as error:
            await interaction.followup.send(str(error), ephemeral=True)


class MoveModal(discord.ui.Modal, title='Move playlist episode'):
    position = discord.ui.TextInput(label='New position in the playlist', placeholder='1', max_length=3)

    def __init__(self, view):
        super().__init__(timeout=180)
        self.editor = view

    async def on_submit(self, interaction):
        try:
            position = int(str(self.position))
        except ValueError:
            await interaction.response.send_message('Enter a whole-number playlist position.', ephemeral=True)
            return
        await self.editor.change(interaction, 'move', position=position)

    async def on_error(self, interaction, error):
        await self.editor.on_error(interaction, error, None)


class PlaylistView(EditorView):
    def __init__(self, bot, owner_id, page=0, selected=None, confirm_clear=False):
        super().__init__(bot, owner_id)
        self.rows = list(bot.draft.rows)
        self.revision = bot.draft.revision
        self.page = max(0, min(page, (len(self.rows) - 1) // 20))
        self.selected = selected if any(row['id'] == selected for row in self.rows) else None
        self.index = next((index for index, row in enumerate(self.rows) if row['id'] == self.selected), None)
        self.confirm_clear = confirm_clear
        if self.rows:
            menu = discord.ui.Select(placeholder='Select an episode to move or remove', row=0, options=[
                discord.SelectOption(label=f'{index + 1}. {self.label(row)}'[:100], value=row['id'],
                                     default=row['id'] == self.selected)
                for index, row in enumerate(self.rows) if self.page * 20 <= index < (self.page + 1) * 20])

            async def choose(interaction):
                await self.replace(interaction, selected=menu.values[0])

            menu.callback = choose
            self.add_item(menu)

        async def move_up(interaction):
            await self.change(interaction, 'move', position=self.index)

        async def move_down(interaction):
            await self.change(interaction, 'move', position=self.index + 2)

        async def move_to(interaction):
            await interaction.response.send_modal(MoveModal(self))

        async def remove(interaction):
            await self.change(interaction, 'remove')

        async def clear(interaction):
            if self.confirm_clear:
                await self.change(interaction, 'clear')
            else:
                await self.replace(interaction, confirm_clear=True)

        async def start(interaction):
            await interaction.response.defer()
            try:
                result = await bot.media.start(actor(interaction), revision=self.revision)
                await interaction.edit_original_response(embed=self.embed(f'Playing {result.title}'), view=self)
            except ControlError as error:
                await interaction.followup.send(str(error), ephemeral=True)

        async def refresh(interaction):
            await self.replace(interaction)

        async def shows(interaction):
            view = ShowsView(bot, owner_id)
            await interaction.response.edit_message(embed=view.embed(), view=view)
            self.stop()

        async def previous(interaction):
            await self.replace(interaction, page=self.page - 1)

        async def following(interaction):
            await self.replace(interaction, page=self.page + 1)

        self.button('Move up', move_up, 1, disabled=self.index is None or self.index == 0)
        self.button('Move down', move_down, 1, disabled=self.index is None or self.index == len(self.rows) - 1)
        self.button('Move to position', move_to, 1, disabled=self.selected is None)
        self.button('Remove episode', remove, 1, disabled=self.selected is None)
        self.button('Start playlist from beginning', start, 2, disabled=not self.rows, style=discord.ButtonStyle.success)
        self.button('Confirm clear' if confirm_clear else 'Clear saved playlist', clear, 2,
                    disabled=not self.rows, style=discord.ButtonStyle.danger)
        self.button('Refresh / cancel', refresh, 2)
        self.button('Shows', shows, 2)
        self.button('Previous page', previous, 3, disabled=self.page == 0)
        self.button('Next page', following, 3, disabled=(self.page + 1) * 20 >= len(self.rows))

    def label(self, row):
        item = self.bot.library.episodes.get(row['episode'])
        return item.label if item else 'Missing video — remove or rescan Shows'

    def embed(self, notice=None):
        lines = [f'**{index + 1}.** {safe(self.label(row))}' for index, row in enumerate(self.rows)
                 if self.page * 20 <= index < (self.page + 1) * 20]
        content = '\n'.join(lines) or 'Open Shows and add episodes or a whole show version.'
        if self.confirm_clear:
            content = '**Clear all entries from the saved playlist? Video files stay on disk.**\n\n' + content
        if notice:
            content = safe(notice) + '\n\n' + content
        embed = discord.Embed(title=f'Your playlist • {len(self.rows)} episodes', description=content[:3900], color=0xE87924)
        embed.set_footer(text='Shared playlist • Edits save automatically • Start applies this order from the beginning • Current playback continues while you edit')
        return embed

    async def replace(self, interaction, **kwargs):
        view = PlaylistView(self.bot, self.owner_id, page=kwargs.get('page', self.page),
                            selected=kwargs.get('selected', self.selected), confirm_clear=kwargs.get('confirm_clear', False))
        await interaction.response.edit_message(embed=view.embed(), view=view)
        self.stop()

    async def change(self, interaction, action, **kwargs):
        await interaction.response.defer()
        try:
            await self.bot.media.edit(actor(interaction), action, row_id=self.selected,
                                      revision=self.revision, **kwargs)
            view = PlaylistView(self.bot, self.owner_id, self.page, self.selected)
            await interaction.edit_original_response(embed=view.embed('Playlist saved.'), view=view)
            self.stop()
        except ControlError as error:
            await interaction.followup.send(str(error), ephemeral=True)
