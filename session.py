import socket


class GameConnection:
    server: socket # socket to vcmiserver
    client: socket # socket to vcmiclient
    serverInit = False # if vcmiserver already connected
    clientInit = False # if vcmiclient already connected

    def __init__(self) -> None:
        self.server = None
        self.client = None
        pass


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
