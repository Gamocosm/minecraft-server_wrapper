minecraft-server_wrapper
========================

Lightweight Python webserver that provides a REST API for Minecraft servers.
Communicates with Minecraft server by piping stdin.
Pipes stdout and stderr to `minecraft-stdout.log` and `minecraft-stderr.log` in the working directory.

### Usage
- `python3 mcsw.py [daemonize|stop pidfile] [--auth=auth-file]`
	- the auth file should contain two lines with the username and password for HTTP basic auth
	- if no auth file is specified, no authentication will be performed (e.g. for development)
- `./run.sh [args...]` for development
	- create a "minecraft" folder (will be ignored by git)
	- put a "minecraft\_server-run.[jar|sh]" in there
	- script will `cd` into the "minecraft" folder, pass args, and run there

### Systemd
- the service file is from Gamocosm; you can tweak it if you're using this separately
- can view its logs with `journalctl -u mcsw`

### Dependencies
- Flask
