from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent


def media_directory(value=None):
    path = Path(value or 'media').expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def numeric_id(values, name, required=True):
    value = (values.get(name) or '').strip()
    if not value and not required:
        return None
    if not value.isascii() or not value.isdecimal() or not 15 <= len(value) <= 22:
        raise ValueError(f'{name} must be a Discord ID (enable Developer Mode to copy IDs).')
    return int(value)


def local_vlc_url(value):
    url = urlsplit(value)
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1')
            or url.username or url.password or url.path not in ('', '/')
            or url.query or url.fragment):
        raise ValueError('VLC_URL must be a local HTTP address, such as http://127.0.0.1:8080.')
    try:
        port = url.port
    except ValueError:
        raise ValueError('VLC_URL has an invalid port.') from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('VLC_URL has an invalid port.')
    return value.rstrip('/')


@dataclass(frozen=True)
class Settings:
    token: str = field(repr=False)
    guild_id: int
    channel_id: int
    vlc_password: str = field(repr=False)
    vlc_url: str = 'http://127.0.0.1:8080'
    host_user_id: int | None = None
    control_role_id: int | None = None
    media_root: Path = field(default_factory=media_directory)

    @classmethod
    def read(cls, values=None):
        if values is None:
            # This installation uses its own file, independent of other bots or
            # stale variables inherited by a PowerShell window.
            values = dotenv_values(ROOT / '.env', encoding='utf-8-sig', interpolate=False)
        token = (values.get('DISCORD_TOKEN') or '').strip()
        password = (values.get('VLC_PASSWORD') or '').strip()
        if not token:
            raise ValueError('DISCORD_TOKEN is missing. Enter the bot token in this folder\'s .env and save it.')
        if any(character.isspace() for character in token):
            raise ValueError('DISCORD_TOKEN must be the bot token without a Bot prefix or spaces.')
        if not password:
            raise ValueError('VLC_PASSWORD is missing. Run setup.ps1.')
        return cls(token=token, guild_id=numeric_id(values, 'DISCORD_GUILD_ID'),
                   channel_id=numeric_id(values, 'DISCORD_CHANNEL_ID'),
                   vlc_password=password,
                   vlc_url=local_vlc_url(values.get('VLC_URL') or 'http://127.0.0.1:8080'),
                   host_user_id=numeric_id(values, 'HOST_USER_ID', False),
                   control_role_id=numeric_id(values, 'CONTROL_ROLE_ID', False),
                   media_root=media_directory(values.get('MEDIA_ROOT')))
