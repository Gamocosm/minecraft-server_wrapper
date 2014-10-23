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

VERSION = distutils.version.StrictVersion('0.4.0')
SOURCE_URL = 'https://raw.githubusercontent.com/Gamocosm/minecraft-server_wrapper/master/minecraft-server_wrapper.py'

ERR_SERVER_RUNNING = 'server_running'
ERR_SERVER_NOT_RUNNING = 'server_not_running'
ERR_NO_MINECRAFT = 'no_minecraft'
ERR_INVALID_REQUEST = 'invalid_request'
ERR_NO_AUTH = 'no_auth'
ERR_OTHER = 'error_other'

class Minecraft:
	def __init__(self):
		self.process = None
		self.stdout = None
		self.stderr = None

	def pid(self):
		if self.process is None:
			return 0
		if self.process.poll() is None:
			return self.process.pid
		return 0

	def start(self, ram):
		if self.pid() != 0:
			return None
		cmd = ['java', '-Xmx' + ram, '-Xms' + ram, '-jar', 'minecraft_server-run.jar', 'nogui']
		if os.path.isfile('minecraft_server-run.sh'):
			cmd = ['bash', 'minecraft_server-run.sh']
		elif not os.path.isfile('minecraft_server-run.jar'):
			return ERR_NO_MINECRAFT
		self.cleanup()
		try:
			self.stdout = open('minecraft-stdout.log', 'a')
			self.stderr = open('minecraft-stderr.log', 'a')
		except OSError:
			app.logger.exception('Error opening Minecraft stdout and stderr files')
			return ERR_OTHER
		self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=self.stdout, stderr=self.stderr, universal_newlines=True, preexec_fn=subprocess_preexec_handler, shell=False)
		return None

	def stop(self):
		if self.pid() == 0:
			return None
		try:
			self.process.communicate('stop\n', 8)
		except subprocess.TimeoutExpired:
			self.process.terminate()
			try:
				self.process.wait(4)
			except subprocess.TimeoutExpired:
				self.process.kill()
		self.process = None
		self.cleanup()
		return None
	
	def exec(self, command):
		if self.pid() == 0:
			return ERR_SERVER_RUNNING
		self.process.stdin.write(command + '\n')
		return None

	def properties(props=None):
		if props is None:
			try:
				with open('server.properties') as f:
					for line in f:
						if '=' in line:
							keyval = line.split('=')
							props[keyval[0]] = keyval[1].strip()
			except OSError:
				pass
			return props
		tmp = tempfile.NamedTemporaryFile(delete=False)
		props = props.copy()
		try:
			with open('server.properties', encoding='utf8') as src:
				for line in src:
					if '=' in line:
						k = line.split('=')[0]
						if k in props:
							tmp.write(bytes(k + '=' + props[k].strip() + '\n', 'utf8'))
							del(props[k])
							continue
					tmp.write(bytes(line, 'utf8'))
			for k in props:
				tmp.write(bytes(k + '=' + props[k].strip() + '\n', 'utf8'))
			tmp.close()
			os.remove(self.f)
			shutil.move(tmp.name, self.f)
		finally:
			try:
				if os.path.isfile(tmp.name):
					os.remove(tmp.name)
			except OSError:
				pass
		return self.properties()

	def cleanup(self):
		try:
			if not self.stdout is None:
				self.stdout.close()
		except OSError:
			app.logger.exception('Error closing Minecraft stdout file')
		try:
			if not self.stderr is None:
				self.stderr.close()
		except OSError:
			app.logger.exception('Error closing Minecraft stderr file')

app = flask.Flask(__name__)
minecraft = Minecraft()
auth_file = None

# Handlers

'''
Handler for sigint and sigterm
'''
def signal_handler(signum=None, frame=None):
	minecraft.stop()
	sys.exit(0)

'''
Separate process group from parent
'''
def subprocess_preexec_handler():
	os.setpgrp()

# Helpers

def build_response(status, http_status_code=200, **kwargs):
	res = flask.jsonify(status=status, **kwargs)
	res.status_code = http_status_code
	return res

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
	res = build_response(ERR_NO_AUTH, 401)
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
	sys.stderr.flush()
	return res

# Routes

'''
All responses include a status: string field. null for no errors
'''

