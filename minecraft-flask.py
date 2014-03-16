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
import tarfile
import datetime
import atexit
import functools
import traceback

app = flask.Flask(__name__)
mc_process = None

# Handlers

def signal_handler(signum=None, frame=None):
	mc_shutdown()
	sys.exit(0)

def subprocess_preexec_handler():
	os.setpgrp()

# Helpers
def response_set_http_code(res, code):
	res.status_code = code
	return res

# Helpers
def response_check_auth(username, password):
	return username == os.environ.get('MINECRAFT_FLASK_USERNAME') and password == os.environ.get('MINECRAFT_FLASK_PASSWORD')

def response_authenticate():
	return response_set_http_code(flask.jsonify(status=ERR_NO_AUTH), 400)

def requires_auth(f):
	@functools.wraps(f)
	def decorated(*args, **kwargs):
		auth = flask.request.authorization
		if not auth or not response_check_auth(auth.username, auth.password):
			return response_authenticate()
		return f(*args, **kwargs)
	return decorated

# Routes
'''
All responses include a status: int field. 0 for no errors
'''
ERR_SERVER_RUNNING = 1
ERR_SERVER_NOT_RUNNING = 2
ERR_NO_MINECRAFT_JAR = 3
ERR_INVALID_REQUEST = 4
ERR_NO_AUTH = 5
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
@requires_auth
def minecraft_start():
	global mc_process
	if not mc_process is None:
		return flask.jsonify(status=ERR_SERVER_RUNNING)
	data = flask.request.get_json(force=True)
	ram = data.get('ram')
	if ram is None:
		return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
	if not os.path.isfile('minecraft_server-run.jar'):
		return response_set_http_code(flask.jsonify(status=ERR_NO_MINECRAFT_JAR), 500)
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
@requires_auth
def minecraft_stop():
	if mc_process is None:
		return flask.jsonify(status=0, retcode=mc_shutdown())
	return flask.jsonify(status=0, retcode=mc_shutdown())

'''
request: {
}
response: {
	pid: 1234
}
'''
@app.route('/pid')
@requires_auth
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
@requires_auth
def minecraft_exec():
	if mc_process is None:
		return response_set_http_code(flask.jsonify(status=ERR_SERVER_NOT_RUNNING), 400)
	data = flask.request.get_json(force=True)
	if not isinstance(data.get('command'), list):
		return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
	mc_process.stdin.write(' '.join(data['command']) + '\n')
	return flask.jsonify(status=0)

'''
request: {
}
response: {
	running: True,
	ping: {
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
}
'''
@app.route('/query')
@requires_auth
def minecraft_query():
	if mc_process is None:
		return flask.jsonify(status=0, running=False)
	data = minecraft_ping('localhost', 25565)
	if data is None:
		return flask.jsonify(status=0, running=False)
	data = {'ping': data, 'running': True, 'status': 0}
	return flask.jsonify(**data)

'''
request: {
	message: 'Hello world'
}
response: {
}
'''
@app.route('/broadcast', methods=['POST'])
@requires_auth
def minceraft_broadcast():
	if mc_process is None:
		return response_set_http_code(flask.jsonify(status=ERR_SERVER_NOT_RUNNING), 400)
	data = flask.request.get_json(force=True)
	if not 'message' in data:
		return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
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
@requires_auth
def minecraft_server_properties():
	if flask.request.method == 'POST':
		data = flask.request.get_json(force=True)
		if not isinstance(data.get('properties'), dict):
			return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
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
@requires_auth
def minecraft_whitelist():
	if flask.request.method == 'POST':
		data = flask.request.get_json(force=True)
		if not isinstance(data.get('players'), list):
			return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
		minecraft_update_whitelist('white-list.txt', data['players'])
	players = minecraft_read_whitelist('white-list.txt')
	return flask.jsonify(status=0, players=players)

'''
request: {
	key: string,
	access_key_id: string,
	policy: string,
	signature: string,
	url: string
}
response: {
	retcode: int
}
'''
@app.route('/backup', methods=['POST'])
@requires_auth
def minecraft_backup():
	if not mc_process is None:
		return flask.jsonify(status=ERR_SERVER_RUNNING)
	data = flask.request.get_json(force=True)
	fields = ['key', 'access_key_id', 'policy', 'signature', 'url']
	curl_command = ['curl']
	for f in fields:
		if not f in data:
			return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
		# curl_command.append('-F')
		# curl_command.append(f + '=' + data[f])
	targz_name = minecraft_targz_world()
	minecraft_trim_old_backups()
	curl_command.extend(['-F', 'key=' + data['key'], '-F', 'AWSAccessKeyId=' + data['access_key_id'], '-F', 'Policy=' + data['policy'], '-F', 'Signature=' + data['signature'], '-F', 'file=@' + targz_name])
	curl_command.append(data['url'])
	retcode = subprocess.call(curl_command)
	return flask.jsonify(status=0, retcode=retcode)

