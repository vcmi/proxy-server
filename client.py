class Client:
    auth: bool

    def __init__(self) -> None:
        self.auth = False


class ClientLobby(Client):
    joined: bool
    username: str
    room_name: str
    protocolVersion: int
    encoding: str
    ready: bool
    vcmiversion: str #TODO: check version compatibility

    def __init__(self) -> None:
        super().__init__()
        self.room = ""
        self.joined = False
        self.username = ""
        self.protocolVersion = 0
        self.encoding = 'utf8'
        self.ready = False
        self.vcmiversion = ""


class ClientPipe(Client):
    apptype: str #client/server
    prevmessages: list
    session_name: str
    uuid: str

    def __init__(self) -> None:
        super().__init__()
        self.prevmessages = []
        self.session = ""
        self.apptype = ""
        self.uuid = ""


