import sys
import socket
import re
import uuid
import struct
import logging
import time
from threading import Thread

PROXYSERVER_VERSION = "0.4.0"

LOG_LEVEL = logging.INFO
LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL
}

PROTOCOL_VERSION_MIN = 1
PROTOCOL_VERSION_MAX = 4

HEALTHCHECK_TIMER = 30

# server's IP address
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5002 # port we want to use

MAX_CONNECTIONS = 50
SYSUSER = "System" #username from whom system messages will be sent

for arg in sys.argv[1:]:
    element = arg.partition("=")
    if element[1] != "=":
        print(f"Unknown argument: {arg}")
        continue

    if element[0] == "logging":
        LOG_LEVEL = LOG_LEVELS[element[2]]

    if element[0] == "port":
        num = int(element[2])
        if num == 0:
            print(f"Cannot listn port 0, continue with default {SERVER_PORT}")
            continue
        SERVER_PORT = num

    if element[0] == "capacity":
        num = int(element[2])
        if num == 0:
            print(f"Cannot limit connections capacity with 0, continue with default {MAX_CONNECTIONS}")
            continue
        MAX_CONNECTIONS = num

    if element[0] == "healthcheck":
        num = int(element[2])
        if num < 10:
            print(f"Too frequent timer for healthcheck, continue with default {HEALTHCHECK_TIMER}")
            continue
        HEALTHCHECK_TIMER = num

STATS = {
    "uniques" : set(), #address
    "users" : set(), #usernames
    "logins" : 0, #sockets
    "clients" : 0, #vcmi clients
    "rooms" : 0, #created rooms
    "sessions" : 0, #started sessions
    "connections" : 0 #successful connections
}

#game modes
NEW_GAME = 0
LOAD_GAME = 1

#logging
logHandlerHighlevel = logging.FileHandler('proxyServer.log')
logHandlerHighlevel.setLevel(logging.INFO)

logHandlerLowlevel = logging.FileHandler('proxyServer_debug.log')
logHandlerLowlevel.setLevel(logging.DEBUG)

handlers = [logHandlerHighlevel]
if LOG_LEVEL == logging.DEBUG:
    handlers.append(logHandlerLowlevel)

