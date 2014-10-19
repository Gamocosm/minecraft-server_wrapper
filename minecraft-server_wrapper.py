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
import logging
import urllib.request
import zipfile
import distutils.version
import pwd
import time

VERSION = distutils.version.StrictVersion('0.3.0')
SOURCE_URL = 'https://raw.githubusercontent.com/Raekye/minecraft-server_wrapper/master/minecraft-flask-minified.py'

app = flask.Flask(__name__)
mc_process = None
auth_file = None
minecraft_stdout = None
minecraft_stderr = None

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
def response_check_auth(u, p):
	try:
		with open(auth_file) as f:
			content = f.readlines()
		if len(content) < 2:
			return False
		return content[0].strip() == u and content[1].strip() == p
	except OSError:
		app.logger.exception('Auth file ' + auth_file + ' not found')
		return False

def response_authenticate():
	res = response_set_http_code(flask.jsonify(status=ERR_NO_AUTH), 401)
	res.headers.add('WWW-Authenticate', 'Basic realm="Login Required"')
	return res

def requires_auth(f):
	@functools.wraps(f)
	def decorated(*args, **kwargs):
		auth = flask.request.authorization
		if not auth_file is None:
			if not auth or not response_check_auth(auth.username, auth.password):
				return response_authenticate()
		return f(*args, **kwargs)
	return decorated

@app.after_request
def after_request(res):
	sys.stdout.flush()
	return res

# Routes
'''
All responses include a status: int field. 0 for no errors
'''
ERR_SERVER_RUNNING = 1
ERR_SERVER_NOT_RUNNING = 2
ERR_NO_MINECRAFT = 3
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
	global minecraft_stdout
	global minecraft_stderr
	if not minecraft_is_running():
		data = flask.request.get_json(force=True)
		ram = data.get('ram')
		if ram is None:
			return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
		cmd = ['java', '-Xmx' + ram, '-Xms' + ram, '-jar', 'minecraft_server-run.jar', 'nogui']
		shell = False
		if not os.path.isfile('minecraft_server-run.jar'):
			if os.path.isfile('minecraft_server-run.sh') and os.access('minecraft_server-run.sh', os.X_OK):
				cmd = ['./minecraft_server-run.sh']
				shell = True
			else:
				return response_set_http_code(flask.jsonify(status=ERR_NO_MINECRAFT), 500)
		try:
			if not minecraft_stdout is None:
				minecraft_stdout.close()
		except OSError:
			app.logger.exception('Error closing Minecraft stdout file')
		try:
			if not minecraft_stdout is None:
				minecraft_stderr.close()
		except OSError:
			app.logger.exception('Error closing Minecraft stderr file')
		try:
			minecraft_stdout = open('minecraft-stdout.log', 'a')
			minecraft_stderr = open('minecraft-stderr.log', 'a')
		except OSError:
			app.logger.exception('Error opening Minecraft stdout and stderr files')
			return response_set_http_code(flask.jsonify(status=ERR_OTHER), 500)
		mc_process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=minecraft_stdout, stderr=minecraft_stderr, universal_newlines=True, preexec_fn=subprocess_preexec_handler, shell=shell)
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
	if not minecraft_is_running():
		return flask.jsonify(status=0, retcode=0)
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
	if not minecraft_is_running():
		return flask.jsonify(status=0, pid=0)
	return flask.jsonify(status=0, pid=mc_process.pid)

'''
request: {
	command: "string"
}
response: {
}
'''
@app.route('/exec', methods=['POST'])
@requires_auth
def minecraft_exec():
	if not minecraft_is_running():
		return response_set_http_code(flask.jsonify(status=ERR_SERVER_NOT_RUNNING), 400)
	data = flask.request.get_json(force=True)
	command = data.get('command')
	if command is None:
		return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
	mc_process.stdin.write(command + '\n')
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
@app.route('/minecraft_properties', methods=['GET', 'POST'])
@requires_auth
def minecraft_server_properties():
	if flask.request.method == 'POST':
		data = flask.request.get_json(force=True)
		if not isinstance(data.get('properties'), dict):
			return response_set_http_code(flask.jsonify(status=ERR_INVALID_REQUEST), 400)
		properties = MinecraftProperties('server.properties')
		properties.update_properties(data['properties'])
	properties = minecraft_read_server_properties()
	return flask.jsonify(status=0, properties=properties)

'''
request: {
}
response: {
}
'''
@app.route('/backup', methods=['POST'])
@requires_auth
def minecraft_backup():
	if minecraft_is_running():
		return flask.jsonify(status=ERR_SERVER_RUNNING)
	zip_name = minecraft_zip_world()
	minecraft_trim_old_backups()
	return flask.jsonify(status=0)

'''
request: {
	'url': string, # (optional)
	'min_version': string, # (optional)
}
response: {
}
'''
@app.route('/update_wrapper', methods=['POST'])
@requires_auth
def update_wrapper():
	if minecraft_is_running():
		return flask.jsonify(status=ERR_SERVER_RUNNING)
	data = flask.request.get_json(force=True)
	url = data.get('url', SOURCE_URL)
	min_version = data.get('min_version')
	if min_version is None or VERSION < distutils.version.StrictVersion(min_version):
		download_file(url, __file__)
	return flask.jsonify(status=0)

'''
request: {
}
response: {
	'version': '1.2.3'
}
'''
@app.route('/version')
@requires_auth
def version():
	return flask.jsonify(status=0, version=str(VERSION))