'''
request: {
}
response: {
	version: 1.2.3,
	status: 0
}
'''
@app.route('/version')
@requires_auth
def minecraft_image_version():
	version_file = os.environ.get('IMAGE_VERSION_FILE')
	if version_file is None:
		return flask.jsonify(status=0, version="0")
	try:
		with open(version_file) as f:
			return flask.jsonify(status=0, version=f.readline().strip())
	except IOError:
		return response_set_http_code(flask.jsonify(status=ERR_OTHER), 500)

'''
request: {
	version: string
}
response: {
	retcode: 0
}
'''
@app.route('/select_version', methods=['POST'])
@requires_auth
def minecraft_select_version():
	if not mc_process is None:
		return response_set_http_code(flask.jsonify(status=ERR_SERVER_RUNNING), 400)
	data = flask.request.get_json(force=True)
	if not 'version' in data:
		return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
	retcode = 0
	if not data['version'] is None:
		retcode = subprocess.call(['/opt/minecraft-files/minecraft-select', data['version']])
	return flask.jsonify(status=0, retcode=retcode)

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
	return minecraft_ping_one_seven(host, port)

def minecraft_ping_one_seven(host, port):
	s = None
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect((host, port))

		s.send(pack_string(b'\x00\x04' + pack_string(host.encode('utf8')) + pack_port(port) + b'\x01'))
		s.send(pack_string(b'\x00'))

		packet_length = unpack_varint(s)
		packet_id = unpack_varint(s)
		l = unpack_varint(s)

		response = s.recv(l)
	except Exception as e:
		print('Caught exception in minecraft ping.')
		traceback.print_exc()
		return None
	finally:
		if not s is None:
			s.close()

def minecraft_ping_one_six(host, port):
	def pack_string(s):
		return struct.pack('>H', len(s)) + s.encode('utf-16be')
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect((host, port))
		s.send(struct.pack('BBB', 0xfe, 0x01, 0xfa))
		s.send(pack_string('MC|PingHost'))
		s.send(struct.pack('>H', 7 + 2 * len(host)))
		s.send(struct.pack('B', 74))
		s.send(pack_string(host))
		s.send(struct.pack('>H', port))
		fb = struct.unpack('B', s.recv(1))[0]
		if fb != 0xff:
			raise Exception('Minecraft 1.6 ping server responded with first byte {0}'.format(fb))
		length = struct.unpack('>H', s.recv(2))[0]
		data = s.recv(length * 2)
		response = data.decode('utf-16be').split('\x00')
		if response[0] != '\u00a71':
			raise Exception('Minecraft 1.6 ping server responded with {0}'.format(response))
		return {
			'protocol_version': response[1],
			'minecraft_version': response[2],
			'motd': response[3],
			'current_players': response[4],
			'max_players': response[5]
		}
	except Exception as e:
		print('Caught exception in minecraft ping 1.6.')
		traceback.print_exc()
		return None
	finally:
		if not s is None:
			s.close()
	return None

def minecraft_ping_one_four(host, port):
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		s.connect((host, port))
		s.send(struct.pack('BB', 0xfe, 0x01))
		packet_id = struct.unpack('B', s.recv(1))[0]
		if packet_id != 0xff:
			raise Exception('Minecraft 1.4 ping invalid packet id {0}'.format(packet_id))
		length = struct.unpack('>H', s.recv(2))[0]
		data = s.recv(length * 2).decode('utf-16be')
		parts = data[2:].split('\x00')
		return {
			'ping_version': parts[0],
			'protocol_version': parts[1],
			'minecraft_version': parts[2],
			'motd': parts[3],
			'current_players': parts[4],
			'max_players': parts[5]
		}
	except Exception as e:
		print('Caught exception in minecraft ping 1.4.')
		traceback.print_exc()
		return None
	finally:
		if not s is None:
			s.close()
	return None

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

def minecraft_targz_world():
	if os.path.isfile('backups'):
		os.remove('backups')
	if not os.path.exists('backups'):
		os.makedirs('backups')
	targz_name = 'backups/minecraft-world_backup-' + str(datetime.datetime.today()).replace('-', '_').replace(' ', '-').replace(':', '_').replace('.', '-') + '.tar.gz'
	world_name = minecraft_read_server_properties('server.properties').get('level-name')
	if world_name is None or not (os.path.exists(world_name) and os.path.isdir(world_name)):
		raise RuntimeError('World name not found.')
	if os.path.exists(targz_name):
		if os.path.isfile(targz_name):
			os.remove(targz_name)
		else:
			shutil.rmtree(targz_name)
	with tarfile.open(targz_name, 'w:gz') as tar:
		tar.add(world_name, arcname='world')
	return targz_name

def minecraft_trim_old_backups():
	if os.path.isfile('backups'):
		os.remove('backups')
	if not os.path.exists('backups'):
		os.makedirs('backups')
	backups = [f for f in os.listdir('backups') if f.endswith('.tar.gz')]
	backups.sort()
	for i in range(10, len(backups)):
		os.remove('backups/' + backups[i - 10])

# Main

def main():
	for sig in [signal.SIGTERM, signal.SIGINT]:
		signal.signal(sig, signal_handler)

	app.run(host='0.0.0.0', debug=True)

if __name__ == '__main__':
	main()
