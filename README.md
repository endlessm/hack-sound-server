# hack-sound-service
This is a dbus-based server that plays sounds given a metadata file and a bunch of sound files.

# Getting started
To test this project, please follow these steps:

## 1. Clone the repository
Open a terminal. In Endless OS, search "terminal" in the desktop, to find and open a terminal. Then, type the following command:
```
git clone https://github.com/endlessm/hack-sound-server/
cd hack-sound-server/
```
## 2. Build and install the server
To build and install you can use the build-flatpak.sh script in the root directory. It will build the current branch and install the flatpak directly.
```
./build-flatpak.sh
```
If a password is requested, input it.

## 3. Play a sound!
Just type this following command in the terminal to play a sound:
```
gdbus call --session --dest com.hack_computer.HackSoundServer --object-path /com/hack_computer/HackSoundServer --method com.hack_computer.HackSoundServer.PlaySound framework/piano/1
```

Sounds are registered internally by a tag known as the "sound event id". The server includes these following sound event ids available:
```
framework/drumkit/0
framework/drumkit/1
framework/drumkit/2
framework/drumkit/3
framework/drumkit/4
framework/drumkit/5
framework/piano/0
framework/piano/1
framework/piano/2
framework/piano/3
framework/piano/4
framework/piano/5
framework/scifi/0
framework/scifi/1
framework/scifi/2
framework/scifi/3
framework/scifi/4
framework/scifi/5
```
The previously listed sound event ids are specified in a metadata file located at `data/sounds/metadata.json`. More descriptions about the metadata file will be explained in the next section.
> Do not think that there is a pattern for sound event ids. For example, `framework/scifi/5` is just a a string, it could have been called `scifi-5WhatEver`, too.

# Metadata file
Metadata files describe the behavior of sounds. The **hack-sound-server** reads from the metadata file to know what sounds are available and to know how to play them. The default metadata that the **hack-sound-server** uses is located at `data/sounds/metadata.json`.
> Do not edit this file if you are just testing the sounds. Instead override it (more detauls in the next subsection).

An example of metadata file is the following:
```
{
    "framework/drumkit/0": {
        "sound-file": "drumkit/176980__snapper4298__kick-2-with-start.wav",
        "license": "CC-BY",
        "source": "freesound.org"
    },
    "framework/piano/0": {
        "sound-file": "piano/39177__jobro__piano-ff-030.wav",
        "license": "CC-BY",
        "source": "freesound.org"
    }
```
This metadata file specifies two sound event ids: `framework/drumkit/0` and `framework/piano/0`. Then each entry, tells what is the location of the audio file (`sound-file`), the license of the sound (`license`) and the source where it was obtained from (`source`).

## A full example
```
{
    "example/sound/1": {
        "sound-file": "sound0.wav",
        "sound-files": [
            "sound1.wav",
            "sound2.wav",
            "sound3.wav"
        ],
        "loop": true,
        "fade-in": 3000,
        "fade-out": 5000,
        "volume": 0.5,
        "pitch": 2.0,
        "delay": 10000,
        "overlap-behavior": "restart"
    }
}
```
This example shows all the options that the metadata file accepts.

- **`sound-file`**: Indicates the path to the sound file to be played.
- **`sound-files`**: It's an array of paths, and indicates that one of these sounds should be picked up randomly to be played. If like in this example, `sound-file` and `sound-files` are set, then all the specified paths will be considered. In other words, for this example, one sound among "sound0.wav", "sound1.wav", "sound2.wav" and "sound3.wav" would be played.
- **`loop`**: If set to `true` the sound will be played again when it finishes. *Defaults to `false`*.
- **`fade-in`**: Indicates the time duration in which the volume of the sound should fade in from the start. The used unit is milliseconds. *Defaults to 1000 only if `loop` is set to `true`*.
- **`fade-out`**: Indicates the time duration in which the volume of the sound should fade out after the sound is stopped. The used unit is milliseconds. *Defaults to 1000 only if `loop` is set to `true`*.
- **`volume`**: Indicates the volume level the sound you play at. *Defaults to 1.0 (the "normal" volume)*.
- **`pitch`**: Sets the sound pitch while keeping the original tempo (speed). *Defaults to 1.0 (the "normal" pitch)*.
- **`rate`**: Sets the tempo and pitch. *Defaults to 1.0 (the "normal" rate)*.
- **`delay`**: The duration in milliseconds that should be delayed before the sound starts. *Defaults to 0*.
- **`overlap-behavior`**: Indicates the behavior of the sound when the same sound is requested to be played while the other is also playing. The available options are: `"overlap"`, `"ignore"` and `"restart"`. If `"overlap"` is set, then if the same sound is played twice or more times simultaneously, all these sounds will overlap between them. If `"ignore"` is set, if the target sound is already playing and an application requests to play this sound, this request will be ignored: this means that **only one** instance of the sound will be played. If `"restart"` is set, then if the target sound is already playing and an application requests to play this sound, the sound will be restarted: this (also) means that **only one** instance of the sound will be playing. *Defaults to `"overlap"`*.
- **`type`**: There are two types of sounds: `"bg"` and `"sfx"`. Sounds of `bg` type follow a special logic: if another `bg` sound is currently playing back and a new `bg` sound is requested to play back, then the last `bg` sound will pause and the new sound will play back. Sounds of type `sfx` are just all the rest. *Defaults to `"sfx"`*

