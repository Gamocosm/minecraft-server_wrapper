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
from minecraft import Minecraft
from daemon import Daemon

VERSION = distutils.version.StrictVersion('0.4.1')

ERR_INVALID_REQUEST = 'invalid_request'
ERR_NO_AUTH = 'no_auth'
ERR_OTHER = 'error_other'
ERR_BADNESS = 'badness'

app = flask.Flask(__name__)
minecraft = None
auth_credentials = None

# Helpers

def build_response(status, http_status_code=200, **kwargs):
	res = flask.jsonify(status=status, **kwargs)
	res.status_code = http_status_code
	return res

def auth_file_load(auth_file):
	global auth_credentials
	try:
		with open(auth_file) as f:
			u = None
			p = None
			i = 0
			for line in f:
				if i == 0:
					u = line.strip()
					if len(u) == 0:
						return 'blank username'
				elif i == 1:
					p = line.strip()
					if len(p) == 0:
						return 'blank password'
				else:
					break
				i += 1
			if i == 2:
				auth_credentials = (u, p)
				return None
			return 'bad format'
	except OSError:
		return 'unable to open'
	return 'badness'

def response_check_auth(u, p):
	if auth_credentials is None:
		return True
	return u == auth_credentials[0] and p == auth_credentials[1]

def response_authenticate():
	res = build_response(ERR_NO_AUTH, 401)
	res.headers.add('WWW-Authenticate', 'Basic realm="Login Required"')
	return res

def requires_auth(f):
	@functools.wraps(f)
	def decorated(*args, **kwargs):
		auth = flask.request.authorization
		if not auth or not response_check_auth(auth.username, auth.password):
			return response_authenticate()
		return f(*args, **kwargs)
	return decorated

@app.after_request
def after_request(res):
	sys.stdout.flush()
	sys.stderr.flush()
	return res

@app.errorhandler(Exception)
def errorhandler(error):
	sys.stdout.flush()
	sys.stderr.flush()
	app.logger.exception('Badness')
	return build_response(ERR_BADNESS, 500)

# Routes

'''
All responses include a status: string field. null for no errors
'''

'''
response: {
	'version': '1.2.3',
	'pid': 123
}
'''
@app.route('/')
@requires_auth
def index():
	return build_response(None, message='Minecraft server wrapper.', version=str(VERSION), pid=minecraft.pid())

'''
Legacy
'''
@app.route('/pid')
@requires_auth
def minecraft_pid():
	return build_response(None, pid=minecraft.pid())

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
			zip_path = os.path.join(tmp, 'a')
			zip_directory(path, zip_path)
			return flask.send_file(zip_path + '.zip', mimetype='application/zip', as_attachment=True, attachment_filename='gamocosm-' + time.strftime('%Y_%b_%d').lower() + '-' + os.path.basename(path) + '.zip')
		finally:
			shutil.rmtree(tmp)
	return build_response(ERR_OTHER, 404)

'''
Legacy
'''
@app.route('/download_world')
@requires_auth
def minecraft_download_world():
	if minecraft.pid() != 0:
		return build_response(mc.ERR_MINECRAFT_RUNNING)
	world_name = minecraft.properties().get('level-name')
	if world_name is None:
		return build_response(ERR_OTHER, 404)
	tmp = tempfile.mkdtemp()
	try:
		zip_path = os.path.join(tmp, 'a')
		zip_directory(world_name, zip_path)
		return flask.send_file(zip_path + '.zip', mimetype='application/zip', as_attachment=True, attachment_filename='minecraft-world-' + time.strftime('%Y_%b_%d').lower() + '.zip')
	finally:
		shutil.rmtree(tmp)
	return build_response(ERR_OTHER, 400)

'''
Legacy
'''
@app.route('/backup', methods=['POST'])
@requires_auth
def minecraft_backup():
	if os.path.isfile('backups'):
		os.remove('backups')
	if not os.path.exists('backups'):
		os.makedirs('backups')
	zip_name = 'backups/minecraft-world_backup-' + str(datetime.datetime.today()).replace('-', '_').replace(' ', '-').replace(':', '_').replace('.', '-')
	world_name = minecraft.properties().get('level-name')
	if world_name is None:
		return build_response(ERR_OTHER, 400)
	zip_directory(world_name, zip_name)
	return build_response(None)

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
	if not os.path.isdir(path):
		return build_response(ERR_INVALID_REQUEST, 400)
	if not os.path.exists(path):
		return build_response(ERR_OTHER, 404)
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
	return build_response(minecraft.start(ram), pid=minecraft.pid())

'''
response: {
	retcode: 1234
}
'''
@app.route('/stop')
@requires_auth
def minecraft_stop():
	return build_response(minecraft.stop(), pid=minecraft.pid())

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
	properties = None
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
	shutil.make_archive(zip_name, 'zip', '.', path)
	'''
	z = zipfile.ZipFile(zip_name, 'w')
	for root, dirs, files in os.walk(path):
		for f in files:
			f_path = os.path.join(root, f)
			z.write(f_path, os.path.relpath(f_path, path))
	return z
	'''

def download_file(url, path):
	path = os.path.realpath(path)
	with open(path + '.tmp', 'wb') as tmp:
		with urllib.request.urlopen(url) as response:
			shutil.copyfileobj(response, tmp)
		os.rename(tmp.name, path)
	return path

# Handlers

def shutdown():
	minecraft.stop()
	sys.stdout.flush()
	sys.stderr.flush()

# Main

def run():
	global minecraft
	minecraft = Minecraft('minecraft.pid', app.logger)
	atexit.register(shutdown)
	# Note: Werkzeug server's reloader catches SIGTERM
	signal.signal(signal.SIGINT, lambda signum, frame: sys.exit(0))
	signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
	handler = logging.StreamHandler()
	app.logger.addHandler(handler)
	app.run(host='0.0.0.0')

def main():
	pidfile = None
	d = None
	for i in range(1, len(sys.argv)):
		arg = sys.argv[i]
		if arg.startswith('--auth='):
			auth_error = auth_file_load(arg[len('--auth='):])
			if not auth_error is None:
				print('Bad auth file: ' + auth_error)
				sys.exit(1)
	if len(sys.argv) > 2:
		if sys.argv[1] == 'daemonize':
			pidfile = sys.argv[2]
			# Reloader will spawn new process with args
			del(sys.argv[2])
			del(sys.argv[1])
			d = Daemon(pidfile)
			d.start(run)
		elif sys.argv[1] == 'stop':
			pidfile = sys.argv[2]
			d = Daemon(pidfile)
			d.stop(24)
	if d is None:
		run()

if __name__ == '__main__':
	main()
