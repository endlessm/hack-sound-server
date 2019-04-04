class Registry:
    def __init__(self):
        self.sounds = {}
        # COunts the references of a sound by UUID and by bus name.
        self.refcount = {}
        self.watcher_by_bus_name = {}
        # Only useful for sounds tagged with "overlap-behavior":
        self.uuids_by_event_id = {}
        self.background_sounds = []