## Overriding the metadata file
To override metadata files or add more sounds, you can create your own metadata file. **All the sounds specified there will have the highest priority**.

Create a file in the following path `$HOME/.var/app/com.hack_computer.HackSoundServer/data/metadata.json`.
> `$HOME` represents your home directory.
> `.var` is a hidden directory. You can show hidden files with the keys `ctrl` + `h` in the Endless OS file browser.

Once you have created that file, you can add for example the following content:
```
{
    "water": {
        "sound-file": "water.wav"
    },
    "framework/piano/0": {
        "sound-file": "beep.wav",
    }
}
```
> Beware of closing curly braces properly.

Then you should create the folder `sounds` in `$HOME/.var/app/com.hack_computer.HackSoundServer/data/` and put your sounds files there. In this case, you would have to put the sound file `water.wav` and `beep.wav`.

### Playing sounds
You can test the `water` sound event id when you input this command in a terminal:
```
gdbus call --session --dest com.hack_computer.HackSoundServer --object-path /com/hack_computer/HackSoundServer --method com.hack_computer.HackSoundServer.PlaySound water
```

If you run the following command on a terminal, this will actually play the sound `beep.wav` because it was specified so in your metadata file.
```
gdbus call --session --dest com.hack_computer.HackSoundServer --object-path /com/hack_computer/HackSoundServer --method com.hack_computer.HackSoundServer.PlaySound framework/piano/1
```
### Stop a sound
When you input the previous commands to play a sound you must have seen that something like the following has been output:
```
('a72276d2-a856-4531-aac1-59fe1d331fc1',)
```
This is the identifier of the sound you have told to play and you can use it to stop it.
```
gdbus call --session --dest com.hack_computer.HackSoundServer --object-path /com/hack_computer/HackSoundServer --method com.hack_computer.HackSoundServer.StopSound a72276d2-a856-4531-aac1-59fe1d331fc1
```

# Logging

## Log levels
The default log level is WARNING, which means that by default only WARNING,
ERROR and CRITICAL levels will be logged.

The log level can be set using the environment variable `HACK_SOUND_SERVER_LOGLEVEL`.

To log everything:
```
HACK_SOUND_SERVER_LOGLEVEL=0 flatpak run com.hack_computer.HackSoundServer
```

Or for example, to log levels from INFO and upper:
```
HACK_SOUND_SERVER_LOGLEVEL=INFO flatpak run com.hack_computer.HackSoundServer
```

For more information about levels, check the [Python logging system documentation](https://docs.python.org/3/library/logging.html).

## Format
For example, the following log output

```
DEBUG    : 2019-01-29 09:35:52,176 <HackSoundServer at 139708402141224>.ref - :1.19, :1.20: clubhouse/entry/hover: a1881470-0d54-4e1a-a4bd-3ca76a648ebf: Reference. Refcount: 1 (server.py:382)
```

should be interpreted as:

- `DEBUG`: The log level
- `2019-01-29 09:35:52,176`: The current date and time
- `<HackSoundServer at 139708402141224>`: The class and id of the object from which the log is called.
- `.ref`: The method that called the log instruction.
- `:1.19, :1.20:`: The unique bus names that referenced the sound.
- `clubhouse/entry/hover`: The sound event id.
- `a1881470-0d54-4e1a-a4bd-3ca76a648ebf`: The uuid.
- `Reference. Refcount: 1`: The log message.
- `(server.py:382)`: The file and line from which the log instruction was called.
