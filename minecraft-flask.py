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

# Classes
class MinecraftPing:
	def __init__(self, host, port):
		self.host = host
		self.port = port

	def ping(self):
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect((self.host, self.port))

		s.send(pack_string(b'\x00\x04' + pack_string(self.host.encode('utf8')) + pack_port(self.port) + b'\x01'))
		s.send(pack_string(b'\x00'))

		packet_length = unpack_varint(s)
		packet_id = unpack_varint(s)
		l = unpack_varint(s)

		response = s.recv(l)

		s.close()

		return json.loads(response.decode('utf8'))

app = flask.Flask(__name__)
mc_process = None

# Handlers

def signal_handler(signum=None, frame=None):
	mc_shutdown()
	sys.exit(0)

def subprocess_preexec_handler():
	os.setpgrp()

# Routes

@app.route('/')
def index():
	return 'Minecraft server web wrapper.'

@app.route('/start', methods=['POST'])
def minecraft_start():
	global mc_process
	if not mc_process is None:
		return flask.jsonify(error='Minecraft server already running.')
	data = flask.request.get_json(force=True)
	if not (('command' in data) and isinstance(data['command'], list)):
		return flask.jsonify(error='Invalid command.')
	mc_process = subprocess.Popen(data['command'], stdout=None, stdin=subprocess.PIPE, stderr=None, universal_newlines=True, preexec_fn=subprocess_preexec_handler, shell=False)
	return flask.jsonify(status='ok', pid=mc_process.pid)

@app.route('/stop')
def minecraft_stop():
	if mc_process is None:
		return flask.jsonify(error='Minecraft server not running.')
	return flask.jsonify(retcode=mc_shutdown())

@app.route('/pid')
def minecraft_pid():
	if mc_process is None:
		return flask.jsonify(error='Minecraft server not running.')
	return flask.jsonify(pid=mc_process.pid)

@app.route('/exec', methods=['POST'])
def minecraft_exec():
	if mc_process is None:
		return flask.jsonify(error='Minecraft server not running.')
	data = flask.request.get_json(force=True)
	if not (('command' in data) and isinstance(data['command'], list)):
		return flask.jsonify(error='Invalid command.')
	mc_process.stdin.write(' '.join(data['command']) + '\n')
	return flask.jsonify(status='ok')

@app.route('/query')
def minecraft_query():
	if mc_process is None:
		return flask.jsonify(running=False)
	data = minecraft_ping('localhost', 25565)
	data['running'] = True
	return flask.jsonify(**data)

@app.route('/broadcast')
def minceraft_broadcast():
	if mc_process is None:
		return flask.jsonify(error='Minecraft server not running.')
	data = flask.request.get_json(force=True)
	if not 'message' in data:
		return flask.jsonify(error='Invalid message')
	mc_process.stdin.write(message + '\n')
	return flask.jsonify(status='ok')

@app.route('/update_server_properties', methods=['POST'])
def minecraft_update_server_properties():
	if not mc_process is None:
		return flask.jsonify(error='Minecraft server already running.')
	data = flask.request.get_json(force=True)
	if not (('properties' in data) and isinstance(data['properties'], dict)):
		return flask.jsonify(error='Invalid properties')
	properties = MinecraftProperties('server.properties')
	properties.update_properties(data['properties'])
	return flask.jsonify(status='ok')


# Minecraft functions

def mc_shutdown():
	global mc_process
	if mc_process is None:
		return None
	mc_process.stdin.write('stop\n')
	retcode = mc_process.wait()
	mc_process = None
	return retcode

# Main

def main():
	for sig in [signal.SIGTERM, signal.SIGINT]:
		signal.signal(sig, signal_handler)

	app.run(debug=True)

if __name__ == '__main__':
	main()