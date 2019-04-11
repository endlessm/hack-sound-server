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

    def try_add_bg_sound(self, sound):
        """
        Adds a sound to the list of background sounds.

        The following rule applies for 'bg' sounds: whenever a new 'bg' sound
        starts to play back, if any previous 'bg' sound was already playing,
        then pause that previous sound and play the new one. If this last sound
        finishes, then the last sound is resumed.

        Args:
            sound (Sound): The sound to add.

        Returns:
            Previously playing background `Sound` object, or `None` if there
            was no background sound already playing or no action is required.
        """
        if sound.type_ != "bg":
            return None

        previous_bg_sound = None
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
                    previous_bg_sound = last_sound
                # Reorder.
                self.background_sounds.remove(sound)
                self.background_sounds.append(sound)

        if len(self.background_sounds) == 0:
            self.background_sounds.append(sound)
        elif self.background_sounds[-1] != sound:
            previous_bg_sound = self.background_sounds[-1]
            self.background_sounds.append(sound)
        return previous_bg_sound

    def _get_sound_to_resume(self, sound):
        if sound not in self.background_sounds:
            return None
        assert sound.type_ == "bg"

        self.background_sounds.remove(sound)
        if len(self.background_sounds) == 0:
            return None

        previous_bg_sound = self.background_sounds[-1]
        sound.server.logger.info(
            "Resuming sound.",
            sound_event_id=previous_bg_sound.sound_event_id,
            uuid=previous_bg_sound.uuid
        )
        if self.refcount[previous_bg_sound.uuid] == 0:
            sound.server.logger.info(
                "Cannot resume this sound because its owning apps have "
                "dissapeared from the bus.",
                sound_event_id=previous_bg_sound.sound_event_id,
                uuid=previous_bg_sound.uuid
            )
            return None
        return previous_bg_sound

    def remove_sound(self, sound):
        """
        Removes a sound from the registry.

        Args:
            sound (Sound): The sound to remove.

        Returns:
            The `Sound` to resume if any. Otherwise, `None`.
        """
        if sound.uuid not in self.sounds:
            return

        sound_to_resume = self._get_sound_to_resume(sound)

        self.sound_events.remove_sound(sound)
        del self.sounds[sound.uuid]
        if sound.bus_name in self.watcher_by_bus_name:
            uuids = self.watcher_by_bus_name[sound.bus_name].uuids
            if sound.uuid in uuids:
                uuids.remove(sound.uuid)
        del self.refcount[sound.uuid]
        return sound_to_resume
