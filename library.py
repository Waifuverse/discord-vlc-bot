"""Allowlisted local shows and a persistent playlist to arrange before playback."""
import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import uuid

from controller import ControlError

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.webm', '.mov', '.m4v', '.ts', '.m2ts'}


def natural_key(value):
    return tuple((0, int(part)) if part.isdecimal() else (1, part.casefold())
                 for part in re.split(r'(\d+)', str(value)))


@dataclass(frozen=True)
class Episode:
    key: str
    relative_path: str
    show: str
    version: str
    label: str

    @property
    def shelf(self):
        return f'{self.show} / {self.version}'


class MediaLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.episodes = {}
        self.shelves = {}

    def scan(self):
        if not self.root.is_dir():
            raise ControlError('The media folder is unavailable. Check MEDIA_ROOT in .env.')
        episodes, shelves = {}, {}
        try:
            files = sorted(self.root.rglob('*'), key=lambda path: natural_key(path.relative_to(self.root)))
            for path in files:
                if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
                    continue
                if not path.resolve().is_relative_to(self.root):
                    continue
                relative = path.relative_to(self.root)
                show = relative.parts[0] if len(relative.parts) > 1 else 'Videos'
                version = ('Dubbed' if re.search(r'\bdub(?:bed)?\b', path.stem.replace('_', ' '), re.I)
                           else 'Subbed' if re.search(r'\bsub(?:bed)?\b', path.stem.replace('_', ' '), re.I)
                           else 'Unlabelled')
                key = hashlib.sha256(relative.as_posix().encode()).hexdigest()[:20]
                label = str(relative.with_suffix('')).replace('\\', ' / ').replace('_', ' ')
                episode = Episode(key, relative.as_posix(), show, version, label)
                episodes[key] = episode
                shelves.setdefault(episode.shelf, []).append(episode)
        except OSError:
            raise ControlError('Could not scan the media folder. Check its local permissions.') from None
        self.episodes, self.shelves = episodes, shelves
        return self

    def resolve(self, key):
        episode = self.episodes.get(key)
        if episode is None:
            raise ControlError('That episode is no longer in the library. Reopen Shows.')
        path = (self.root / episode.relative_path).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise ControlError('That video is missing or outside the media folder. Reopen Shows.')
        return path


class PlaylistDraft:
    def __init__(self, path):
        self.path = Path(path)
        self.rows = []
        self.revision = 0
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                rows = data['rows']
                if (not isinstance(rows, list) or len(rows) > 100
                        or type(data['revision']) is not int
                        or any(not isinstance(row, dict) or set(row) != {'id', 'episode'}
                               or not all(isinstance(value, str) for value in row.values()) for row in rows)
                        or len({row['id'] for row in rows}) != len(rows)):
                    raise ValueError
                self.rows, self.revision = rows, data['revision']
            except (ValueError, KeyError, TypeError, OSError):
                raise ValueError('Cannot read .state/playlist.json. Repair it before starting the bot.') from None

    def commit(self, rows):
        if len(rows) > 100:
            raise ControlError('The playlist can hold up to 100 episodes.')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'rows': rows, 'revision': self.revision + 1}), encoding='utf-8')
            temporary.replace(self.path)
        except OSError:
            raise ControlError('Could not save the playlist. Check local folder permissions.') from None
        self.rows, self.revision = rows, self.revision + 1


class LibraryController:
    def __init__(self, control, library, draft):
        self.control, self.library, self.draft = control, library, draft

    async def edit(self, actor, action, *, episode=None, shelf=None, row_id=None, position=None, revision=None):
        async with self.control.lock:
            self.control.authorize(actor, changing=True)
            if revision is not None and revision != self.draft.revision:
                raise ControlError('The playlist changed. Refresh it before editing again.')
            rows = list(self.draft.rows)
            if action in ('add', 'add_shelf'):
                keys = [episode] if action == 'add' else [item.key for item in self.library.shelves.get(shelf, [])]
                if not keys:
                    raise ControlError('Select an available show version first.')
                for key in keys:
                    self.library.resolve(key)
                    rows.append({'id': uuid.uuid4().hex, 'episode': key})
            elif action in ('move', 'remove'):
                index = next((index for index, row in enumerate(rows) if row['id'] == row_id), None)
                if index is None:
                    raise ControlError('Select an episode from the current playlist first.')
                if action == 'move':
                    if type(position) is not int or not 1 <= position <= len(rows):
                        raise ControlError(f'Choose a position from 1 to {len(rows)}.')
                    rows.insert(position - 1, rows.pop(index))
                else:
                    rows.pop(index)
            elif action == 'clear':
                rows = []
            else:
                raise ControlError('Unknown playlist action.')
            self.draft.commit(rows)
            return len(rows)

    async def start(self, actor, *, episode=None, revision=None):
        async with self.control.lock:
            self.control.authorize(actor, changing=True)
            if revision is not None and revision != self.draft.revision:
                raise ControlError('The playlist changed. Refresh it before starting.')
            keys = [episode] if episode else [row['episode'] for row in self.draft.rows]
            if not keys:
                raise ControlError('Add some episodes to the playlist first.')
            # Validate every file before replacing anything in VLC.
            paths = [self.library.resolve(key) for key in keys]
            vlc = self.control.vlc
            raw = await vlc.request()
            for flag, command in [('random', 'pl_random'), ('loop', 'pl_loop'), ('repeat', 'pl_repeat')]:
                if raw.get(flag):
                    await vlc.status(command)
            await vlc.status('pl_empty')
            try:
                for path in paths:
                    await vlc.status('in_enqueue', input=path.as_uri())
                items = await vlc.playlist()
                if len(items) != len(paths):
                    raise ControlError('VLC did not load all playlist items.')
                first_id = int(items[0]['id'])
                await vlc.status('pl_play', id=str(first_id))
                for _ in range(30):
                    status = await vlc.status()
                    if status.item_id == first_id and status.state == 'playing' and status.duration > 0:
                        return status
                    await asyncio.sleep(0.1)
                raise ControlError('VLC has not confirmed playback yet.')
            except ControlError:
                raise ControlError('VLC could not confirm the full playlist started. Your saved playlist is intact; '
                                   'check VLC and Status before trying Start again.') from None
