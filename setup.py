from setuptools import setup, find_packages


setup(
    name='hack-sound-server',
    version='0.1',
    license='GPLv2',
    author='danigm',
    author_email='danigm@endlessos.org',
    url='https://github.com/endlessm/hack-sound-server/',
    long_description="README.txt",
    packages=find_packages(),
    entry_points={
        'console_scripts': ['hack-sound-server=hack_sound_server.main:main'],
    },
    package_data={},
    data_files=[],
    description='This is a dbus-based server that plays sounds '
                'given a metadata file and a bunch of sound files.',
)
