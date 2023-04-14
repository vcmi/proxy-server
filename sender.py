import socket
import struct
from client import Client, ClientLobby, ClientPipe

BUFFER_SIZE = 4096

class Sender:
    address: str #full client address
    client: Client
    sock: socket

    def __init__(self, client_socket: socket) -> None:
        self.client = None
        self.sock = client_socket
        pass

    def isLobby(self) -> bool:
        return isinstance(self.client, ClientLobby)

    def isPipe(self) -> bool:
        return isinstance(self.client, ClientPipe)
    
    def receive_all(self, n):
        # Helper function to recv n bytes or return None if EOF is hit
        data = bytearray()
        while len(data) < n:
            packet = self.sock.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        return data
    
    def receive_pack(self):
        # Read message length and unpack it into an integer
        raw_msglen = self.receive_all(4)
        if not raw_msglen:
            return None
        msglen = struct.unpack('<I', raw_msglen)[0]
        # Read the message data
        return self.receive_all(msglen)
    
    def receive_data(self):
        if self.isPipe() and self.client.auth:
            return self.sock.recv(BUFFER_SIZE)
        return self.receive_pack()
    
    def handshake(self, data):
        if not self.client:
            msg = str(data)
            exchangeMessageFlag = False #flag to identify if message exchange was started
            if msg.find("Aiya!") != -1:
                self.client = ClientPipe()
            else:
                self.client = ClientLobby()

        self.client.handshake(data)

        