project('hack-sound-server', version: '0.0.0')

python = find_program('python3')
pkgdatadir = join_paths(get_option('datadir'), meson.project_name())

session_bus_services_dir = get_option('session-bus-services-dir')

if session_bus_services_dir == ''
   session_bus_services_dir = join_paths(get_option('datadir'), 'dbus-1', 'services')
endif

install_data(
    join_paths('service', 'com.endlessm.HackSoundServer.service'),
    install_dir: session_bus_services_dir
)

conf = configuration_data()
conf.set('DATADIR', join_paths(get_option('prefix'), get_option('datadir')))
conf.set('LIBDIR', join_paths(get_option('prefix'), get_option('libdir')))
conf.set('PACKAGE', meson.project_name())

pkglibdir = join_paths(get_option('libdir'), meson.project_name())
install_dir = join_paths(pkglibdir, 'python', 'hack_sound_server')

run_command(
    python, '-m', 'compileall',
    join_paths(meson.current_source_dir(), 'hack_sound_server')
)

install_subdir(
    'src',
    exclude_files: 'configure.py.in',
    install_dir: install_dir,
    strip_directory: true
)

configure_file(
    input: join_paths('src', 'configure.py.in'),
    output: 'configure.py',
    install: true,
    install_dir: install_dir,
    configuration: conf
)

startup_script = configure_file(
    input: join_paths('bin', 'hack-sound-server.in'),
    output: 'hack-sound-server',
    configuration: conf
)

install_data(
    startup_script,
    install_dir: get_option('bindir'),
    install_mode: 'rwxr-xr-x'
)

install_subdir(
    'data',
    install_dir: pkgdatadir,
    strip_directory: true
)

message('\n'.join([
    '@0@ @1@'.format(meson.project_name(), meson.project_version()),
    '--------------------------------------',
    'Directories:',
    '    prefix: @0@'.format(get_option('prefix')),
    '    bindir: @0@'.format(get_option('bindir')),
    '    session_bus_services_dir: @0@'.format(session_bus_services_dir),
    ''
]))
