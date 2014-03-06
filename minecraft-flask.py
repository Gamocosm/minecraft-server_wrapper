import flask
import sys
import signal
import subprocess
import os
import socket
import struct
import json
import shutil
import tempfile

app = flask.Flask(__name__)
mc_process = None

# Handlers

def signal_handler(signum=None, frame=None):
	mc_shutdown()
	sys.exit(0)

def subprocess_preexec_handler():
	os.setpgrp()

# Routes
'''
All responses include a status: int field. 0 for no errors
'''
ERR_SERVER_RUNNING = 1
ERR_SERVER_NOT_RUNNING = 2
ERR_NO_MINECRAFT_JAR = 3
ERR_INVALID_REQUEST = 4
ERR_OTHER = 128

@app.route('/')
def index():
	return flask.jsonify(message='Minecraft server web wrapper.', status=0)

'''
request: {
	ram: '1024M'
}
response: {
	pid: 1234
}
'''
@app.route('/start', methods=['POST'])
def minecraft_start():
	global mc_process
	if not mc_process is None:
		return flask.jsonify(status=ERR_SERVER_RUNNING)
	data = flask.request.get_json(force=True)
	ram = data.get('ram')
	if ram is None:
		return flask.jsonify(status=ERR_INVALID_REQUEST)
	if not os.path.isfile('minecraft_server.jar'):
		return flask.jsonify(status=ERR_NO_MINECRAFT_JAR)
	mc_process = subprocess.Popen(['java', '-Xmx' + ram, '-Xms' + ram, '-jar', 'minecraft_server-run.jar', 'nogui'], stdout=None, stdin=subprocess.PIPE, stderr=None, universal_newlines=True, preexec_fn=subprocess_preexec_handler, cwd='/home/mcuser/minecraft/', shell=False)
	return flask.jsonify(status=0, pid=mc_process.pid)

'''
request: {
}
response: {
	retcode: 1234
}
'''
@app.route('/stop')
def minecraft_stop():
	if mc_process is None:
		return flask.jsonify(status=ERR_SERVER_NOT_RUNNING)
	return flask.jsonify(status=0, retcode=mc_shutdown())

'''
request: {
}
response: {
	pid: 1234
}
'''
@app.route('/pid')
def minecraft_pid():
	if mc_process is None:
		return flask.jsonify(status=ERR_SERVER_NOT_RUNNING)
	return flask.jsonify(status=0, pid=mc_process.pid)

'''
request: {
	command: ['broadcast', 'hello world']
}
response: {
}
'''
@app.route('/exec', methods=['POST'])
def minecraft_exec():
	if mc_process is None:
		return flask.jsonify(status=ERR_SERVER_NOT_RUNNING)
	data = flask.request.get_json(force=True)
	if not isinstance(data.get('command'), list):
		return flask.jsonify(status=ERR_INVALID_REQUEST)
	mc_process.stdin.write(' '.join(data['command']) + '\n')
	return flask.jsonify(status=0)

'''
request: {
}
response: {
	running: True,
	description: 'A Minecraft Server',
	players: {
		max: 20,
		online: 0
	},
	version: {
		name: '1.7.5',
		protocol: 4
	}
}
'''
@app.route('/query')
def minecraft_query():
	if mc_process is None:
		return flask.jsonify(status=0, running=False)
	data = minecraft_ping('localhost', 25565)
	data['running'] = True
	data['status'] = 0
	return flask.jsonify(**data)

'''
request: {
	message: 'Hello world'
}
response: {
}
'''
@app.route('/broadcast', methods=['POST'])
def minceraft_broadcast():
	if mc_process is None:
		return flask.jsonify(status=ERR_SERVER_NOT_RUNNING)
	data = flask.request.get_json(force=True)
	if not 'message' in data:
		return flask.jsonify(status=ERR_INVALID_REQUEST)
	mc_process.stdin.write('say ' + data['message'] + '\n')
	return flask.jsonify(status=0)

