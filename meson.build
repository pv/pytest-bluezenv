project(
  'pytest-bluezenv',
  'c',
  version: '0.1.1',
  meson_version: '>=0.64.0',
)

cc = meson.get_compiler('c')
fs = import('fs')

py_mod = import('python')
py = py_mod.find_installation(pure: false)

bluez_proj = subproject('bluez', required: true)
bluez_btvirt = bluez_proj.get_variable('btvirt')
bluez_test_runner = bluez_proj.get_variable('test_runner')

btvirt = custom_target(
  'btvirt',
  command: ['cp', '@INPUT@', '@OUTPUT@'],
  input: bluez_btvirt,
  output: 'btvirt',
  install_dir: py.get_install_dir(subdir: 'pytest_bluezenv/bin'),
  install: true
)

test_runner = custom_target(
  'test-runner',
  command: ['cp', '@INPUT@', '@OUTPUT@'],
  input: bluez_test_runner,
  output: 'test-runner',
  install_dir: py.get_install_dir(subdir: 'pytest_bluezenv/bin'),
  install: true
)

subdir('src')
