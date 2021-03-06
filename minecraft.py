import os
import subprocess
import shutil
import tempfile
import daemon
import signal

ERR_NO_MINECRAFT = 'no_minecraft'
ERR_MINECRAFT_RUNNING = 'minecraft_running'
ERR_MINECRAFT_NOT_RUNNING = 'minecraft_not_running'
ERR_MINECRAFT_ORPHANED = 'minecraft_orphaned'
ERR_PIDFILE_LOCKED = 'pidfile_locked'
ERR_OTHER = 'error_other'

class Minecraft:
	def __init__(self, pidfile, logger):
		self.process = None
		self.stdout = None
		self.stderr = None
		self.pidfile = pidfile
		self.logger = logger

	def pid(self):
		if self.process is None:
			return 0
		if self.process.poll() is None:
			return self.process.pid
		return 0

	def start(self, ram):
		if self.pid() != 0:
			return None
		assert(self.process is None)
		assert(self.stdout is None)
		assert(self.stderr is None)
		if self.minecraft_running_elsewhere():
			return ERR_MINECRAFT_ORPHANED
		cmd = ['java', '-Xmx' + ram, '-jar', 'minecraft_server-run.jar', 'nogui']
		if os.path.isfile('minecraft_server-run.sh'):
			cmd = ['bash', 'minecraft_server-run.sh']
		elif not os.path.isfile('minecraft_server-run.jar'):
			return ERR_NO_MINECRAFT
		try:
			self.stdout = open('minecraft-stdout.log', 'ab')
			self.stderr = open('minecraft-stderr.log', 'ab')
		except OSError:
			self.logger.exception('[mcsw] Error opening Minecraft stdout and stderr files.')
			return ERR_OTHER
		def create_process(f):
			self.process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=self.stdout, stderr=self.stderr)
			daemon.write_pid(f, self.process.pid)
		if not daemon.open_pid(self.pidfile, create_process):
			return ERR_PIDFILE_LOCKED
		return None

	def stop(self):#
		self.logger.info('[mcsw] Stopping minecraft...')
		mc_pid = self.pid()
		if mc_pid == 0:
			self.logger.info('[mcsw] Not running.')
			return None
		try:
			self.process.stdin.write('stop\n'.encode('ascii'))
			self.process.stdin.flush()
			self.process.wait(16)
			self.logger.info('[mcsw] Minecraft exited gracefully.')
		except subprocess.TimeoutExpired:
			self.process.terminate()
			#pgid = os.getpgid(mc_pid)
			#os.killpg(pgid, signal.SIGTERM)
			try:
				self.process.wait(4)
				self.logger.info('[mcsw] Minecraft exited due to SIGTERM.')
			except subprocess.TimeoutExpired:
				self.process.kill()
				#os.killpg(pgid, signal.SIGKILL)
				self.process.wait()
				self.logger.info('[mcsw] Minecraft killed.')
		self.process = None
		self.cleanup()
		return None

	def exec(self, command):
		if self.pid() == 0:
			return ERR_MINECRAFT_NOT_RUNNING
		self.process.stdin.write((command + '\n').encode('utf8'))
		self.process.stdin.flush()
		return None

	def properties(self, props=None):
		if props is None:
			props = {}
			try:
				with open('server.properties', encoding='utf8') as f:
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
			# we do this loop again to keep the same order
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
			except OSError:
				pass
			for k in props:
				tmp.write(bytes(k + '=' + props[k].strip() + '\n', 'utf8'))
			tmp.close()
			os.remove('server.properties')
			shutil.move(tmp.name, 'server.properties')
		finally:
			try:
				os.remove(tmp.name)
			except OSError:
				pass
		return self.properties()

	def minecraft_running_elsewhere(self):
		return (daemon.read_pid(self.pidfile) is not None)

	def cleanup(self):
		daemon.delete_pid(self.pidfile)
		try:
			self.stdout.close()
		except OSError:
			self.logger.exception('[mcsw] Error closing Minecraft stdout file.')
		try:
			self.stderr.close()
		except OSError:
			self.logger.exception('[mcsw] Error closing Minecraft stderr file.')
		self.stdout = None
		self.stderr = None
