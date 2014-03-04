import flask
import sys
import signal
import subprocess

app = flask.Flask(__name__)
mc_process = None

# Handlers

def signal_handler(signum=None, frame=None):
	signals = { signal.SIGTERM: "SIGTERM", signal.SIGINT: "SIGINT" }
	if signum in signals:
		print('Received signal {0}, stopping...'.format(signals[signum]))
		print('Server stopped with: {0}.'.format(mc_shutdown()))
	else:
		print('Unknown signal {0}, ignoring.'.format(signum))

def subprocess_preexec_handler():
	signal.signal(signal.SIGINT, signal.SIG_IGN)

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
	return False

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
		# signal.signal(sig, signal_handler)
		pass

	app.run()

if __name__ == '__main__':
	main()