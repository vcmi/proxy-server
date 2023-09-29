import logging
import socket
import sys
from multiprocessing import Process
from threading import Thread, Timer
from sender import Sender
from lobby import Lobby, STATS

# Major version: increase if backword compatibility with old protocols is not supported
# Minor version: increase if new functional changes appeared, more functionality in the protocol
# Patch version: increase for any internal change/bugfix, not related to vcmi functionality
PROXYSERVER_VERSION = "0.6.1"

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

# command line arcgunents parsing and support
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
            print(f"Cannot listen port 0, continue with default {SERVER_PORT}")
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

def removeSession(session):
    session.timer = None
    if len(session.connections) == 0:
        lobby.sessions.remove(session)

def handle_disconnection(sender: Sender):
    """
    Handles disconnnection of socket in current thread.
    Called in case of any socket method throws
    """
    try:
        if sender.isLobby():
            lobby.disconnect(sender)
        if sender.isPipe():
            if sender.client.session:
                sender.client.session.removeConnection(sender.sock)
                try:
                    if len(sender.client.session.connections) == 0:
                        if sender.client.session.timer != None:
                            sender.client.session.timer.cancel()
                        sender.client.session.timer = Timer(300, removeSession, args = [sender.client.session])
                        sender.client.session.timer.start()
                        
                    lobby.senders.remove(sender)
                except ValueError as e:
                    logging.warning(f"[*] Exception during disconnecion: {e}")

    except Exception as e:
        logging.critical(f"[!] Unhandled execption: {e}")
    
    try:
        sender.sock.close()
        if sender in lobby.senders:
            lobby.senders.remove(sender)
    except Exception as e:
        logging.critical(f"[!] Cannot close socket: {e}")


def listen_for_client(sender: Sender):
    """
    This function keep listening for a message from `cs` socket
    Whenever a message is received, broadcast it to all other connected clients
    """
    try:
        while True:
            # keep listening for a message from `cs` socket
            msg = sender.receive_data()

            if msg == None or msg == b'':
                break # receiving empty message means that TCP connection is stopped

            if not sender.client or not sender.client.auth:
                # client isn't identified yet
                if sender.handshake(msg) == False:
                    if sender.client: # partially authorized client - we can send an error message
                        logging.error(f"[!] {sender.client.status}")
                        if sender.isLobby():
                            lobby.send(sender, f":>>ERROR:{sender.client.status}")
                    break # handle disconnection if handshakign is unsuccessfull

                # this codeblock if needed to properly support game connection after handshaking
                # need to do this only once, which is ensured by setting `auth`` to true
                if sender.isPipe() and sender.client.auth:
                    #read missing byte
                    sender.client.prevmessages.append(sender.sock.recv(1))
                    msg = b'' #reset message to prevent its duplicating
                    
                    # search for session and register connection
                    for session in lobby.sessions:
                        if sender.client.testForSession(session):
                            sender.client.session = session
                            session.addConnection(sender.sock, sender.client.isServer(), sender.client.prevmessages)
                            break

                    if sender.client.session and sender.client.session.validPipe(sender.sock):
                        # session has been found, send all pending data to connected client
                        if len(sender.client.session.pipeMessages(sender.sock)):
                            sender.client.session.forward_data(sender.sock, b''.join(sender.client.session.pipeMessages(sender.sock)))
                        
                        # send all received data to opposite client
                        # after this step data exchange is finally started
                        opposite = sender.client.session.getPipe(sender.sock)
                        if len(sender.client.session.pipeMessages(opposite)):
                            sender.client.session.forward_data(opposite, b''.join(sender.client.session.pipeMessages(opposite)))
                    
                    BUFFER_SIZE = 1024 * 1024  # Example buffer size of 1MB
                    sender.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUFFER_SIZE)
                    sender.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUFFER_SIZE)
                    sender.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            
            if sender.isPipe():
                if not sender.client.auth:
                    continue #continue handshaking

                if not sender.client.session:
                    break #cannot connect player - break connection

                if not sender.client.session.validPipe(sender.sock):
                    # opposite client still not connected - wait for them and store all pending messages
                    if msg != b'':
                        sender.client.session.pipeMessages(sender.sock).append(msg)
                    continue

                # connection established - just forward data
                sender.client.session.forward_data(sender.sock, msg)


            if sender.isLobby():
                # for lobby connection dispatch lobby message
                lobby.dispatch(sender, msg)

    except Exception as e:
        # client no longer connected
        logging.error(f"[!] Error: {e}")
        print(f"[!] Error: {e}")
        
    finally:
        handle_disconnection(sender)


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