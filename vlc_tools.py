"""Launch a dedicated VLC player or diagnose its local API."""
import argparse
import asyncio
import os
from pathlib import Path
import shutil
import socket
import subprocess
from urllib.parse import urlsplit

import aiohttp
from dotenv import dotenv_values

from config import ROOT, local_vlc_url
from controller import ControlError, VlcClient


def local_config():
    values = dotenv_values(ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    password = values.get('VLC_PASSWORD')
    if not password:
        raise SystemExit('Run setup.ps1 first to generate a local VLC password.')
    url = local_vlc_url(values.get('VLC_URL') or 'http://127.0.0.1:8080')
    return url, password


def vlc_executable():
    candidates = [shutil.which('vlc'),
                  str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'VideoLAN/VLC/vlc.exe'),
                  str(Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'VideoLAN/VLC/vlc.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise SystemExit('VLC was not found. Install VLC from https://www.videolan.org/vlc/.')


async def check(url, password):
    async with aiohttp.ClientSession(trust_env=False) as session:
        status = await VlcClient(session, url, password).status()
        print(f'VLC API connected. Playback: {status.state}; position: {status.seconds}s.')


def launch(url, password):
    parsed = urlsplit(url)
    host, port = parsed.hostname, parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=1):
            pass
    except OSError:
        pass
    else:
        raise SystemExit('The local VLC port is already in use. Run check-vlc.ps1; if it succeeds, use that VLC window.')
    # This is a visible interactive player for the user to open and screen-share.
    # Existing VLC instances are never closed or reconfigured.
    subprocess.Popen([vlc_executable(), '--no-one-instance', '--no-one-instance-when-started-from-file',
                      '--extraintf=http', f'--http-host={host}', f'--http-port={port}',
                      f'--http-password={password}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Opened the controlled VLC window. Open your video in that window and screen-share it in Discord.')


async def ensure_running(url, password):
    async with aiohttp.ClientSession(trust_env=False) as session:
        vlc = VlcClient(session, url, password)
        try:
            await vlc.status()
            print('Using the existing controlled VLC window.')
            return
        except ControlError:
            pass
        # The launcher refuses to start if another service/wrong-password VLC
        # owns the port. Never silently attach to or replace that process.
        launch(url, password)
        for _ in range(30):
            await asyncio.sleep(0.25)
            try:
                await vlc.status()
                print('VLC control connection verified.')
                return
            except ControlError:
                pass
        raise ControlError('VLC did not become ready. Check its window and run check-vlc.ps1.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['launch', 'check'])
    args = parser.parse_args()
    try:
        url, password = local_config()
        if args.command == 'launch':
            launch(url, password)
        else:
            asyncio.run(check(url, password))
    except (ControlError, ValueError) as error:
        raise SystemExit(str(error)) from None
