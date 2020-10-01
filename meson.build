project('hack-sound-server', version: '0.0.0')

python = find_program('python3')
pkgdatadir = join_paths(get_option('datadir'), meson.project_name())

session_bus_services_dir = get_option('session-bus-services-dir')

if session_bus_services_dir == ''
   session_bus_services_dir = join_paths(get_option('datadir'), 'dbus-1', 'services')
endif

conf = configuration_data()
conf.set('bindir', join_paths(get_option('prefix'), get_option('bindir')))

configure_file(
    input: join_paths('service', 'com.hack_computer.HackSoundServer.service.in'),
    output: 'com.hack_computer.HackSoundServer.service',
    install: true,
    install_dir: session_bus_services_dir,
    configuration: conf
)

conf = configuration_data()
conf.set('DATADIR', join_paths(get_option('prefix'), get_option('datadir')))
conf.set('LIBDIR', join_paths(get_option('prefix'), get_option('libdir')))
conf.set('PACKAGE', meson.project_name())

pkglibdir = join_paths(get_option('libdir'), meson.project_name())
install_dir = join_paths(pkglibdir, 'python', 'hack_sound_server')

configure_py = configure_file(
    input: join_paths('hack_sound_server', 'configure.py.in'),
    output: 'configure.py',
    configuration: conf
)

main_py = configure_file(
    input: join_paths('hack_sound_server', 'main.py.in'),
    output: 'main.py',
    configuration: conf
)

run_command('cp', configure_py, join_paths(meson.current_source_dir(), 'hack_sound_server'))
run_command('cp', main_py, join_paths(meson.current_source_dir(), 'hack_sound_server'))
run_command(python, 'setup.py', 'install', '--prefix=' + get_option('prefix'))

install_subdir(
    'data',
    install_dir: pkgdatadir,
    strip_directory: true
)

data_dir = join_paths(get_option('prefix'), get_option('datadir'))

install_data(
    'com.hack_computer.HackSoundServer.appdata.xml',
    install_dir: join_paths(data_dir, 'appdata')
)

message('\n'.join([
    '@0@ @1@'.format(meson.project_name(), meson.project_version()),
    '--------------------------------------',
    'Directories:',
    '    prefix: @0@'.format(get_option('prefix')),
    '    bindir: @0@'.format(get_option('bindir')),
    '    datadir: @0@'.format(data_dir),
    '    session_bus_services_dir: @0@'.format(session_bus_services_dir),
    ''
]))
