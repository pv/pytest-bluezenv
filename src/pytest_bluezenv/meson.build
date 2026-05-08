python_sources = files(
  '__init__.py',
  '__main__.py',
  'agent.py',
  'btmon.py',
  'build_kernel.py',
  'env.py',
  'host_plugins.py',
  'plugin.py',
  'rpc.py',
  'runner.py',
  'utils.py'
)

py.install_sources(
  python_sources,
  subdir: 'pytest_bluezenv'
)

subdir('tests')
