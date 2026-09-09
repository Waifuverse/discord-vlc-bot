# Public release checks

1. Run the tests and `python -m pip check`.
2. Review the staged file list. It should contain source, scripts, documentation, tests, the MIT license, the blank template and GitHub workflow only.
3. Run `python scripts/check_public_files.py`. This checks the **Git index**, so stage intended changes first.
4. Confirm `.env`, `.state` and `.venv` remain ignored with `git check-ignore`.
5. After committing, run `python scripts/check_public_files.py --ref HEAD` and verify a clean checkout can run `setup.ps1` to create a fresh `.env` without requiring any maintainer credentials.
6. Review repository ownership, visibility and license, then push the intended commit. Check the GitHub Actions result after pushing. CI workflow presence alone does not prove CI has run.

Only `config.env.template` is public. Setup creates the real `.env` with blank Discord fields and a newly generated VLC password. Existing `.env` files are preserved.

Use `git archive` from a reviewed commit when distributing a ZIP. Do not zip the working directory: it can include ignored credentials, video files, caches and runtime state.
