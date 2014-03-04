import sys
import signal
import subprocess

mc_process = None

def signal_handler(signum=None, frame=None):
	signals = { signal.SIGTERM: "SIGTERM", signal.SIGINT: "SIGINT" }
	if signum in signals:
		print('Received signal {0}, stopping...'.format(signals[signum]))
		mc_shutdown()
	else:
		print('Unknown signal {0}, ignoring.'.format(signum))

def subprocess_preexec_handler():
	signal.signal(signal.SIGINT, signal.SIG_IGN)

def mc_shutdown():
	mc_process.stdin.write('stop\n')

for sig in [signal.SIGTERM, signal.SIGINT]:
	signal.signal(sig, signal_handler)

def main():
	print('Running {0}.'.format(sys.argv[1:]))
	global mc_process
	mc_process = subprocess.Popen(sys.argv[1:], stdout=None, stdin=subprocess.PIPE, stderr=None, universal_newlines=True, preexec_fn=subprocess_preexec_handler, shell=False)
	print('Subprocess running, pid is {0}.'.format(mc_process.pid))
	mc_process.wait()
	print('Subprocess returned, was {0}.'.format(mc_process.poll()))

if __name__ == '__main__':
	main()