logging.basicConfig(handlers=handlers, level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')

def receive_packed(sock):
    # Read message length and unpack it into an integer
    raw_msglen = recvall(sock, 4)
    if not raw_msglen:
        return None
    msglen = struct.unpack('<I', raw_msglen)[0]
    # Read the message data
    return recvall(sock, msglen)

def recvall(sock, n):
    # Helper function to recv n bytes or return None if EOF is hit
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data


class GameConnection:
    server: socket # socket to vcmiserver
    client: socket # socket to vcmiclient
    serverInit = False # if vcmiserver already connected
    clientInit = False # if vcmiclient already connected

    def __init__(self) -> None:
        self.server = None
        self.client = None
        pass


class Room:
    total = 1 # total amount of players
    joined = 0 # amount of players joined to the session
    password = "" # password to connect
    protected = False # if True, password is required to join to the session
    name: str # name of session
    host: socket # player socket who created the room
    players = [] # list of sockets of players, joined to the session
    mods = {} # modname - version pairs of enabled by host mods
    gamemode = NEW_GAME # game
    started = False

    def __init__(self, host: socket, name: str) -> None:
        self.name = name
        self.host = host
        self.players = [host]
        self.joined = 1
        self.gamemode = NEW_GAME
        self.mods = {}

    def isJoined(self, player: socket) -> bool:
        return player in self.players

    def join(self, player: socket):
        if not self.isJoined(player) and self.joined < self.total:
            self.players.append(player)
            self.joined += 1

    def leave(self, player: socket):
        if not self.isJoined(player) or player == self.host:
            return

        self.players.remove(player)
        self.joined -= 1

    def modsString(self) -> str:
        result = f"{len(self.mods)}"
        for m in self.mods.keys():
            result += f":{m}:{self.mods[m]}"
        return result
    
    def verifyForStart(self) -> bool:
        for pl in self.players:
            if not client_sockets[pl].client.ready:
                return False
        
        return True
    
    def resetPlayersReady(self):
        for pl in self.players:
            client_sockets[pl].client.ready = False


class Session:
    name: str # name of session
    host_uuid: str # uuid of vcmiserver for hosting player
    clients_uuid: list # list od vcmiclients uuid
    players: list # list of sockets of players, joined to the session
    connections: list # list of GameConnections for vcmiclient/vcmiserver (game mode)
    pipes: dict #dictionary of pipes for speed up

    def __init__(self) -> None:
        self.name = ""
        self.host_uuid = ""
        self.clients_uuid = []
        self.connections = []
        self.pipes = {}
        pass

    def addConnection(self, conn: socket, isServer: bool):
        #find uninitialized server connection
        for gc in self.connections:
            if isServer and not gc.serverInit:
                gc.server = conn
                gc.serverInit = True
                self.pipes[conn] = gc.client
                self.pipes[gc.client] = conn
                return
            if not isServer and not gc.clientInit:
                gc.client = conn
                gc.clientInit = True
                self.pipes[conn] = gc.server
                self.pipes[gc.server] = conn
                return
            
        #no existing connection - create the new one
        gc = GameConnection()
        if isServer:
            gc.server = conn
            gc.serverInit = True
        else:
            gc.client = conn
            gc.clientInit = True
        self.connections.append(gc)

    def removeConnection(self, conn: socket):
        if self.validPipe(conn):
            self.pipes.pop(self.getPipe(conn))
            self.pipes.pop(conn)

        newConnections = []
        for c in self.connections:
            if c.server == conn:
                c.server = None
                c.serverInit = False
            if c.client == conn:
                c.client = None
                c.clientInit = False
            if c.server != None or c.client != None:
                newConnections.append(c)
        self.connections = newConnections

    def validPipe(self, conn) -> bool:
        return conn in self.pipes.keys()

    def getPipe(self, conn) -> socket:
        return self.pipes[conn]


class Client:
    auth: bool

    def __init__(self) -> None:
        self.auth = False


class ClientLobby(Client):
    joined: bool
    username: str
    room: Room
    protocolVersion: int
    encoding: str
    ready: bool
    vcmiversion: str #TODO: check version compatibility
    timer: int

    def __init__(self) -> None:
        super().__init__()
        self.room = None
        self.joined = False
        self.username = ""
        self.protocolVersion = 0
        self.encoding = 'utf8'
        self.ready = False
        self.vcmiversion = ""
        self.timer = HEALTHCHECK_TIMER


class ClientPipe(Client):
    apptype: str #client/server
    prevmessages: list
    session: Session
    uuid: str

    def __init__(self) -> None:
        super().__init__()
        self.prevmessages = []
        self.session = None
        self.apptype = ""
        self.uuid = ""


class Sender:
    address: str #full client address
    client: Client

    def __init__(self) -> None:
        self.client = None
        pass

    def isLobby(self) -> bool:
        return isinstance(self.client, ClientLobby)

    def isPipe(self) -> bool:
        return isinstance(self.client, ClientPipe)


# create a TCP socket
s = socket.socket()
# make the port as reusable port
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# bind the socket to the address we specified
s.bind((SERVER_HOST, SERVER_PORT))
# listen for upcoming connections
s.listen(MAX_CONNECTIONS)
logging.info("=============================================")
logging.info(f"[!] ProxyServer version {PROXYSERVER_VERSION}")
logging.info(f"[!] Listening as {SERVER_HOST}:{SERVER_PORT}")

# active rooms
rooms = {}

# list of active sessions
sessions = []

# initialize list/set of all connected client's sockets
client_sockets = {}

#correctly process disconnection and close socket
def handleDisconnection(client: socket):

    if not client in client_sockets:
        logging.warning("[!] Disconnection for removed socket")
        return

    logging.info(f"[!] Disconnecting {client_sockets[client].address}")

    sender = client_sockets[client]
    #cleanup room
    if sender.isLobby() and sender.client.joined:
        if not sender.client.room.started:
            if sender.client.room.host == client:
                #destroy the session, sending messages inside the function
                deleteRoom(sender.client.room)
            else:
                sender.client.room.leave(client)
                sender.client.joined = False
                message = f":>>KICK:{sender.client.room.name}:{sender.client.username}"
                broadcast(sender.client.room.players, message.encode())
            updateStatus(sender.client.room)
            updateRooms()

    #cleanup session
    if sender.isPipe() and sender.client.auth:
        if sender.client.session in sessions:
            logging.info(f"[S {sender.client.session.name}]: Remove {sender.client.apptype}")
            #break opposite connection
            if sender.client.session.validPipe(client):
                opposite = sender.client.session.getPipe(client)
                logging.info(f"[S {sender.client.session.name}]: Disconnecting pipe socket for {client_sockets[opposite].client.apptype} at {client_sockets[opposite].address}")
                sender.client.session.removeConnection(opposite)
                opposite.close()
                client_sockets.pop(opposite)

            sender.client.session.removeConnection(client)
            if not len(sender.client.session.connections):
                logging.info(f"[S {sender.client.session.name}] Destroying session")
                sessions.remove(sender.client.session)

    client.close()
    client_sockets.pop(client)
    logging.debug(f"---- disconnected")

    #updating list of users
    for cl in client_sockets.keys():
        if client_sockets[cl].isLobby() and client_sockets[cl].client.auth and client_sockets[cl].client.protocolVersion >= 4:
            sendUsers(cl)


#sending message for lobby players
def send(client: socket, message: str):
    if client in client_sockets.keys():
        sender = client_sockets[client]
        client.send(message.encode(encoding=sender.client.encoding, errors='replace'))


def broadcast(clients: list, message: str):
    for c in clients:
        if client_sockets[c].isLobby() and client_sockets[c].client.auth:
            send(c, message)


def sendRooms(client: socket):
    msg2 = ""
    counter = 0
    for s in rooms.values():
        if not s.started:
            msg2 += f":{s.name}:{s.joined}:{s.total}:{s.protected}"
            counter += 1
    msg = f":>>SESSIONS:{counter}{msg2}"

    send(client, msg)

def sendUsers(client: socket):
    targetClients = [i for i in client_sockets.keys() if client_sockets[i].isLobby()]
    msg = f":>>USERS:{len(targetClients)}"
        
    for cl in targetClients:
        msg += f":{client_sockets[cl].client.username}"
    
    send(client, msg)


def sendCommonInfo(client: socket):
    if client_sockets[client].client.protocolVersion >= 4:
        sendUsers(client)

    lobby_users = [i for i in client_sockets.keys() if client_sockets[i].isLobby() and client_sockets[i].client.auth]
    play_users = [i for i in client_sockets.keys() if client_sockets[i].isPipe()]
    msg = f":>>MSG:{SYSUSER}:Here available {len(lobby_users) - 1} users, currently playing {len(play_users)}"
    if client_sockets[client].client.protocolVersion < 4:
        msg += "\n Send <HERE> to see people names in the chat"
    msg += "\n Send direct message by typing @username"
    send(client, msg)


def updateRooms():
    for s in client_sockets.keys():
        if client_sockets[s].isLobby():
            sendRooms(s)


def deleteRoom(room: Room):
    msg = f":>>KICK:{room.name}"
    for player in room.players:
        client_sockets[player].client.joined = False
        msg2 = msg + f":{client_sockets[player].client.username}"
        send(player, msg2)
    
    logging.info(f"[R {room.name}]: Destroying room")
    rooms.pop(room.name)


def updateStatus(room: Room):
    msg = f":>>STATUS:{room.joined}"
    for player in room.players:
        msg += f":{client_sockets[player].client.username}:{client_sockets[player].client.ready}"
    broadcast(room.players, msg)


def startRoom(room: Room):
    STATS["sessions"] += 1
    room.started = True
    session = Session()
    session.name = room.name
    sessions.append(session)
    logging.info(f"[S {session.name}] Starting for {room.joined} players")
    session.host_uuid = str(uuid.uuid4())
    hostMessage = f":>>HOST:{session.host_uuid}:{room.joined - 1}" #one client will be connected locally
    logging.debug(f"---- host: {session.host_uuid} connections {room.joined - 1}")
    #host message must be before start message
    send(room.host, hostMessage)

    for player in room.players:
        _uuid = str(uuid.uuid4())
        session.clients_uuid.append(_uuid)
        msg = f":>>START:{_uuid}"
        send(player, msg)
        #remove this connection
        player.close
        client_sockets.pop(player)

    #this room shall not exist anymore
    logging.info(f"[R {room.name}] Exit room as session {session.name} was started")
    rooms.pop(room.name)

    
def startRoomIfReady(room: Room) -> bool:
    if room.joined > 1 and room.verifyForStart():
        startRoom(room)
        return True
    
    return False


def messageTarget(s: str):
    ttuple = s.partition("@")
    if ttuple[0] != "" or ttuple[1] != "@":
        return ("", s)

    ttuple = ttuple[2].partition(" ")
    if ttuple[0] == "":

        return ("", s)

    return (ttuple[0], ttuple[2])    


def timer_for_clients():
    start = time.time()
    while True:
        end = time.time()
        if end - start >= HEALTHCHECK_TIMER:
            start = end
            clientsForRemove = []
            for cs in client_sockets.keys():
                if client_sockets[cs].isLobby() and client_sockets[cs].client.auth and client_sockets[cs].client.protocolVersion >= 4:
                    client_sockets[cs].client.timer -= HEALTHCHECK_TIMER
                    if client_sockets[cs].client.timer <= 0:
                        send(cs, ":>>HEALTH:")
                    if client_sockets[cs].client.timer <= -HEALTHCHECK_TIMER:
                        clientsForRemove.append(cs)
            
            for cs in clientsForRemove:
                handleDisconnection(cs)


def dispatch(cs: socket, sender: Sender, arr: bytes):
    
    if arr == None or len(arr) == 0:
        return

    if (sender.isPipe() or sender.isLobby() and not sender.client.auth) or (not sender.isPipe() and not sender.isLobby()):
        logging.debug(f"---- {sender.address} is sending {arr}")

    #check for game mode connection
    msg = str(arr)
    exchangeMessageFlag = False #flag to identify if message exchange was started
    if msg.find("Aiya!") != -1:
        sender.client = ClientPipe()
        logging.info("[!] VCMI recognized")
        STATS["clients"] += 1

    if sender.isPipe():
        if sender.client.auth: #if already playing - sending raw bytes as is
            sender.client.prevmessages.append(arr)
        else:
            sender.client.prevmessages.append(struct.pack('<I', len(arr)) + arr) #pack message
            logging.debug("---- packing message")
            #search fo application type in the message
            match = re.search(r"\((\w+)\)", msg)
            _appType = ''
            if match != None:
                _appType = match.group(1)
                sender.client.apptype = _appType
            
            #extract uuid from message
            _uuid = arr.decode()
            logging.debug(f"---- decoding {_uuid}")
            if not _uuid == '' and not sender.client.apptype == '':
                #search for uuid
                for session in sessions:
                    #verify uuid of connected application
                    if _uuid.find(session.host_uuid) != -1 and sender.client.apptype == "server":
                        session.addConnection(cs, True)
                        sender.client.session = session
                        sender.client.auth = True
                        #read boolean flag for the endian
                        # this is workaround to send only one remaining byte
                        # WARNING: reversed byte order is not supported
                        sender.client.prevmessages.append(cs.recv(1))
                        exchangeMessageFlag = True
                        logging.info(f"[S {session.name}]: Bindind {sender.client.apptype} {_uuid}")
                        break

                    if sender.client.apptype == "client":
                        for p in session.clients_uuid:
                            if _uuid.find(p) != -1:
                                #client connection
                                session.addConnection(cs, False)
                                sender.client.session = session
                                sender.client.auth = True
                                #read boolean flag for the endian
                                # this is workaround to send only one remaining byte
                                # WARNING: reversed byte order is not supported
                                sender.client.prevmessages.append(cs.recv(1))
                                exchangeMessageFlag = True
                                logging.info(f"[S {session.name}] Binding {sender.client.apptype} {_uuid}")
                                break

    #game mode
    if sender.isPipe() and sender.client.auth and sender.client.session.validPipe(cs):
        #send messages from queue
        opposite = sender.client.session.getPipe(cs)
        if opposite not in client_sockets:
            logging.critical(f"[S {sender.client.session.name}] Opposite socket is not connected")
            return

        if exchangeMessageFlag:
            logging.info(f"[S {sender.client.session.name}] Message exchange {sender.address} - {client_sockets[opposite].address}")
            STATS["connections"] += 1

        #sending our messages to opposite client
        for x in sender.client.prevmessages:
            opposite.sendall(x)

        #receiving messages from opposite client
        for x in client_sockets[opposite].client.prevmessages:
            cs.sendall(x)

        client_sockets[opposite].client.prevmessages.clear()
        sender.client.prevmessages.clear()
        return

    #we are in pipe mode but game still not started - waiting other clients to connect
    if sender.isPipe():
        logging.debug(f"---- waiting other clients")
        return
    
    #intialize lobby mode
    if not sender.isLobby():
        if len(arr) < 2: 
            logging.critical("[!] Error: unknown client tries to connect")
            #TODO: block address? close the socket?
            return

        sender.client = ClientLobby()

        # first byte is protocol version
        sender.client.protocolVersion = arr[0]
        if arr[0] < PROTOCOL_VERSION_MIN or arr[0] > PROTOCOL_VERSION_MAX:
            logging.critical(f"[!] Error: client {sender.address} has incompatbile protocol version {arr[0]}")
            send(cs, ":>>ERROR:Cannot connect to remote server due to protocol incompatibility")
            return

        # second byte is an encoding str size
        if arr[1] == 0:
            sender.client.encoding = "utf8"
        else:
            if len(arr) < arr[1] + 2:
                logging.critical(f"[!] Client {sender.address} message is incorrect: {arr}")
                send(cs, ":>>ERROR:Protocol error")
                return
            # read encoding string
            sender.client.encoding = arr[2:(arr[1] + 2)].decode(errors='ignore')
            arr = arr[(arr[1] + 2):]
            msg = str(arr)

    msg = arr.decode(encoding=sender.client.encoding, errors='replace')
    _open = msg.partition('<')
    _close = _open[2].partition('>')
    if _open[0] != '' or _open[1] == '' or _open[2] == '' or _close[0] == '' or _close[1] == '':
        logging.error(f"[!] Incorrect message from {sender.address}: {msg}")
        return

    _nextTag = _close[2].partition('<')
    tag = _close[0]
    tag_value = _nextTag[0]

    #greetings to the server
    if tag == "GREETINGS":
        if sender.client.auth:
            logging.critical(f"[*] Greetings from authorized user {sender.client.username} {sender.address}")
            send(cs, ":>>ERROR:User already authorized")
            return

        if len(tag_value) < 3:
            logging.warning(f"[!] Incorrect username from {sender.address}: {tag_value}")
            send(cs, f":>>ERROR:Too short username {tag_value}")
            return

        if tag_value == SYSUSER or tag_value == "all" or len(tag_value.split(" ")) > 1:
            logging.warning(f"[!] Incorrect username from {sender.address}: {tag_value}")
            send(cs, f":>>ERROR:Invalid username")
            return

        for user in client_sockets.values():
            if user.isLobby() and user.client.username == tag_value:
                logging.warning(f"[!] Client username already exist {sender.address}: {tag_value}")
                send(cs, f":>>ERROR:Can't connect with the name {tag_value}. This login is already occpupied")
                return
        
        logging.info(f"[*] {sender.address} autorized as {tag_value}")
        STATS["users"].add(tag_value)
        sender.client.username = tag_value
        #sending info that someone here before authorizing - to not send it to itself
        targetClientsOld = [i for i in client_sockets.keys() if client_sockets[i].isLobby() and client_sockets[i].client.protocolVersion < 4]
        message = f":>>MSG:{SYSUSER}:{sender.client.username} is here"
        broadcast(targetClientsOld, message)
        #updating list of users
        for cl in client_sockets.keys():
            if client_sockets[cl].isLobby() and client_sockets[cl].client.protocolVersion >= 4:
                sendUsers(cl)
        #authorizing user
        sender.client.auth = True
        sendRooms(cs)
        sendCommonInfo(cs)

    #VCMI version received
    if tag == "VER" and sender.client.auth:
        logging.info(f"[*] User {sender.client.username} has version {tag_value}")
        sender.client.vcmiversion = tag_value

    #message received
    if tag == "MSG" and sender.client.auth:
        target = messageTarget(tag_value)
        targetClients = [i for i in client_sockets.keys() if client_sockets[i].isLobby()]
        if sender.client.joined and target[0] != "all":
            targetClients = sender.client.room.players #send message only to players in the room
        
        if target[0] != "" and target[0] != "all":
            for cl in targetClients:
                if client_sockets[cl].client.username == target[0]:
                    targetClients = [cl, cs]

        message = f":>>MSG:{sender.client.username}:{target[1]}"
        broadcast(targetClients, message)

    #new room
    if tag == "NEW" and sender.client.auth and not sender.client.joined:
        if tag_value in rooms:
            #refuse creating game
            message = f":>>ERROR:Cannot create session with name {tag_value}, session with this name already exists"
            send(cs, message)
            return

        if tag_value == "" or tag_value.startswith(" ") or len(tag_value) < 3:
            #refuse creating game
            message = f":>>ERROR:Cannot create session with invalid name {tag_value}"
            send(cs, message)
            return
        
        rooms[tag_value] = Room(cs, tag_value)
        sender.client.joined = True
        sender.client.ready = False
        sender.client.room = rooms[tag_value]
        logging.info(f"[R {tag_value}]: room created")
        STATS["rooms"] += 1

    #set password for the session
    if tag == "PSWD" and sender.client.auth and sender.client.joined and sender.client.room.host == cs:
        sender.client.room.password = tag_value
        sender.client.room.protected = bool(tag_value != "")

    #set amount of players to the new room
    if tag == "COUNT" and sender.client.auth and sender.client.joined and sender.client.room.host == cs:
        if sender.client.room.total != 1:
            #refuse changing amount of players
            message = f":>>ERROR:Changing amount of players is not possible for existing session"
            send(cs, message)
            return

        if int(tag_value) < 2 or int(tag_value) > 8:
            #refuse and cleanup room
            deleteRoom(sender.client.room)
            message = f":>>ERROR:Cannot create room with invalid amount of players"
            send(cs, message)
            return

        sender.client.room.total = int(tag_value)
        message = f":>>CREATED:{sender.client.room.name}"
        send(cs, message)
        #now room is ready to be broadcasted
        message = f":>>JOIN:{sender.client.room.name}:{sender.client.username}"
        send(cs, message)
        updateStatus(sender.client.room)
        updateRooms()
        #send instructions to player
        message = f":>>MSG:{SYSUSER}:You are in the room chat. To send message to global chat, type @all"
        send(cs, message)

    #join session
    if tag == "JOIN" and sender.client.auth and not sender.client.joined:
        if tag_value not in rooms:
            message = f":>>ERROR:Room with name {tag_value} doesn't exist"
            send(cs, message)
            return
        
        if rooms[tag_value].joined >= rooms[tag_value].total:
            message = f":>>ERROR:Room {tag_value} is full"
            send(cs, message)
            return

        if rooms[tag_value].started:
            message = f":>>ERROR:Session {tag_value} is started"
            send(cs, message)
            return

        sender.client.joined = True
        sender.client.ready = False
        sender.client.room = rooms[tag_value]

    if tag == "PSWD" and sender.client.auth and sender.client.joined and sender.client.room.host != cs:
        if not sender.client.room.protected or sender.client.room.password == tag_value:
            sender.client.room.join(cs)
            message = f":>>JOIN:{sender.client.room.name}:{sender.client.username}"
            logging.info(f"[R {sender.client.room.name}] {sender.client.username} joined")
            broadcast(sender.client.room.players, message)
            updateStatus(sender.client.room)
            updateRooms()
            #send instructions to player
            message = f":>>MSG:{SYSUSER}:You are in the room chat. To send message to global chat, type @all"
            send(cs, message)
            #verify version and send warning
            host_sender = client_sockets[sender.client.room.host]
            if sender.client.vcmiversion != host_sender.client.vcmiversion:
                message = f":>>MSG:{SYSUSER}:Your VCMI version {sender.client.vcmiversion} differs from host version {host_sender.client.vcmiversion}, which may cause problems"
                send(cs, message)

        else:
            sender.client.joined = False
            message = f":>>ERROR:Incorrect password"
            send(cs, message)
            return

    #[PROTOCOL 4] set game mode
    if tag == "HOSTMODE" and sender.client.auth and sender.client.joined:
        #checks for permissions
        if sender.client.room.host != cs:
            message = ":>>ERROR:Insuficcient permissions"
            send(cs, message)
            return

        #update game mode for everybody
        sender.client.room.gamemode = int(tag_value)
        message = f":>>GAMEMODE:{sender.client.room.gamemode}"
        broadcast(sender.client.room.players, message)


    #[PROTOCOL 2] receive list of mods
    if tag == "MODS" and sender.client.auth and sender.client.joined:
        mods = tag_value.split(";") #list of modname&modverion
        
        if sender.client.room.host == cs:
            #set mods
            for m in mods:
                mp = m.partition("&")
                sender.client.room.mods[mp[0]] = mp[2]
        
        #send mods
        message = f":>>MODS:{sender.client.room.modsString()}"
        send(cs, message)

        #[PROTOCOL 3] send mods to the server
        mods_string = ':'.join(mods).replace("&", ":")
        message = f":>>MODSOTHER:{sender.client.username}:{len(mods)}:{mods_string}"
        if len(mods) > 0 and client_sockets[sender.client.room.host].client.protocolVersion >= 3:
            send(sender.client.room.host, message)

    #leaving session
    if tag == "LEAVE" and sender.client.auth and sender.client.joined and sender.client.room.name == tag_value:
        if sender.client.room.host == cs:
            #destroy the session, sending messages inside the function
            deleteRoom(sender.client.room)
        else:
            message = f":>>KICK:{sender.client.room.name}:{sender.client.username}"
            broadcast(sender.client.room.players, message)
            sender.client.room.leave(cs)
            sender.client.room.resetPlayersReady()
            sender.client.joined = False
            logging.info(f"[R {sender.client.room.name}] {sender.client.username} left")
            updateStatus(sender.client.room)
        updateRooms()

    #[PROTOCOL 3]
    if tag == "KICK" and sender.client.auth and sender.client.joined and sender.client.room.host == cs:
        for pl in sender.client.room.players:
            if pl == sender.client.room.host:
                continue

            if client_sockets[pl].client.username == tag_value:
                message = f":>>KICK:{sender.client.room.name}:{client_sockets[pl].client.username}"
                broadcast(sender.client.room.players, message)
                sender.client.room.leave(pl)
                client_sockets[pl].client.joined = False
                logging.info(f"[R {sender.client.room.name}] {client_sockets[pl].client.username} was kicked")
                updateStatus(sender.client.room)
                startRoomIfReady(sender.client.room)
                updateRooms() 
                break

    if tag == "READY" and sender.client.auth and sender.client.joined and sender.client.room.name == tag_value:
        sender.client.ready = not sender.client.ready
        updateStatus(sender.client.room)

        #for old versions of protocol we can start game by host ready
        if sender.client.protocolVersion < 3 and sender.client.room.host == cs:
            startRoom(sender.client.room)
            updateRooms()
        else:
            if startRoomIfReady(sender.client.room):
                updateRooms()

    #[PROTOCOL 3]
    if tag == "FORCESTART" and sender.client.auth and sender.client.joined and sender.client.room.name == tag_value and sender.client.room.host == cs:
        startRoom(sender.client.room)
        updateRooms()
        STATS["sessions"] += 1

    #manual system command
    if tag == "ROOT" and sender.client.auth:
        logging.warning(f"[!] ROOT from {sender.address} {sender.client.username}: {tag_value}")
        if tag_value in STATS.keys():
            message = f":>>ERROR:Uknown command"
            if isinstance(STATS[tag_value], set):
                message = f":>>MSG:{SYSUSER}:{len(STATS[tag_value])}"
            else:
                message = f":>>MSG:{SYSUSER}:{STATS[tag_value]}"
            send(cs, message)

    #manual user command
    if tag == "HERE" and sender.client.auth:
        logging.info(f"[*] HERE from {sender.address} {sender.client.username}: {tag_value}")
        if sender.client.protocolVersion >= 4:
            sendUsers(cs)
        else:
            targetClients = [i for i in client_sockets.keys() if client_sockets[i].isLobby()]
            message = f":>>MSG:{SYSUSER}:People in lobby"
        
            for cl in targetClients:
                message += f"\n{client_sockets[cl].client.username}"
                if client_sockets[cl].client.joined:
                    message += f"[room {client_sockets[cl].client.room.name}]"
            send(cs, message)

    #[PROTOCOL 4] healthcheck
    if tag == "ALIVE" and sender.client.auth:
        sender.client.timer = HEALTHCHECK_TIMER

    dispatch(cs, sender, (_nextTag[1] + _nextTag[2]).encode())


def listen_for_client(cs):
    """
    This function keep listening for a message from `cs` socket
    Whenever a message is received, broadcast it to all other connected clients
    """
    while True:
        try:
            # keep listening for a message from `cs` socket
            if client_sockets[cs].isPipe() and client_sockets[cs].client.auth:
                msg = cs.recv(4096)
            else:
                msg = receive_packed(cs)

            if msg == None or msg == b'':
                handleDisconnection(cs)
                return

            dispatch(cs, client_sockets[cs], msg)

        except Exception as e:
            # client no longer connected
            logging.error(f"[!] Error: {e}")
            handleDisconnection(cs)
            return


timer = Thread(target=timer_for_clients)
timer.daemon = True
timer.start()

while True:
    # we keep listening for new connections all the time
    client_socket, client_address = s.accept()
    logging.info(f"[+] {client_address} connected.")
    STATS["uniques"].add(client_address[0])
    STATS["logins"] += 1
    # add the new connected client to connected sockets
    client_sockets[client_socket] = Sender()
    client_sockets[client_socket].address = client_address
    # start a new thread that listens for each client's messages
    t = Thread(target=listen_for_client, args=(client_socket,))
    # make the thread daemon so it ends whenever the main thread ends
    t.daemon = True
    # start the thread
    t.start()

 # close client sockets
for cs in client_sockets:
    cs.close()
# close server socket
s.close()