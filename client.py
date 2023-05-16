import re
import struct
from session import Session

class Client:
    """
    Abstract client class with handshaking interface
    """
    auth: bool
    status: str # Information field to store error message which can be transferred to client

    def __init__(self) -> None:
        self.auth = False
        self.status = ""

    def handshake(self, data: bytes):
        return True

PROTOCOL_VERSION_MIN = 1
PROTOCOL_VERSION_MAX = 4

class ClientLobby(Client):
    """
    Lobby client type
    """
    joined: bool #is joined to some room
    username: str #usename specified in lobby prior connection
    room_name: str #if joined to the room, name of this room is stored here
    protocolVersion: int #client protocol version
    encoding: str #client string encoding
    ready: bool #is ready for start session
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

    def handshake(self, data: bytes):
        if len(data) < 2:
            # actually could be different errors, but assuming that just name isn't specified
            self.status = "Too short username"
            return False
        
        # first byte is protocol version
        self.protocolVersion = data[0]
        if self.protocolVersion < PROTOCOL_VERSION_MIN or self.protocolVersion > PROTOCOL_VERSION_MAX:
            self.status = "Cannot connect to remote server due to protocol incompatibility"
            #logging.critical(f"[!] Error: client {sender.address} has incompatbile protocol version {arr[0]}")
            #self.send(sender, ":>>ERROR:Cannot connect to remote server due to protocol incompatibility")
            return False
        
        # second byte is an encoding str size
        if data[1] == 0:
            self.encoding = "utf8"
        else:
            if len(data) < data[1] + 2:
                self.status = "Protocol error or incorrect encoding"
                #logging.critical(f"[!] Client {sender.address} message is incorrect: {arr}")
                #self.send(sender, ":>>ERROR:Protocol error")
                return False
            # read encoding string
            self.encoding = data[2:(data[1] + 2)].decode(errors='ignore')
            data = data[(data[1] + 2):]
        
        return True


class ClientPipe(Client):
    apptype: str #client/server
    uuid: str
    prevmessages: list #message queue to be send to opposite client
    session: Session

    def __init__(self) -> None:
        super().__init__()
        self.prevmessages = []
        self.session = None
        self.apptype = ""
        self.uuid = ""

    def testForSession(self, ses):
        if self.apptype == "server" and ses.host_uuid == self.uuid:
            return True
        if self.apptype == "client" and self.uuid in ses.clients_uuid:
            return True
        return False

    def isServer(self):
        if self.apptype == "server":
            return True
        if self.apptype == "client":
            return False
        return None

    def handshake(self, data: bytes):

        self.prevmessages.append(struct.pack('<I', len(data)) + data) #pack message

        #search fo application type in the message
        match = re.search(r"\((\w+)\)", str(data))
        if match:
            self.apptype = match.group(1)
            self.status = f"Client type {self.apptype}, continue..."
        
        #extract uuid from message
        _uuid = data.decode()
        match = re.search(r"\w{8}-\w{4}-\w{4}-\w{4}-\w{12}", _uuid)
        if match and not _uuid == '' and not self.apptype == '':
            #search for uuid
            self.uuid = _uuid
            self.auth = True
            self.status = f"Success! Client type {self.apptype}, uuid {self.uuid}"
        
        return True


