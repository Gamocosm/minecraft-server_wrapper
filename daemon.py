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

class Daemon:
	def __init__(self, pidfile, timeout, do_it):
		self.pidfile = pidfile
		self.timeout = timeout
		self.nike = do_it

	def daemonize(self):
		pid = os.fork()
		if pid > 0:
			os._exit(0)
		os.setsid()
		pid = os.fork()
		if pid > 0:
			os._exit(0)
		self.close_fds()
		atexit.register(self.delete_pid)
		return self.create_pid(os.getpid())

	def start(self):
		pid = self.read_pid()
		if not pid is None:
			sys.stderr.write('Pid {:s} with process {:d} already exists\n'.format(self.pidfile, pid))
			return False
		if self.daemonize():
			return self.run()
		else:
			sys.stderr.write('Pid {:s} with process {:d} already exists (tried creating pid)\n'.format(self.pidfile, pid))
			return False

	def stop(self):
		pid = self.read_pid()
		if pid is None:
			return
		i = 0
		while i < self.timeout:
			try:
				os.kill(pid, signal.SIGTERM)
				time.sleep(1)
			except ProcessLookupError:
				break
		if i == self.timeout:
			sys.stderr.write('Process {:d} did not stop after {:d} SIGTERMs, killing\n'.format(pid, self.timeout))
			os.kill(pid, signal.SIGKILL)

	def run(self):
		# Just (for Radu)
		self.nike()

	def read_pid(self):
		pid = None
		try:
			with open(self.pidfile, encoding='utf8') as f:
				pid = int(f.readline().strip())
		except FileNotFoundError:
			pass
		return pid

	def create_pid(self, pid):
		try:
			with open(self.pidfile, 'x', encoding='utf8') as f:
				f.write('{:d}\n'.format(pid))
		except FileExistsError:
			return False
		return True

	def delete_pid(self):
		try:
			os.remove(self.pidfile)
		except FileNotFoundError:
			pass

	# From python subprocess source
	def close_fds(self):
		max_fds = os.sysconf('SC_OPEN_MAX')
		os.closerange(3, max_fds)
