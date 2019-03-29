from gi.repository import GObject


class SoundBase(GObject.Object):
    # API V2 compatibility.
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.id = None
        self.player = None
        self.manager = None
        self._object_path = None
        self.peer_bus_name = None
