import re
import struct
from session import Session

class Client:
    auth: bool

    def __init__(self) -> None:
        self.auth = False

    def handshake(self, data: bytes):
        return True

PROTOCOL_VERSION_MIN = 1
PROTOCOL_VERSION_MAX = 4

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

    def handshake(self, data: bytes):
        if len(data) < 2:
            return False
        
        # first byte is protocol version
        self.protocolVersion = data[0]
        if self.protocolVersion < PROTOCOL_VERSION_MIN or self.protocolVersion > PROTOCOL_VERSION_MAX:
            #logging.critical(f"[!] Error: client {sender.address} has incompatbile protocol version {arr[0]}")
            #self.send(sender, ":>>ERROR:Cannot connect to remote server due to protocol incompatibility")
            return False
        
        # second byte is an encoding str size
        if data[1] == 0:
            self.encoding = "utf8"
        else:
            if len(data) < data[1] + 2:
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
    prevmessages: list
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
        
        #extract uuid from message
        _uuid = data.decode()
        match = re.search(r"\w{8}-\w{4}-\w{4}-\w{4}-\w{12}", _uuid)
        if match and not _uuid == '' and not self.apptype == '':
            #search for uuid
            self.uuid = _uuid
            self.auth = True
            """ for session in self.sessions:
                #verify uuid of connected application
                if _uuid.find(session.host_uuid) != -1 and sender.client.apptype == "server":
                    session.addConnection(sender.sock, True)
                    sender.client.session = session
                    sender.client.auth = True
                    #read boolean flag for the endian
                    # this is workaround to send only one remaining byte
                    # WARNING: reversed byte order is not supported
                    sender.client.prevmessages.append(sender.sock.recv(1))
                    exchangeMessageFlag = True
                    logging.info(f"[S {session.name}]: Bindind {sender.client.apptype} {_uuid}")
                    break

                if sender.client.apptype == "client":
                    for p in session.clients_uuid:
                        if _uuid.find(p) != -1:
                            #client connection
                            session.addConnection(sender.sock, False)
                            sender.client.session = session
                            sender.client.auth = True
                            #read boolean flag for the endian
                            # this is workaround to send only one remaining byte
                            # WARNING: reversed byte order is not supported
                            sender.client.prevmessages.append(sender.sock.recv(1))
                            exchangeMessageFlag = True
                            logging.info(f"[S {session.name}] Binding {sender.client.apptype} {_uuid}")
                            break """
        
        return True