'''
response: {
	'version': '1.2.3'
}
'''
@app.route('/')
def index():
	return build_response(None, message='Minecraft server wrapper.', version=str(VERSION))

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
	if minecraft.pid() != 0:
		return build_response(ERR_SERVER_RUNNING)
	data = flask.request.get_json(force=True)
	url = data.get('url', SOURCE_URL)
	min_version = data.get('min_version')
	if min_version is None or VERSION < distutils.version.StrictVersion(min_version):
		download_file(url, __file__)
	print('here')
	app.logger.info('herestderr')
	return build_response(None)

'''
request: path=
'''
@app.route('/file')
@requires_auth
def get_file():
	data = flask.request.args.get('path')
	if data is None:
		return build_response(ERR_INVALID_REQUEST, 400)
	normed_path = os.path.normpath(data)
	if normed_path.startswith('/'):
		normed_path = normed_path[1:]
	if normed_path.startswith('..'):
		return build_response(ERR_INVALID_REQUEST, 400)
	path = os.path.realpath(os.path.join(os.getcwd(), normed_path))
	if os.path.isfile(path):
		return flask.send_file(path, mimetype='application/octet-stream', as_attachment=True, attachment_filename='gamocosm-' + time.strftime('%Y_%b_%d').lower() + '-' + os.path.basename(path))
	if os.path.isdir(path):
		tmp = tempfile.mkdtemp()
		try:
			zip_path = os.path.join(tmp, 'a.zip')
			z = zip_directory(path, zip_path)
			return flask.send_file(zip_path, mimetype='application/zip', as_attachment=True, attachment_filename='gamocosm-' + time.strftime('%Y_%b_%d').lower() + '-' + os.path.basename(path) + '.zip')
		finally:
			shutil.rmtree(tmp)
	return build_response(ERR_OTHER, 404)

'''
request: dir=
response: {
	'files': ['files'],
	'folders': ['folders']
}
'''
@app.route('/ls')
@requires_auth
def get_ls():
	data = flask.request.args.get('dir')
	if data is None:
		return build_response(ERR_INVALID_REQUEST, 400)
	normed_path = os.path.normpath(data)
	if normed_path.startswith('/'):
		normed_path = normed_path[1:]
	if normed_path.startswith('..'):
		return build_response(ERR_INVALID_REQUEST, 400)
	path = os.path.realpath(os.path.join(os.getcwd(), normed_path))
	if os.path.isfile(path):
		return build_response(ERR_INVALID_REQUEST, 400)
	try:
		dirs = []
		files = []
		for r, d, f in os.walk(path):
			dirs.extend(d)
			files.extend(f)
			break
		return build_response(None, files=files, folders=dirs)
	except OSError:
		return build_response(ERR_INVALID_REQUEST, 400)

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
	data = flask.request.get_json(force=True)
	ram = data.get('ram')
	if ram is None:
		return build_response(ERR_INVALID_REQUEST, 400)
	return build_response(minecraft.start(ram), minecraft.pid())

'''
response: {
	retcode: 1234
}
'''
@app.route('/stop')
@requires_auth
def minecraft_stop():
	return build_response(minecraft.stop(), minecraft.pid())

'''
response: {
	pid: 1234
}
'''
@app.route('/pid')
@requires_auth
def minecraft_pid():
	return build_response(None, minecraft.pid())

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
	data = flask.request.get_json(force=True)
	command = data.get('command')
	if command is None:
		return build_response(ERR_INVALID_REQUEST, 400)
	return build_response(minecraft.exec(command))

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
			return build_response(ERR_INVALID_REQUEST, 400)
		properties = minecraft.properties(data['properties'])
	if properties is None:
		properties = minecraft.properties()
	return build_response(None, properties=properties)

# Utility

def zip_directory(path, zip_name):
	z = zipfile.ZipFile(zip_name, 'w')
	for root, dirs, files in os.walk(path):
		for f in files:
			f_path = os.path.join(root, f)
			z.write(f_path, os.path.relpath(f_path, path))
	return z

def download_file(url, path):
	path = os.path.realpath(path)
	with open(path + '.tmp', 'wb') as tmp:
		with urllib.request.urlopen(url) as response:
			shutil.copyfileobj(response, tmp)
		os.rename(tmp.name, path)
	return path

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
