# Contributing

Use Python 3.11+ on Windows. Create a virtual environment and install `requirements.txt`. Run the test suite before submitting a pull request:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests do not need a Discord token, an installed VLC player, or real videos. They use temporary files, local HTTP fixtures and mocked Discord interactions. Integration changes should also be checked against a separate VLC instance and a test Discord server.

Edit `config.env.template` only to change documented configuration fields. Keep credentials in your ignored `.env`, media outside Git, and local data under `.state`. After staging changes, run:

```powershell
.\.venv\Scripts\python.exe scripts/check_public_files.py
git diff --cached --stat
```

The public-file check examines staged contents, including accidental copies of locally configured tokens. It is an additional check, not a guarantee that every kind of secret can be detected. Never use `git add -f` for credentials or runtime files.

Changes to commands or buttons should update the help guide and corresponding interaction tests. Preserve per-action access checks, persistent button IDs, playlist conflict detection and the local-only VLC connection.
