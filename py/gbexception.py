# A nearly-empty Python module providing a custom Exception to many modules

class GhostbusException(Exception):
    def __init__(self, s):
        super().__init__(s)

class GhostbusNameCollision(GhostbusException):
    def __init__(self, s):
        super().__init__(s)
