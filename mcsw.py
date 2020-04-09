#!/usr/bin/env python3

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
import datetime
import atexit
import functools
import logging
import urllib.request
import distutils.version
import time
from minecraft import Minecraft
import daemon

VERSION = distutils.version.StrictVersion('0.5.0')

ERR_INVALID_REQUEST = 'invalid_request'
ERR_NO_AUTH = 'no_auth'
ERR_OTHER = 'error_other'
ERR_BADNESS = 'badness'

minecraft = None

def create_app():
	global minecraft
	app = flask.Flask(__name__)
	app.logger.setLevel(logging.DEBUG)
	app.logger.info('[mcsw] Initializing...')
	auth_credentials = auth_file_load(app)
	minecraft = Minecraft('minecraft.pid', app.logger)

	atexit.register(lambda: shutdown(app))

	# Helpers

	def build_response(status, http_status_code=200, **kwargs):
		res = flask.jsonify(status=status, **kwargs)
		res.status_code = http_status_code
		return res

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
		app.logger.exception('[mcsw] Badness.')
		return build_response(ERR_BADNESS, 500)

	# Routes

	'''
	All responses include a status: string field. null for no errors
	'''

	'''
	response: {
		'version': '1.2.3',
	}
	'''
	@app.route('/')
	@requires_auth
	def index():
		return build_response(None, message='Minecraft server wrapper.', version=str(VERSION), pid=minecraft.pid())

	'''
	response: {
		'pid': 1234,
	}
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
		pid: 1234
	}
	'''
	@app.route('/stop', methods=['POST'])
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

	daemon.systemd_ready()
	app.logger.info('[mcsw] Ready.')
	return app

# Handlers

def shutdown(app):
	app.logger.info('[mcsw] Shutting down...')
	minecraft.stop()
	sys.stdout.flush()
	sys.stderr.flush()
	app.logger.info('[mcsw] Goodbye.')

# Utility

def zip_directory(path, zip_name):
	shutil.make_archive(zip_name, 'zip', '.', path)

def auth_file_load(app):
	auth_file = os.environ.get('MCSW_AUTH')
	if auth_file is None:
		app.logger.info('[mcsw] No auth file (unsecured, only for development/debug).')
		return None
	try:
		with open(auth_file) as f:
			u = None
			p = None
			lines = []
			for s in f:
				lines.append(s.strip())
			if len(lines) != 2:
				app.logger.error('[mcsw] Bad auth file format.')
				sys.exit(1)
			u = lines[0]
			p = lines[1]
			if len(u) == 0:
				app.logger.error('[mcsw] Blank username in auth file.')
				sys.exit(1)
			if len(p) == 0:
				app.logger.error('[mcsw] Blank password in auth file.')
				sys.exit(1)
			app.logger.info('[mcsw] Loaded auth file.')
			return (u, p)
	except OSError:
		app.logger.error('[mcsw] Unable to open auth file.')
		sys.exit(1)

