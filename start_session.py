"""One launcher for the configured local VLC and Discord bot."""
import asyncio

from bot import main as run_bot
from config import Settings
from controller import ControlError
from vlc_tools import ensure_running


def main():
    try:
        settings = Settings.read()
        asyncio.run(ensure_running(settings.vlc_url, settings.vlc_password))
    except (ValueError, ControlError) as error:
        raise SystemExit(str(error)) from None
    run_bot()


if __name__ == '__main__':
    main()
