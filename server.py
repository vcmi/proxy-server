import logging
import socket
import sys
from multiprocessing import Process
from threading import Thread
from sender import Sender
from lobby import Lobby, STATS


PROXYSERVER_VERSION = "0.5.0"

LOG_LEVEL = logging.INFO
LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL
}

# server's IP address
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5002 # port we want to use

MAX_CONNECTIONS = 50

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


#logging
logHandlerHighlevel = logging.FileHandler('proxyServer.log')
logHandlerHighlevel.setLevel(logging.INFO)

logHandlerLowlevel = logging.FileHandler('proxyServer_debug.log')
logHandlerLowlevel.setLevel(logging.DEBUG)

handlers = [logHandlerHighlevel]
if LOG_LEVEL == logging.DEBUG:
    handlers.append(logHandlerLowlevel)

logging.basicConfig(handlers=handlers, level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S')



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

lobby = Lobby()

def listen_for_client(sender: Sender):
    """
    This function keep listening for a message from `cs` socket
    Whenever a message is received, broadcast it to all other connected clients
    """
    while True:
        try:
            # keep listening for a message from `cs` socket
            if sender.isPipe() and sender.client.auth:
                msg = sender.sock.recv(4096)
            else:
                msg = sender.receive_pack()

            if msg == None or msg == b'':
                #handleDisconnection(cs)
                return

            if not sender.client or sender.isLobby():
                lobby.dispatch(sender, msg)

        except Exception as e:
            # client no longer connected
            logging.error(f"[!] Error: {e}")
            #handleDisconnection(cs)
            return


while True:
    # we keep listening for new connections all the time
    client_socket, client_address = s.accept()
    logging.info(f"[+] {client_address} connected.")
    STATS["uniques"].add(client_address[0])
    STATS["logins"] += 1
    # add the new connected client to connected sockets
    sender = Sender(client_socket)
    sender.address = client_address
    lobby.senders.append(sender)

    # start a new thread that listens for each client's messages
    t = Thread(target=listen_for_client, args=(sender,))
    # make the thread daemon so it ends whenever the main thread ends
    t.daemon = True
    # start the thread
    t.start()