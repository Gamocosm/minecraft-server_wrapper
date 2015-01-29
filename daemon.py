'''
Daemon implementation
- http://legacy.python.org/dev/peps/pep-3143/
- http://stackoverflow.com/questions/473620/how-do-you-create-a-daemon-in-python
- http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/
- http://code.activestate.com/recipes/278731/
- https://pypi.python.org/pypi/python-daemon/
- http://stackoverflow.com/questions/4790876/what-is-the-de-facto-library-for-creating-python-daemons
- http://www.jstorimer.com/blogs/workingwithcode/7766093-daemon-processes-in-ruby
- https://github.com/mperham/sidekiq/blob/master/bin/sidekiqctl
- https://github.com/mperham/sidekiq/blob/master/lib/sidekiq/cli.rb

Day 2: I have spent the past few hours reading up on linux processes, process groups, sessions, and zombie processes.
I believe I have a solid understand of the tiny details now.
Unfortunately, I don't have a solid understanding of the calculus for my midterm in ~18 hours

'''

import os
import sys
import time
import atexit
import signal

def read_pid(pidfile):
	pid = None
	try:
		with open(pidfile, encoding='utf8') as f:
			try:
				pid = int(f.readline().strip())
				try:
					os.kill(pid, 0)
				except ProcessLookupError:
					delete_pid(pidfile)
					pid = None
			except ValueError:
				delete_pid(pidfile)
	except FileNotFoundError:
		pass
	return pid

def open_pid(pidfile, success):
	try:
		with open(pidfile, 'x', encoding='utf8') as f:
			success(f)
	except FileExistsError:
		return False
	return True

def create_pid(pidfile, pid):
	return open_pid(pidfile, lambda f: write_pid(f, pid))

def write_pid(f, pid):
	f.write('{:d}\n'.format(pid))

def delete_pid(pidfile):
	try:
		os.remove(pidfile)
	except FileNotFoundError:
		pass

# From python subprocess source
def close_fds():
	max_fds = os.sysconf('SC_OPEN_MAX')
	os.closerange(3, max_fds)

# stdin, stdout, stderr, and working directory expected to be set (e.g. systemd)
class Daemon:
	def __init__(self, pidfile):
		self.pidfile = pidfile

	def daemonize(self):
		pid = os.fork()
		if pid > 0:
			os._exit(0)
		os.setsid()
		pid = os.fork()
		if pid > 0:
			os._exit(0)
		close_fds()
		atexit.register(lambda: delete_pid(self.pidfile))
		return create_pid(self.pidfile, os.getpid())

	def start(self, do_it):
		pid = read_pid(self.pidfile)
		if not pid is None:
			sys.stderr.write('Pidfile {:s} with process {:d} already exists\n'.format(self.pidfile, pid))
			return
		if self.daemonize():
			self.run(do_it)
		else:
			sys.stderr.write('Pidfile {:s} with process {:d} already exists (tried creating pidfile)\n'.format(self.pidfile, pid))
			return

	def stop(self, timeout):
		pid = read_pid(self.pidfile)
		if pid is None:
			return
		try:
			os.kill(pid, signal.SIGTERM)
		except ProcessLookupError:
			return
		i = 0
		while i < timeout:
			try:
				time.sleep(1)
				os.kill(pid, 0)
				i += 1
			except ProcessLookupError:
				return
		sys.stderr.write('Process {:d} did not stop after {:d} seconds, killing\n'.format(pid, timeout))
		os.kill(pid, signal.SIGKILL)

	def run(self, nike):
		# Just do it (for Radu)
		nike()
