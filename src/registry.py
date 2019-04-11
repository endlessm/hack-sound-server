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
        # The following variables are used in API v2.
        self.players_by_bus_name = {}

    def add_bg_uuid(self, uuid):
        """
        Adds a sound to the list of background sounds safety.

        The following rule applies for 'bg' sounds: whenever a new 'bg' sound
        starts to play back, if any previous 'bg' sound was already playing,
        then pause that previous sound and play the new one. If this last sound
        finishes, then the last sound is resumed.

        Args:
            uuid (str): The sound UUID.

        Returns:
            A `Sound` object representing the target sound to pause. `None` can
            be returned in case of error, or if there is no sound to pause.
        """
        sound_to_pause = None

        sound = self.sounds.get(uuid)
        if sound is None or sound.type_ != "bg":
            return None
        # The following rule applies for 'bg' sounds: whenever a new 'bg'
        # sound starts to play back, if any previous 'bg' sound was already
        # playing, then pause that previous sound and play the new one. If
        # this last sound finishes, then the last sound is resumed.

        # Reorder the list of background sounds if necessary.
        if len(self.background_sounds) > 0:
            overlap_behavior = sound.server.metadata[sound.sound_event_id].get(
                "overlap-behavior", "overlap")

            # Sounds with overlap behavior 'ignore' or 'restart' are unique
            # so just need to move the incoming sound to the head/top of
            # the list/stack.
            if (overlap_behavior in ("ignore", "restart") and
                    sound in self.background_sounds):
                last_sound = self.background_sounds[-1]
                if last_sound != sound:
                    sound_to_pause = last_sound
                # Reorder.
                self.background_sounds.remove(sound)
                self.background_sounds.append(sound)

        if len(self.background_sounds) == 0:
            self.background_sounds.append(sound)
        elif self.background_sounds[-1] != sound:
            sound_to_pause = self.background_sounds[-1]
            self.background_sounds.append(sound)
        return sound_to_pause