'''
request: {
}
response: {
}
'''
@app.route('/download_world')
@requires_auth
def minecraft_download_world():
	if minecraft_is_running():
		return flask.jsonify(status=ERR_SERVER_RUNNING)
	zip_name = os.path.realpath(minecraft_zip_world())
	return flask.send_file(zip_name, mimetype='application/zip', as_attachment=True, attachment_filename='minecraft-world-' + time.strftime('%Y_%b_%d').lower() + '.zip')

# Minecraft functions

def mc_shutdown():
	global mc_process
	if not minecraft_is_running():
		return
	retcode = -1
	mc_process.stdin.write('stop\n')
	try:
		retcode = mc_process.wait(4)
	except subprocess.TimeoutExpired:
		mc_process.terminate()
		try:
			retcode = mc_process.wait(4)
		except subprocess.TimeoutExpired:
			mc_process.kill()
	mc_process = None
	return retcode

class MinecraftProperties:
	WHITELISTED_PROPERTIES = {
		'allow-flight'
		, 'allow-nether'
		, 'announce-player-achievements'
		, 'difficulty'
		, 'enable-command-block'
		, 'force-gamemode'
		, 'gamemode'
		, 'generate-structures'
		, 'generator-settings'
		, 'hardcore'
		, 'level-name'
		, 'level-seed'
		, 'level-type'
		, 'max-build-height'
		, 'max-players'
		, 'motd'
		, 'online-mode'
		, 'op-permission-level'
		, 'player-idle-timeout'
		, 'pvp'
		, 'resource-pack'
		, 'server-name'
		, 'snooper-enabled'
		, 'spawn-animals'
		, 'spawn-monsters'
		, 'spawn-npcs'
		, 'spawn-protection'
		, 'view-distance'
		, 'white-list'
	}
	def __init__(self, f):
		self.f = f

	def update_properties(self, keyvals):
		tmp = tempfile.NamedTemporaryFile(delete=False)
		keyvals = keyvals.copy()
		try:
			with open(self.f) as src:
				for line in src:
					if '=' in line:
						k = line.split('=')[0]
						if k in keyvals:
							tmp.write(bytes(k + '=' + keyvals[k] + '\n', 'utf8'))
							del(keyvals[k])
							continue
					tmp.write(bytes(line, 'utf8'))
			for k in keyvals:
				if k in MinecraftProperties.WHITELISTED_PROPERTIES:
					tmp.write(bytes(k + '=' + keyvals[k] + '\n', 'utf8'))
			tmp.close()
			os.remove(self.f)
			shutil.move(tmp.name, self.f)
		finally:
			try:
				os.remove(tmp.name)
			except IOError:
				pass

def minecraft_read_server_properties():
	properties = {}
	try:
		with open('server.properties') as f:
			for line in f:
				if '=' in line:
					keyval = line.split('=')
					properties[keyval[0]] = keyval[1].strip()
	except IOError:
		pass
	return properties

def minecraft_trim_old_backups():
	mkdir_silent('backups')
	backups = [f for f in os.listdir('backups') if f.endswith('.zip')]
	backups.sort()
	for i in range(10, len(backups)):
		os.remove('backups/' + backups[i - 10])

def minecraft_world_name():
	return minecraft_read_server_properties().get('level-name')

def minecraft_zip_world():
	if os.path.isfile('backups'):
		os.remove('backups')
	if not os.path.exists('backups'):
		os.makedirs('backups')
	zip_name = 'backups/minecraft-world_backup-' + str(datetime.datetime.today()).replace('-', '_').replace(' ', '-').replace(':', '_').replace('.', '-') + '.zip'
	world_name = minecraft_world_name()
	if world_name is None or not (os.path.exists(world_name) and os.path.isdir(world_name)):
		raise RuntimeError('World name not found.')
	if os.path.exists(zip_name):
		if os.path.isfile(zip_name):
			os.remove(zip_name)
		else:
			shutil.rmtree(zip_name)
	z = zipfile.ZipFile(zip_name, 'w')
	zip_directory(world_name, z)
	return zip_name

def zip_directory(path, z):
	for root, dirs, files in os.walk(path):
		for f in files:
			z.write(os.path.join(root, f))

def minecraft_is_running():
	global mc_process
	if mc_process is None:
		return False
	if not mc_process.poll() is None:
		mc_process = None
		return False
	return True

def download_file(url, path):
	path = os.path.realpath(path)
	with open(path + '.tmp', 'wb') as tmp:
		with urllib.request.urlopen(url) as response:
			shutil.copyfileobj(response, tmp)
		os.rename(tmp.name, path)
	return path

def mkdir_silent(path):
	if os.path.isfile(path):
		os.remove(path)
	if not os.path.exists(path):
		os.makedirs(path)

def rm_silent(path):
	if not os.path.exists(path):
		return
	if os.path.isfile(path):
		os.remove(path)
	else:
		shutil.rmtree(path)

# Main

def main():
	global auth_file
	if len(sys.argv) > 1:
		auth_file = sys.argv[1]
	for sig in [signal.SIGTERM, signal.SIGINT]:
		signal.signal(sig, signal_handler)
	handler = logging.StreamHandler()
	app.logger.addHandler(handler)
	app.run(host='0.0.0.0', use_reloader=True)

if __name__ == '__main__':
	main()
