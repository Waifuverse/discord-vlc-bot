"""Check the Git index before commit/push; never print matching secret values."""
import argparse
import io
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = 'config.env.template'
PRIVATE_PARTS = {'.state', '.venv', 'venv', '__pycache__', '.idea', '.vscode', 'local-notes'}
MEDIA_SUFFIXES = {'.mp4', '.mkv', '.avi', '.webm', '.mov', '.m4v', '.ts', '.m2ts', '.wav', '.mp3', '.srt', '.ass'}
TOKEN_PATTERNS = [
    re.compile(rb'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}'),
    re.compile(rb'(?<![A-Za-z0-9_-])mfa\.[A-Za-z0-9_-]{80,}'),
    re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def forbidden_path(name):
    if name == TEMPLATE:
        return False
    path = PurePosixPath(name)
    return (any(part.lower() in PRIVATE_PARTS for part in path.parts)
            or any(part == '.env' or part.startswith('.env.') or '.env.' in part or part.endswith('.env') for part in path.parts)
            or path.suffix.lower() in MEDIA_SUFFIXES | {'.log', '.pid', '.pyc', '.bak'}
            or path.name == 'LIBRARY_REVIEW.md'
            or (path.parts[0] == 'media' and name != 'media/README.md'))


def scan(files, local_values=None):
    issues = []
    # Local checks catch an accidental copy of this installation's credentials
    # or IDs even if they do not resemble a typical provider token.
    known_values = [(value.encode('utf-8'), key) for key, value in (local_values or {}).items()
                    if key in {'DISCORD_TOKEN', 'VLC_PASSWORD', 'DISCORD_GUILD_ID', 'DISCORD_CHANNEL_ID',
                               'HOST_USER_ID', 'CONTROL_ROLE_ID'} and value and len(value) >= 8]
    for name, content in files.items():
        if forbidden_path(name):
            issues.append(f'{name}: local-only file must not be tracked')
        if any(secret in content for secret, _ in known_values):
            issues.append(f'{name}: contains a value from local private configuration')
        if any(pattern.search(content) for pattern in TOKEN_PATTERNS):
            issues.append(f'{name}: possible credential or private key')
        if re.search(rb'(?i)[A-Z]:[\\/]+Users[\\/]+[^\s\\/]+[\\/]', content):
            issues.append(f'{name}: contains a personal Windows home path')
    if TEMPLATE not in files:
        issues.append('Missing blank configuration template')
    else:
        values = dotenv_values(stream=io.StringIO(files[TEMPLATE].decode('utf-8')), interpolate=False)
        for key in ('DISCORD_TOKEN', 'VLC_PASSWORD', 'DISCORD_GUILD_ID', 'DISCORD_CHANNEL_ID',
                    'HOST_USER_ID', 'CONTROL_ROLE_ID'):
            if values.get(key) != '':
                issues.append(f'{TEMPLATE}: {key} must be present and empty')
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', help='Check a commit instead of the staged index, e.g. HEAD')
    args = parser.parse_args()
    try:
        if args.ref:
            names = git('ls-tree', '-r', '--name-only', '-z', args.ref).decode().split('\0')
            files = {name: git('show', f'{args.ref}:{name}') for name in names if name}
        else:
            names = git('ls-files', '-z').decode().split('\0')
            files = {name: git('show', f':{name}') for name in names if name}
    except subprocess.CalledProcessError:
        raise SystemExit('Could not read Git files. Initialize Git and stage the intended files first.') from None
    env_path = ROOT / '.env'
    values = dotenv_values(env_path, encoding='utf-8-sig', interpolate=False) if env_path.exists() else {}
    issues = scan(files, values)
    if issues:
        print('\n'.join(issues))
        raise SystemExit('Public-file check failed. No matching secret values were printed.')
    print(f'PASS: {len(files)} tracked files checked; no forbidden local files or credential matches found.')


if __name__ == '__main__':
    main()
