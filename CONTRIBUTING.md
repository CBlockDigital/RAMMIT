# Contributing to RAMMIT

Thanks for helping. Small fixes are as welcome as features. Issues labelled [good first issue](https://github.com/CBlockDigital/RAMMIT/labels/good%20first%20issue) are a good place to start.

- **Questions and ideas:** [Discussions](https://github.com/CBlockDigital/RAMMIT/discussions).
- **Bugs:** [Issues](https://github.com/CBlockDigital/RAMMIT/issues/new/choose), using the bug template.
- **Security problems:** please don't open a public issue. Use [Report a vulnerability](https://github.com/CBlockDigital/RAMMIT/security/advisories/new). [SECURITY.md](SECURITY.md) says what to include.

We aim to reply to every issue and pull request within a day.

## Run it locally (Windows 10/11, Python 3.13)

```powershell
git clone https://github.com/CBlockDigital/RAMMIT.git
cd RAMMIT\Production\RAMMIT-Stable
python -m pip install -r requirements.txt
python RAMMIT.py
```

It keeps its data in `Config\` next to `RAMMIT.py`. That folder holds real Roblox logins, so it's git-ignored. Never commit it, and never paste its contents into an issue.

The installer lives in `Production\Installer` (`python Installer\Installer.py`). Set `RAMMIT_INSTALLER_TEST=1` to make it use test registry keys and temp folders instead of your real install.

## Run the tests

From `Production\RAMMIT-Stable`:

```powershell
python -m pyflakes App Tests Tools RAMMIT.py
python -m unittest discover -s Tests -p "Test*.py"
python Tools\SyncThemes.py --check
```

From `Production\Installer`:

```powershell
python -m pyflakes Installer Tests
python -m unittest discover -s Tests -p "Test*.py"
```

Both folders also have headless UI tests (`Tests\TestUi.mjs`, run with Node, puppeteer-core and Chrome). Their READMEs show the command. CI runs the checks above on every push and pull request.

## House rules

The full list is in [`Production/RAMMIT-Stable/AGENTS.md`](Production/RAMMIT-Stable/AGENTS.md). The ones that matter most:

- **Never log, return or store a `.ROBLOSECURITY` cookie** outside `Storage`/`Crypto`. No real cookies in tests, docs or commits.
- **Names:** PascalCase for every identifier (variables, functions, CSS classes, HTML ids, JSON keys we author) and for file and folder names. Extensions stay lowercase.
- **Themes are full copies.** Change shared UI code in `Src/Dark`, then run `python Tools\SyncThemes.py` so Light, CBlock and MyCustomTheme get it too.
- **No inline scripts, no `innerHTML` with data.** The page runs under a strict Content-Security-Policy.
- **Fix a bug, add a test.**

## Pull requests

1. Fork, then branch from `main`.
2. Keep each PR to one change and explain why in the description.
3. Make sure the checks above pass. CI must be green before merge.
4. If users would notice the change, add a line to [`Production/RAMMIT-Stable/CHANGELOG.md`](Production/RAMMIT-Stable/CHANGELOG.md).

By contributing you agree that your contribution is licensed under the [GPL-3.0](LICENSE), like the rest of RAMMIT.
