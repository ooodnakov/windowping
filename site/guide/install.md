# Install

`windowping` requires **Python 3.11+** and uses only the Python standard library — there are no third-party Python dependencies.

## From Git Checkout (with `install.sh`)

```sh
git clone https://github.com/ooodnakov/windowping.git ~/Projects/windowping
cd ~/Projects/windowping
./install.sh                 # ~/.local/bin/windowping + systemd user unit
windowping config init       # write ~/.config/windowping/config.toml
$EDITOR ~/.config/windowping/config.toml
windowping status            # live meters
windowping ping --dry-run    # what a ping would send
```

`install.sh` is optional — the tool is a plain Python package and can be run directly without installing:

```sh
PYTHONPATH=$PWD python3 -m windowping status
```

## From PyPI

```sh
pipx install windowping        # or: pip install --user windowping
windowping config init
windowping service install
```

## Verify the Installation

After creating `~/.config/windowping/config.toml` and enabling your providers:

1. Run `windowping doctor` to check Python, config permissions (`0o600`), clock skew, provider usage endpoints, CLI binaries, Telegram bot token, and systemd status. See [Doctor & Diagnostics](/operations/doctor).
2. Run `windowping status` to verify live 5h and weekly meters.
3. Run `windowping ping --dry-run` to preview what a ping would send without spending quota.
4. Install and start the [systemd user service](/operations/systemd) (`windowping service install`).
