project('hack-sound-server', version: '0.0.0')

session_bus_services_dir = get_option('session-bus-services-dir')

if session_bus_services_dir == ''
   session_bus_services_dir = join_paths(get_option('datadir'), 'dbus-1', 'services')
endif

install_data(
    'com.endlessm.HackSoundServer.service',
    install_dir: session_bus_services_dir
)

install_data(
    'hack-sound-server',
    install_dir: get_option('bindir')
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
