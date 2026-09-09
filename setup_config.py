"""Interactive local setup; never prints credentials."""
from getpass import getpass
import argparse
import secrets

from dotenv import dotenv_values, set_key

from config import ROOT, Settings, numeric_id


def prepare_env(path=None):
    path = path or ROOT / '.env'
    if path.exists():
        print('.env already exists; its contents were preserved.')
        return
    password = secrets.token_urlsafe(32)
    template = (ROOT / 'config.env.template').read_text(encoding='utf-8')
    content = template.replace(
        '# Public, blank configuration template. Do not put real credentials in this file.\n'
        '# Run setup.ps1 to generate your private .env, then edit .env instead.',
        '# Private configuration for this PC. Enter your values here and save.\n'
        '# This file is ignored by Git; never force-add it or share it.')
    content = content.replace('VLC_PASSWORD=\n', f'VLC_PASSWORD={password}\n')
    with path.open('x', encoding='utf-8') as file:
        file.write(content)
    print('Created .env with a generated VLC password. No secrets were printed.')


def prompt_id(values, name, label, required=True):
    current = values.get(name) or ''
    while True:
        hint = f' [{current}]' if current else (' (optional)' if not required else '')
        entered = input(f'{label}{hint}: ').strip()
        value = '' if entered == '-' else entered or current
        try:
            numeric_id({name: value}, name, required)
            return value
        except ValueError as error:
            print(error)


def main():
    path = ROOT / '.env'
    values = dict(dotenv_values(path, encoding='utf-8-sig', interpolate=False)) if path.exists() else {}
    print('VLC shared remote setup. Enter the bot token here, never in chat.')
    print('For optional IDs, enter - to clear an existing value.')
    token_prompt = 'Bot token (hidden; Enter keeps existing): ' if values.get('DISCORD_TOKEN') else 'Bot token (hidden): '
    token = getpass(token_prompt).strip() or values.get('DISCORD_TOKEN', '')
    if not token:
        raise SystemExit('No token entered. Nothing was saved.')
    if any(char.isspace() for char in token):
        raise SystemExit('The token contains whitespace. Nothing was saved.')
    values['DISCORD_TOKEN'] = token
    values['DISCORD_GUILD_ID'] = prompt_id(values, 'DISCORD_GUILD_ID', 'Server ID')
    values['DISCORD_CHANNEL_ID'] = prompt_id(values, 'DISCORD_CHANNEL_ID', 'Control channel ID')
    values['HOST_USER_ID'] = prompt_id(values, 'HOST_USER_ID', 'Your user ID (host)', False)
    values['CONTROL_ROLE_ID'] = prompt_id(values, 'CONTROL_ROLE_ID', 'Controller role ID', False)
    values['VLC_URL'] = values.get('VLC_URL') or 'http://127.0.0.1:8080'
    values['VLC_PASSWORD'] = values.get('VLC_PASSWORD') or secrets.token_urlsafe(32)
    current_media = values.get('MEDIA_ROOT') or 'media'
    values['MEDIA_ROOT'] = input(f'Media folder [{current_media}]: ').strip() or current_media
    Settings.read(values)
    for name in ('DISCORD_TOKEN', 'DISCORD_GUILD_ID', 'DISCORD_CHANNEL_ID', 'HOST_USER_ID',
                 'CONTROL_ROLE_ID', 'MEDIA_ROOT', 'VLC_URL', 'VLC_PASSWORD'):
        set_key(str(path), name, values[name], quote_mode='always')
    print('Saved locally to .env. No secrets were printed. Keep this file private.')
    print('Next: run start.ps1 or double-click Start VLC Remote.cmd.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true', help='Create the real .env without credential prompts')
    args = parser.parse_args()
    try:
        if args.prepare:
            prepare_env()
        else:
            main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('\nSetup cancelled.') from None
