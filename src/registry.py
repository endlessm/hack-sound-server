class SoundEventRegistry:
    def __init__(self, registry):
        self.registry = registry
        # _uuids_by_bus_name and _uuids contain the same UUIDs.
        self._uuids_by_bus_name = {}
        self._uuids = set([])

    def add_uuid(self, uuid, bus_name):
        if bus_name not in self._uuids_by_bus_name:
            self._uuids_by_bus_name[bus_name] = set([])
        self._uuids.add(uuid)
        self._uuids_by_bus_name[bus_name].add(uuid)

    def remove_uuid(self, uuid):
        sound = self.registry.sounds[uuid]
        self._uuids.remove(uuid)
        self._uuids_by_bus_name[sound.bus_name].remove(uuid)
        if len(self._uuids_by_bus_name[sound.bus_name]) == 0:
            del self._uuids_by_bus_name[sound.bus_name]

    @property
    def uuids(self):
        return self._uuids


class SoundEventsRegistry:
    def __init__(self, registry):
        self.registry = registry
        self._sound_events = {}

    def add_uuid(self, sound_event_id, uuid, bus_name):
        if sound_event_id not in self._sound_events:
            self._sound_events[sound_event_id] = \
                SoundEventRegistry(self.registry)
        self._sound_events[sound_event_id].add_uuid(uuid, bus_name)

    def remove_uuid(self, uuid):
        sound = self.registry.sounds[uuid]
        self._sound_events[sound.sound_event_id].remove_uuid(uuid)
        if not self._sound_events[sound.sound_event_id].uuids:
            del self._sound_events[sound.sound_event_id]

    def get_uuids(self, sound_event_id):
        sound_event = self._sound_events.get(sound_event_id)
        if not sound_event:
            return set([])
        return sound_event.uuids

    def get_event_ids(self):
        return iter(self._sound_events)


class Registry:
    def __init__(self):
        self.sounds = {}
        # COunts the references of a sound by UUID and by bus name.
        self.refcount = {}
        self.watcher_by_bus_name = {}
        self.sound_events = SoundEventsRegistry(self)
        self.background_sounds = []
