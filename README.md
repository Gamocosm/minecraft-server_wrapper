minecraft-server_wrapper
========================

Light Python Flask webserver that provides a REST API for Minecraft servers.
Communicates with Minecraft server by piping stdin.
Pipes stdout and stderr to `minecraft-stdout.log` and `minecraft-stderr.log` in the working directory.

### Usage
- `python3 minecraft-server_wrapper.py [auth-file]`
	- the auth file should contain two lines with the username and password for HTTP basic auth
	- if no auth file is specified, no authentication will be performed (e.g. for development)
- `./run.sh` for development
	- creates a "minecraft" folder which is ignored
	- you should place "minecraft\_server-run.[jar|sh]" in here
	- pipes stdout and stderr of the wrapper to "minecraft/minecraft-server\_wrapper-log.txt"

### Supervisord
- the supervisord config file is from Gamocosm

### Dependencies
- Flask
