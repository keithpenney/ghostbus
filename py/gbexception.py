# A nearly-empty Python module providing a custom Exception to many modules

class GhostbusException(Exception):
    def __init__(self, s):
        super().__init__("Ghostbus ERROR: " + s)

class GhostbusNameCollision(GhostbusException):
    def __init__(self, s):
        super().__init__("Ghostbus Name Collision: " + s)

class GhostbusFeatureRequest(GhostbusException):
    def __init__(self, s):
        super().__init__("Ghostbus Unsupported Feature: " + s)
