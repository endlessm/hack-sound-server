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

    def _add_bg_uuid(self, uuid):
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

    def _get_sound_to_resume(self, uuid):
        sound = self.sounds.get(uuid)
        if sound is None or sound not in self.background_sounds:
            return None
        assert sound.type_ == "bg"

        self.background_sounds.remove(sound)
        if len(self.background_sounds) == 0:
            return None

        last_sound = self.background_sounds[-1]
        sound.server.logger.info("Resuming sound.",
                                 sound_event_id=last_sound.sound_event_id,
                                 uuid=last_sound.uuid)
        if self.refcount[last_sound.uuid] == 0:
            sound.server.logger.info("Cannot resume this sound because its "
                                     "owning apps have dissapeared from the "
                                     "bus.",
                                     sound_event_id=last_sound.sound_event_id,
                                     uuid=last_sound.uuid)
            return None
        return last_sound

    def add_sound(self, sound):
        """
        Adds a sound to the registry.

        Returns:
            The `Sound` object to pause if any. Otherwise, `None`.
        """
        self.sounds[sound.uuid] = sound
        self.sound_events.add_uuid(sound.sound_event_id, sound.uuid,
                                   sound.bus_name)
        return self._add_bg_uuid(sound.uuid)

    def remove_uuid(self, uuid):
        """
        Removes a sound from the registry.

        Args:
            uuid (str): The sound UUID.

        Returns:
            The `Sound` to resume if any. Otherwise, `None`.
        """
        if uuid not in self.sounds:
            return

        sound = self.sounds[uuid]
        sound_to_resume = self._get_sound_to_resume(sound.uuid)

        if sound.sound_event_id in self.sound_events.get_event_ids():
            self.sound_events.remove_uuid(sound.uuid)
        del self.sounds[sound.uuid]
        if sound.bus_name in self.watcher_by_bus_name:
            uuids = self.watcher_by_bus_name[sound.bus_name].uuids
            if sound.uuid in uuids:
                uuids.remove(sound.uuid)
        del self.refcount[sound.uuid]
        return sound_to_resume
