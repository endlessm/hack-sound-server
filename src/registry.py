from gi.repository import GObject


class SoundEventUUIDInfo:
    """
    Tracks UUIDs (classified by bus name) related to a specific sound event id.
    """
    def __init__(self):
        # _uuids_by_bus_name and _uuids contain the same UUIDs.
        self._uuids_by_bus_name = {}
        self._uuids = set()

    def add_sound(self, sound):
        """
        Adds the sound uuid to the set of uuids (per sound event id).
        """
        if sound.bus_name not in self._uuids_by_bus_name:
            self._uuids_by_bus_name[sound.bus_name] = set()
        self._uuids.add(sound.uuid)
        self._uuids_by_bus_name[sound.bus_name].add(sound.uuid)

    def remove_sound(self, sound):
        """
        Removes the sound uuid from the set of uuids (per sound event id).
        """
        if sound.uuid in self.uuids:
            self._uuids.remove(sound.uuid)
        if sound.bus_name in self._uuids_by_bus_name:
            if sound.uuid in self._uuids_by_bus_name[sound.bus_name]:
                self._uuids_by_bus_name[sound.bus_name].remove(sound.uuid)
            if len(self._uuids_by_bus_name[sound.bus_name]) == 0:
                del self._uuids_by_bus_name[sound.bus_name]

    def get_uuids(self, bus_name):
        """
        Gets the UUIDs filtering them by bus name.

        Args:
            bus_name (str): A bus name to filter UUIDs.

        Returns:
            set: A set containing the UUIDs.
        """
        if bus_name is not None:
            return self._uuids_by_bus_name.get(bus_name, set())
        return self._uuids

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

    def get_uuids(self, sound_event_id, bus_name=None):
        """
        Gets the UUIDs for a given sound event id.

        Returns:
            set: A set of UUIDs.
        """
        sound_event = self._sound_events.get(sound_event_id)
        if not sound_event:
            return set()
        return sound_event.get_uuids(bus_name)

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


class Registry(GObject.Object):
    __gsignals__ = {
        "player-added": (GObject.SignalFlags.RUN_FIRST, None, (object, )),
        "player-removed": (GObject.SignalFlags.RUN_FIRST, None, (object, ))
    }

    def __init__(self):
        super().__init__()
        self.sounds = {}
        # COunts the references of a sound by UUID and by bus name.
        self.refcount = {}
        self.watcher_by_bus_name = {}
        self.sound_events = SoundEventsRegistry()
        self.background_sounds = []
        # Used in API v2.
        self.players_by_bus_name = {}

    def _try_add_bg_sound(self, sound):
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

    def add_sound(self, sound):
        """
        Adds a sound to the registry.

        Args:
            sound (Sound): The sound to add to the registry.

        Returns:
            In the case of a bg sound, the previously playing background
            `Sound` object, or `None` if there was no background sound already
            playing or if the given sound is not a bg sound.
        """
        self.sounds[sound.uuid] = sound
        self.sound_events.add_sound(sound)
        return self._try_add_bg_sound(sound)

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

    def get_player(self, app_id, options):
        """
        Obtains a player given its app id (a well-known name) and options.

        Arguments:
            app_id (str): A well known name, ie: "com.endlessm.Fizzics".
            options (dict): A dictionary with options.

        Returns:
            A `Player` object if it exists in the registry with the matching
            options. Otherwise, `None`.
        """
        players = self.players_by_bus_name.get(app_id, options)
        for player in players:
            if player.options == options:
                return player
        return None

    def add_player(self, player):
        if player.bus_name not in self.players_by_bus_name:
            self.players_by_bus_name[player.bus_name] = set()
        self.players_by_bus_name[player.bus_name].add(player)
        self.emit("player-added", player)

    def remove_player(self, app_id, options):
        existing_player = self.get_player(app_id, options)
        if existing_player is None:
            return

        self.players_by_bus_name[app_id].remove(existing_player)
        self.emit("player-removed", existing_player)

    def remove_players(self, app_id):
        players = self.players_by_bus_name.get(app_id)
        if players is None:
            return

        del self.players_by_bus_name[app_id]
        for player in players:
            self.emit("player-removed", player)

    @property
    def players(self):
        return self.players_by_bus_name.items()
