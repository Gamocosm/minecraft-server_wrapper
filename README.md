minecraft-server_wrapper
========================

Lightweight Python webserver that provides a REST API for Minecraft servers.
Communicates with Minecraft server by piping stdin.
Pipes stdout and stderr to `minecraft-stdout.log` and `minecraft-stderr.log` in the working directory.

### Usage
`python3 mcsw.py [daemonize|stop pidfile] [--auth=auth-file]`
- the auth file should contain two lines with the username and password for HTTP basic auth
- if no auth file is specified, no authentication will be performed (e.g. for development)

### Development
It is recommended you create a "minecraft" folder (will be ignored by git), put a `minecraft_server-run.[jar|sh]`, and run the wrapper there (`cd minecraft`, `python3 ../mcsw.py [args...]`).

### Client
There is a client for Gamocosm servers in `bin/mcsw-client` which is just a helper script for `curl`ing the wrapper.
It expects the auth file to be in `/opt/gamocosm/mcsw-auth.txt`; if it cannot find it, it will use a blank password.
You can read it or modify it for different setups (it is just a shell script).

Examples:
```
bin/mcsw-client start '{ "ram": "1024M" }'
bin/mcsw-client stop
bin/mcsw-client exec '{ "command": "say hi" }'
```

### Systemd
- the service file is from Gamocosm; you can tweak it if you're using this separately
- can view its logs with `journalctl -u mcsw`

### Dependencies
- Flask