'''
- properties only mandatory for POST
- returns new/current properties
request: {
	properties: {
		key: value
	}
}
response: {
	properties: {
		key: value
	}
}
'''
@app.route('/server_properties', methods=['GET', 'POST'])
def minecraft_server_properties():
	if flask.request.method == 'POST':
		if not mc_process is None:
			return flask.jsonify(status=ERR_SERVER_RUNNING)
		data = flask.request.get_json(force=True)
		if not isinstance(data.get('properties', dict)):
			return flask.jsonify(status=ERR_INVALID_REQUEST)
		properties = MinecraftProperties('server.properties')
		properties.update_properties(data['properties'])
	properties = minecraft_read_server_properties('server.properties')
	return flask.jsonify(status=0, properties=properties)

'''
- players only mandatory for POST
- returns new/current whitelisted players
request: {
	players: ['a', 'b', 'c']
}
response: {
	players: ['a', 'b', 'c']
}
'''
@app.route('/whitelist', methods=['GET', 'POST'])
def minecraft_whitelist():
	if flask.request.method == 'POST':
		if not mc_process is None:
			return flask.jsonify(status=ERR_SERVER_RUNNING)
		data = flask.request.get_json(force=True)
		if not isinstance(data.get('players', list)):
			return flask.jsonify(status=ERR_INVALID_REQUEST)
		minecraft_update_whitelist(data['players'])
	players = minecraft_read_whitelist('white-list.txt')
	return flask.jsonify(status=0, players=players)

# Minecraft functions

def mc_shutdown():
	global mc_process
	if mc_process is None:
		return None
	mc_process.stdin.write('stop\n')
	retcode = mc_process.wait()
	mc_process = None
	return retcode

class MinecraftProperties:
	def __init__(self, f):
		self.f = f

	def update_properties(self, keyvals):
		tmp = tempfile.NamedTemporaryFile(delete=False)
		with open(self.f) as src:
			for line in src:
				if '=' in line:
					k = line.split('=')[0]
					if k in keyvals:
						tmp.write(bytes(k + '=' + keyvals[k] + '\n', 'utf8'))
						continue
				tmp.write(bytes(line, 'utf8'))
		tmp.close()
		os.remove(self.f)
		shutil.move(tmp.name, self.f)

def pack_varint(x):
	varint = b''
	for i in range(5):
		b = x & 0x7f
		x >>= 7
		varint += struct.pack('B', b | (0x80 if x > 0 else 0))
		if x == 0:
			break
	return varint

def unpack_varint(s):
	x = 0
	for i in range(5):
		b = ord(s.recv(1))
		x |= (b & 0x7f) << 7 * i
		if not (b & 0x80):
			break
	return x

def pack_string(msg):
	return pack_varint(len(msg)) + msg

def pack_port(port):
	return struct.pack('>H', port)

def minecraft_ping(host, port):
	s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	s.connect((host, port))

	s.send(pack_string(b'\x00\x04' + pack_string(host.encode('utf8')) + pack_port(port) + b'\x01'))
	s.send(pack_string(b'\x00'))

	packet_length = unpack_varint(s)
	packet_id = unpack_varint(s)
	l = unpack_varint(s)

	response = s.recv(l)

	s.close()

	return json.loads(response.decode('utf8'))

def minecraft_read_server_properties(path):
	properties = {}
	with open(path) as f:
		for line in f:
			if '=' in line:
				keyval = line.split('=')
				properties[keyval[0]] = keyval[1].strip()
	return properties

def minecraft_read_whitelist(path):
	players = []
	with open(path) as f:
		for line in f:
			if len(line.strip()) > 0:
				players.append(line.strip())
	return players

def minecraft_update_whitelist(path, players):
	with open(path, 'w') as f:
		for each in players:
			f.write(each + '\n')

# Main

def main():
	for sig in [signal.SIGTERM, signal.SIGINT]:
		signal.signal(sig, signal_handler)

	app.run(host='0.0.0.0')

if __name__ == '__main__':
	main()