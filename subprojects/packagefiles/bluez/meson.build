project(
  'bluez',
  'c',
  version: '5.86',
  meson_version: '>= 1.3.0'
)

add_project_arguments('-DHAVE_CONFIG_H', language: 'c')
config_h = configuration_data()

cc = meson.get_compiler('c')

required_funcs = [
  'explicit_bzero',
  'getrandom',
  'rawmemchr',
  'signalfd',
]

foreach func: required_funcs
  cc.has_function(func, required: true)
endforeach

required_lib_funcs = [
  [ 'clock_gettime', 'rt' ],
  [ 'pthread_create', 'pthread' ],
  [ 'dlopen', 'dl' ]
]

foreach func: required_lib_funcs
  dep = cc.find_library(func[1], required: true)
  cc.has_function(func[0], dependencies: dep, required: true)
endforeach

add_project_arguments('-I' + meson.project_build_root(), language: 'c')
add_project_arguments('-I' + meson.project_source_root(), language: 'c')

glib_dep = dependency('glib-2.0', version: '>= 2.36')

config_h.set_quoted('VERSION', meson.project_version())

configure_file(
  output: 'config.h',
  configuration: config_h
)

btvirt = executable(
  'btvirt',
  sources: [
    'emulator/main.c',
    'emulator/serial.c',
    'emulator/server.c',
    'emulator/vhci.c',
    'emulator/btdev.c',
    'emulator/bthost.c',
    'emulator/smp.c',
    'emulator/phy.c',
    'emulator/le.c',
    'src/shared/ad.c',
    'src/shared/crypto.c',
    'src/shared/ecc.c',
    'src/shared/queue.c',
    'src/shared/log.c',
    'src/shared/util.c',
    'src/shared/io-mainloop.c',
    'src/shared/timeout-mainloop.c',
    'src/shared/mainloop.c',
    'src/shared/mainloop-notify.c',
    'lib/bluetooth/bluetooth.c',
    'lib/bluetooth/uuid.c',
  ],
  dependencies: glib_dep,
  include_directories: ['lib', '.'],
)

test_runner = executable(
  'test-runner',
  sources: 'tools/test-runner.c',
  include_directories: ['lib', '.'],
)

tester_config = files('doc/tester.config')
