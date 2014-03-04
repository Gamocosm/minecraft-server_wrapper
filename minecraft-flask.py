import flask
import sys
import signal
import subprocess
import os
import socket
import struct
import json

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
	data = MinecraftPing('localhost', 25565).ping()
	data['running'] = True
	return flask.jsonify(**data)

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

	app.run()

if __name__ == '__main__':
	main()