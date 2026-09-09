"""Local VLC adapter and shared-control policy, independent of Discord UI."""
import asyncio
from base64 import b64encode
import json
import time
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from config import local_vlc_url


class ControlError(Exception):
    """Safe, actionable error that may be shown in Discord."""


@dataclass(frozen=True)
class Playback:
    state: str
    seconds: int
    duration: int
    title: str
    item_id: int = -1

    @classmethod
    def parse(cls, data):
        try:
            if not isinstance(data, dict) or data.get('state') not in ('playing', 'paused', 'stopped'):
                raise ValueError
            meta = data.get('information', {}).get('category', {}).get('meta', {})
            # Filename/title only: never publish a media URI or filesystem path.
            raw = str(meta.get('title') or meta.get('filename') or 'VLC')
            title = raw.replace('\\', '/').rsplit('/', 1)[-1][:200]
            return cls(data['state'], max(0, int(data.get('time', 0))),
                       max(0, int(data.get('length', 0))), title, int(data.get('currentplid', -1)))
        except (ValueError, TypeError, AttributeError):
            raise ControlError('VLC returned an unexpected status response.') from None


class VlcClient:
    def __init__(self, session, url, password):
        self.session = session
        self.url = local_vlc_url(url) + '/requests/status.json'
        self.headers = {'Authorization': 'Basic ' + b64encode((':' + password).encode('utf-8')).decode('ascii')}

    async def request(self, endpoint='status.json', command=None, **params):
        if command:
            params['command'] = command
        try:
            # No redirects, environment proxy, or retries of playback mutations.
            url = self.url.rsplit('/', 1)[0] + '/' + endpoint
            async with self.session.get(url, params=params, headers=self.headers,
                                        allow_redirects=False,
                                        timeout=aiohttp.ClientTimeout(total=4)) as response:
                if response.status in (401, 403):
                    raise ControlError('VLC rejected the password. Restart VLC using start-vlc.ps1.')
                if response.status != 200:
                    raise ControlError('VLC did not accept the request. Check the local VLC interface.')
                return await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            raise ControlError('Cannot reach VLC. Run start-vlc.ps1 on the streaming PC. '
                               'If a control timed out, check Status before trying again.') from None
        except (ValueError, UnicodeError):
            raise ControlError('VLC returned an unreadable status response.') from None

    async def status(self, command=None, **params):
        return Playback.parse(await self.request(command=command, **params))

    async def playlist(self):
        data = await self.request('playlist.json')
        items = []

        def visit(node):
            if not isinstance(node, dict):
                return
            if 'uri' in node:
                items.append(node)
            for child in node.get('children', []):
                visit(child)

        visit(data)
        return items

    async def act(self, action, seconds=None):
        if action == 'status':
            return await self.status()
        current = await self.status()
        if action == 'play':
            if current.state == 'stopped':
                result = await self.status('pl_play')
                if result.state == 'stopped':
                    raise ControlError('Open a video in VLC first, then press Play.')
                return result
            return await self.status('pl_forceresume')
        if action == 'pause':
            return await self.status('pl_forcepause')
        if action in ('next', 'previous'):
            items = await self.playlist()
            current_index = next((index for index, item in enumerate(items)
                                  if int(item['id']) == current.item_id), None)
            if current_index is None:
                raise ControlError('Start a playlist first.')
            target = current_index + (1 if action == 'next' else -1)
            if not 0 <= target < len(items):
                raise ControlError('You are at the end of the playlist.' if action == 'next'
                                   else 'You are at the start of the playlist.')
            return await self.status('pl_play', id=str(items[target]['id']))
        if action == 'seek':
            if type(seconds) is not int or seconds == 0 or abs(seconds) > 3600:
                raise ControlError('Enter whole seconds from -3600 to 3600, excluding 0.')
            if current.state == 'stopped' or current.duration <= 0:
                raise ControlError('Open a seekable video first. Some live streams cannot rewind.')
            # Absolute, clamped seeks prevent end-of-file skips into another item.
            target = max(0, min(current.duration - 1, current.seconds + seconds))
            return await self.status('seek', val=str(target))
        raise ControlError('Unknown playback action.')


@dataclass(frozen=True)
class Actor:
    user_id: int
    guild_id: int | None
    channel_id: int | None
    roles: frozenset[int] = frozenset()
    manage_guild: bool = False


class StateStore:
    def __init__(self, path: Path, scope: str):
        self.path, self.scope = path, scope
        self.locked = False
        self.panel_id = None
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data, dict):
                    raise ValueError
                if data.get('scope') == scope:
                    if type(data.get('locked')) is not bool:
                        raise ValueError
                    panel = data.get('panel_id')
                    if panel is not None and (type(panel) is not int or panel <= 0):
                        raise ValueError
                    self.locked, self.panel_id = data['locked'], panel
            except (ValueError, OSError):
                raise ValueError('Local state cannot be read. Repair .state/session.json before starting.') from None

    def save(self, *, locked, panel_id):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'scope': self.scope, 'locked': locked,
                                         'panel_id': panel_id}), encoding='utf-8')
        temporary.replace(self.path)
        self.locked, self.panel_id = locked, panel_id


class SharedController:
    def __init__(self, vlc, settings, store, cooldown=0.8):
        self.vlc, self.settings, self.store = vlc, settings, store
        self.cooldown = cooldown
        self.last_action = {}
        self.lock = asyncio.Lock()

    def is_host(self, actor):
        return actor.manage_guild or actor.user_id == self.settings.host_user_id

    def authorize(self, actor, *, changing=False, host_only=False):
        if actor.guild_id != self.settings.guild_id or actor.channel_id != self.settings.channel_id:
            raise ControlError('Use the configured VLC control channel in your server.')
        host = self.is_host(actor)
        if host_only and not host:
            raise ControlError('Only the host or someone with Manage Server can do that.')
        if self.settings.control_role_id and not host and self.settings.control_role_id not in actor.roles:
            raise ControlError('You need the configured control role to use this remote.')
        if changing and self.store.locked and not host:
            raise ControlError('The host has locked the remote. You can still check Status.')

    async def execute(self, actor, action, seconds=None):
        # The queue includes permission checks, reads, and writes. A host lock takes
        # effect for later queued commands, and simultaneous seeks accumulate.
        if self.lock.locked():
            self.authorize(actor, changing=action != 'status', host_only=action in ('lock', 'unlock'))
        async with self.lock:
            self.authorize(actor, changing=action != 'status', host_only=action in ('lock', 'unlock'))
            now = time.monotonic()
            self.last_action = {key: value for key, value in self.last_action.items()
                                if now - value < self.cooldown}
            if actor.user_id in self.last_action:
                raise ControlError('Wait a moment before using another control.')
            self.last_action[actor.user_id] = now
            if action in ('lock', 'unlock'):
                try:
                    self.store.save(locked=action == 'lock', panel_id=self.store.panel_id)
                except OSError:
                    raise ControlError('Could not save the host lock. Check the bot folder permissions.') from None
                return None
            return await self.vlc.act(action, seconds)

    async def snapshot(self):
        async with self.lock:
            return await self.vlc.status()
