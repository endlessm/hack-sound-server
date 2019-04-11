class SoundEventUUIDInfo:
    """
    Tracks the UUIDs related to a specific sound event id.
    """
    def __init__(self):
        self._uuids = set()

    def add_sound(self, sound):
        """
        Adds the sound uuid to the set of uuids (per sound event id).
        """
        self._uuids.add(sound.uuid)

    def remove_sound(self, sound):
        """
        Removes the sound uuid from the set of uuids (per sound event id).
        """
        if sound.uuid not in self._uuids:
            return
        self._uuids.remove(sound.uuid)

    @property
    def uuids(self):
        """
        Gets the UUIDs for this sound event id info.
        """
        return self._uuids


class SoundEventsRegistry:
    """
    Tracks information related to a given sound event id.
    """
    def __init__(self):
        self._sound_events = {}

    def add_sound(self, sound):
        """
        Adds sound event id information related to a given sound.
        """
        if sound.sound_event_id not in self._sound_events:
            self._sound_events[sound.sound_event_id] = SoundEventUUIDInfo()
        self._sound_events[sound.sound_event_id].add_sound(sound)

    def remove_sound(self, sound):
        """
        Removes sound event id information related to a given sound.
        """
        if sound.sound_event_id not in self._sound_events:
            return
        self._sound_events[sound.sound_event_id].remove_sound(sound)
        if not self._sound_events[sound.sound_event_id].uuids:
            del self._sound_events[sound.sound_event_id]

    def get_uuids(self, sound_event_id):
        """
        Gets the UUIDs for a given sound event id.

        Returns:
            set: A set of UUIDs.
        """
        sound_event = self._sound_events.get(sound_event_id)
        if not sound_event:
            return set()
        return sound_event.uuids

    def get_event_ids(self):
        """
        Gets all the sound event ids in the registry.

        Returns:
            dict_keys: A setlike of sound event ids.
        """
        return self._sound_events.keys()

    def has_sound_event_id(self, sound_event_id):
        """
        Checks if a sound event id is in the registry.

        Returns:
            bool: True if the event id is in the registry. Otherwise, False.
        """
        return sound_event_id in self.get_event_ids()


class Registry:
    def __init__(self):
        self.sounds = {}
        # COunts the references of a sound by UUID and by bus name.
        self.refcount = {}
        self.watcher_by_bus_name = {}
        self.sound_events = SoundEventsRegistry()
        self.background_sounds = []
