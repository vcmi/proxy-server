import re, struct
import uuid
from sender import Sender
import logging
from room import Room
from session import Session

SYSUSER = "System" #username from whom system messages will be sent

STATS = {
    "uniques" : set(), #address
    "users" : set(), #usernames
    "logins" : 0, #sockets
    "clients" : 0, #vcmi clients
    "rooms" : 0, #created rooms
    "sessions" : 0, #started sessions
    "connections" : 0 #successful connections
}

class Lobby:
    sessions: list
    rooms: dict
    senders: list

    def __init__(self) -> None:
        self.sessions = []
        self.rooms = {}
        self.senders = []

    def disconnect(self, sender: Sender):
        #cleanup room
        if sender.client.joined and sender.client.room_name in self.rooms.keys():
            r = self.rooms[sender.client.room_name]
            if not r.started:
                if r.host == sender:
                    #destroy the session, sending messages inside the function
                    self.deleteRoom(r)
                else:
                    r.leave(sender)
                    sender.client.joined = False
                    message = f":>>KICK:{sender.client.room_name}:{sender.client.username}"
                    self.broadcast(r.players, message.encode())
                self.updateStatus(r)
                self.updateRooms()
        
        self.senders.remove(sender)
        
        #updating list of users
        for cl in self.senders:
            if cl.isLobby() and cl.client.auth and cl.client.protocolVersion >= 4:
                self.sendUsers(cl)

    #sending message for lobby players
    def send(self, sender: Sender, message: str):
        if sender in self.senders:
            sender.sock.send(message.encode(encoding=sender.client.encoding, errors='replace'))


    def broadcast(self, senders: list, message: str):
        for sender in senders:
            if sender.isLobby() and sender.client.auth:
                self.send(sender, message)


    def sendRooms(self, sender: Sender):
        msg2 = ""
        counter = 0
        for room in self.rooms.values():
            if not room.started:
                msg2 += f":{room.name}:{room.joined}:{room.total}:{room.protected}"
                counter += 1
        msg = f":>>SESSIONS:{counter}{msg2}"

        self.send(sender, msg)

    def sendUsers(self, sender: Sender):
        targetClients = [i for i in self.senders if i.isLobby()]
        msg = f":>>USERS:{len(targetClients)}"
            
        for cl in targetClients:
            msg += f":{cl.client.username}"
        
        self.send(sender, msg)


    def sendCommonInfo(self, sender: Sender):
        if sender.client.protocolVersion >= 4:
            self.sendUsers(sender)

        lobby_users = [i for i in self.senders if i.isLobby() and i.client.auth]
        play_users = [i for i in self.senders if i.isPipe()]
        msg = f":>>MSG:{SYSUSER}:Here available {len(lobby_users) - 1} users, currently playing {len(play_users)}"
        if sender.client.protocolVersion < 4:
            msg += "\n Send <HERE> to see people names in the chat"
        msg += "\n Send direct message by typing @username"
        self.send(sender, msg)


    def updateRooms(self):
        for s in self.senders:
            if s.isLobby():
                self.sendRooms(s)


    def deleteRoom(self, room_name: str):
        msg = f":>>KICK:{room_name}"
        for player in self.rooms[room_name].players:
            player.client.joined = False
            msg2 = msg + f":{player.client.username}"
            self.send(player, msg2)
        
        logging.info(f"[R {room_name}]: Destroying room")
        self.rooms.pop(room_name)


    def updateStatus(self, room: Room):
        msg = f":>>STATUS:{room.joined}"
        for player in room.players:
            msg += f":{player.client.username}:{player.client.ready}"
        self.broadcast(room.players, msg)


    def startRoom(self, room: Room):
        STATS["sessions"] += 1
        room.started = True
        session = Session()
        session.name = room.name
        self.sessions.append(session)
        logging.info(f"[S {session.name}] Starting for {room.joined} players")
        session.host_uuid = str(uuid.uuid4())
        hostMessage = f":>>HOST:{session.host_uuid}:{room.joined - 1}" #one client will be connected locally
        logging.debug(f"---- host: {session.host_uuid} connections {room.joined - 1}")
        #host message must be before start message
        self.send(room.host, hostMessage)

        for player in room.players:
            _uuid = str(uuid.uuid4())
            session.clients_uuid.append(_uuid)
            msg = f":>>START:{_uuid}"
            self.send(player, msg)

        for player in room.players:
            #remove this connection
            player.sock.close()
            self.senders.remove(player)

        #this room shall not exist anymore
        logging.info(f"[R {room.name}] Exit room as session {session.name} was started")
        self.rooms.pop(room.name)

        
    def startRoomIfReady(self, room: Room) -> bool:
        if room.joined > 1 and room.verifyForStart():
            self.startRoom(room)
            return True
        
        return False


    def messageTarget(self, s: str):
        ttuple = s.partition("@")
        if ttuple[0] != "" or ttuple[1] != "@":
            return ("", s)

        ttuple = ttuple[2].partition(" ")
        if ttuple[0] == "":

            return ("", s)

        return (ttuple[0], ttuple[2])    


    def dispatch(self, sender: Sender, arr: bytes):
        
        msg = arr.decode(encoding=sender.client.encoding, errors='replace')
        _open = msg.partition('<')
        _close = _open[2].partition('>')
        if _open[1] == '' or _open[2] == '' or _close[0] == '' or _close[1] == '':
            logging.error(f"[!] Incorrect message from {sender.address}: {msg}")
            return

        _nextTag = _close[2].partition('<')
        tag = _close[0]
        tag_value = _nextTag[0]

        #greetings to the server
        if tag == "GREETINGS":
            if sender.client.auth:
                logging.critical(f"[*] Greetings from authorized user {sender.client.username} {sender.address}")
                self.send(sender, ":>>ERROR:User already authorized")
                return

            if len(tag_value) < 3:
                logging.warning(f"[!] Incorrect username from {sender.address}: {tag_value}")
                self.send(sender, f":>>ERROR:Too short username {tag_value}")
                return

            if tag_value == SYSUSER or tag_value == "all" or len(tag_value.split(" ")) > 1:
                logging.warning(f"[!] Incorrect username from {sender.address}: {tag_value}")
                self.send(sender, f":>>ERROR:Invalid username")
                return

            for user in self.senders:
                if user.isLobby() and user.client.username == tag_value:
                    logging.warning(f"[!] Client username already exist {sender.address}: {tag_value}")
                    self.send(sender, f":>>ERROR:Can't connect with the name {tag_value}. This login is already occpupied")
                    return
            
            logging.info(f"[*] {sender.address} autorized as {tag_value}")
            STATS["users"].add(tag_value)
            sender.client.username = tag_value
            #sending info that someone here before authorizing - to not send it to itself
            targetClientsOld = [i for i in self.senders if i.isLobby() and i.client.protocolVersion < 4]
            message = f":>>MSG:{SYSUSER}:{sender.client.username} is here"
            self.broadcast(targetClientsOld, message)
            #updating list of users
            for cl in self.senders:
                if cl.isLobby() and cl.client.protocolVersion >= 4:
                    self.sendUsers(cl)
            #authorizing user
            sender.client.auth = True
            self.sendRooms(sender)
            self.sendCommonInfo(sender)

        #VCMI version received
        if tag == "VER" and sender.client.auth:
            logging.info(f"[*] User {sender.client.username} has version {tag_value}")
            sender.client.vcmiversion = tag_value

        #message received
        if tag == "MSG" and sender.client.auth:
            target = self.messageTarget(tag_value)
            targetClients = [i for i in self.senders if i.isLobby()]
            if sender.client.joined and target[0] != "all":
                targetClients = self.rooms[sender.client.room_name].players #send message only to players in the room
            
            if target[0] != "" and target[0] != "all":
                for cl in targetClients:
                    if cl.client.username == target[0]:
                        targetClients = [cl, sender]

            message = f":>>MSG:{sender.client.username}:{target[1]}"
            self.broadcast(targetClients, message)

        #new room
        if tag == "NEW" and sender.client.auth and not sender.client.joined:
            if tag_value in self.rooms:
                #refuse creating game
                message = f":>>ERROR:Cannot create session with name {tag_value}, session with this name already exists"
                self.send(sender, message)
                return

            if tag_value == "" or tag_value.startswith(" ") or len(tag_value) < 3:
                #refuse creating game
                message = f":>>ERROR:Cannot create session with invalid name {tag_value}"
                self.send(sender, message)
                return
            
            self.rooms[tag_value] = Room(sender, tag_value)
            sender.client.joined = True
            sender.client.ready = False
            sender.client.room_name = tag_value
            logging.info(f"[R {tag_value}]: room created")
            STATS["rooms"] += 1

        #set password for the session
        if tag == "PSWD" and sender.client.auth and sender.client.joined:
            r = self.rooms[sender.client.room_name]
            if r.host == sender:
                r.password = tag_value
                r.protected = bool(tag_value != "")
            else:
                if not r.protected or r.password == tag_value:
                    r.join(sender)
                    message = f":>>JOIN:{r.name}:{sender.client.username}"
                    logging.info(f"[R {r.name}] {sender.client.username} joined")
                    self.broadcast(r.players, message)
                    self.updateStatus(r)
                    self.updateRooms()
                    #send instructions to player
                    message = f":>>MSG:{SYSUSER}:You are in the room chat. To send message to global chat, type @all"
                    self.send(sender, message)
                    #verify version and send warning
                    host_sender = r.host
                    if sender.client.vcmiversion != host_sender.client.vcmiversion:
                        message = f":>>MSG:{SYSUSER}:Your VCMI version {sender.client.vcmiversion} differs from host version {host_sender.client.vcmiversion}, which may cause problems"
                        self.send(sender, message)

                else:
                    sender.client.joined = False
                    message = f":>>ERROR:Incorrect password"
                    self.send(sender, message)
                    return

        #set amount of players to the new room
        if tag == "COUNT" and sender.client.auth and sender.client.joined:
            r = self.rooms[sender.client.room_name]
            if r.host == sender:
                if r.total != 1:
                    #refuse changing amount of players
                    message = f":>>ERROR:Changing amount of players is not possible for existing session"
                    self.send(sender, message)
                    return

                if int(tag_value) < 2 or int(tag_value) > 8:
                    #refuse and cleanup room
                    self.deleteRoom(r.name)
                    message = f":>>ERROR:Cannot create room with invalid amount of players"
                    self.send(sender, message)
                    return

                r.total = int(tag_value)
                message = f":>>CREATED:{r.name}"
                self.send(sender, message)
                #now room is ready to be broadcasted
                message = f":>>JOIN:{r.name}:{sender.client.username}"
                self.send(sender, message)
                self.updateStatus(r)
                self.updateRooms()
                #send instructions to player
                message = f":>>MSG:{SYSUSER}:You are in the room chat. To send message to global chat, type @all"
                self.send(sender, message)

        #join session
        if tag == "JOIN" and sender.client.auth and not sender.client.joined:
            if tag_value not in self.rooms:
                message = f":>>ERROR:Room with name {tag_value} doesn't exist"
                self.send(sender, message)
                return
            
            if self.rooms[tag_value].joined >= self.rooms[tag_value].total:
                message = f":>>ERROR:Room {tag_value} is full"
                self.send(sender, message)
                return

            if self.rooms[tag_value].started:
                message = f":>>ERROR:Session {tag_value} is started"
                self.send(sender, message)
                return

            sender.client.joined = True
            sender.client.ready = False
            sender.client.room_name = tag_value

        if tag == "PSWD" and sender.client.auth and sender.client.joined:
            r = self.rooms[sender.client.room_name]


        #[PROTOCOL 4] set game mode
        if tag == "HOSTMODE" and sender.client.auth and sender.client.joined:
            r = self.rooms[sender.client.room_name]
            #checks for permissions
            if r.host != sender:
                message = ":>>ERROR:Insuficcient permissions"
                self.send(sender, message)
                return

            #update game mode for everybody
            r.gamemode = int(tag_value)
            message = f":>>GAMEMODE:{r.gamemode}"
            self.broadcast(r.players, message)


        #[PROTOCOL 2] receive list of mods
        if tag == "MODS" and sender.client.auth and sender.client.joined:
            mods = tag_value.split(";") #list of modname&modverion
            r = self.rooms[sender.client.room_name]

            if r.host == sender:
                #set mods
                for m in mods:
                    mp = m.partition("&")
                    r.mods[mp[0]] = mp[2]
            
            #send mods
            message = f":>>MODS:{r.modsString()}"
            self.send(sender, message)

            #[PROTOCOL 3] send mods to the server
            mods_string = ':'.join(mods).replace("&", ":")
            message = f":>>MODSOTHER:{sender.client.username}:{len(mods)}:{mods_string}"
            if len(mods) > 0 and r.host.client.protocolVersion >= 3:
                self.send(r.host, message)

        #leaving session
        if tag == "LEAVE" and sender.client.auth and sender.client.joined and sender.client.room_name == tag_value:
            r = self.rooms[sender.client.room_name]
            if r.host == sender:
                #destroy the session, sending messages inside the function
                self.deleteRoom(r.name)
            else:
                message = f":>>KICK:{r.name}:{sender.client.username}"
                self.broadcast(r.players, message)
                r.leave(sender)
                r.resetPlayersReady()
                sender.client.joined = False
                logging.info(f"[R {r.name}] {sender.client.username} left")
                self.updateStatus(r)
            self.updateRooms()

        #[PROTOCOL 3]
        if tag == "KICK" and sender.client.auth and sender.client.joined:
            r = self.rooms[sender.client.room_name]
            #checks for permissions
            if r.host != sender:
                message = ":>>ERROR:Insuficcient permissions"
                self.send(sender, message)
                return
            
            for pl in r.players:
                if pl == r.host:
                    continue

                if pl.client.username == tag_value:
                    message = f":>>KICK:{r.name}:{pl.client.username}"
                    self.broadcast(r.players, message)
                    r.leave(pl)
                    pl.client.joined = False
                    logging.info(f"[R {r.name}] {pl.client.username} was kicked")
                    self.updateStatus(r)
                    self.startRoomIfReady(r)
                    self.updateRooms() 
                    break

        if tag == "READY" and sender.client.auth and sender.client.joined and sender.client.room_name == tag_value:
            sender.client.ready = not sender.client.ready
            r = self.rooms[sender.client.room_name]
            self.updateStatus(r)

            #for old versions of protocol we can start game by host ready
            if sender.client.protocolVersion < 3 and r.host == sender:
                self.startRoom(r)
                self.updateRooms()
            else:
                if self.startRoomIfReady(r):
                    self.updateRooms()

        #[PROTOCOL 3]
        if tag == "FORCESTART" and sender.client.auth and sender.client.joined and sender.client.room_name == tag_value:
            r = self.rooms[sender.client.room_name]
            if r.host != sender:
                message = ":>>ERROR:Insuficcient permissions"
                self.send(sender, message)
                return
            
            self.startRoom(r)
            self.updateRooms()
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
                self.send(sender, message)

        #manual user command
        if tag == "HERE" and sender.client.auth:
            logging.info(f"[*] HERE from {sender.address} {sender.client.username}: {tag_value}")
            if sender.client.protocolVersion >= 4:
                self.sendUsers(sender)
            else:
                targetClients = [i for i in self.senders if i.isLobby()]
                message = f":>>MSG:{SYSUSER}:People in lobby"
            
                for cl in targetClients:
                    message += f"\n{cl.client.username}"
                    if cl.client.joined:
                        message += f"[room {cl.client.room_name}]"
                self.send(sender, message)

        #[PROTOCOL 4, DEPRECATED] healthcheck
        if tag == "ALIVE" and sender.client.auth:
            pass

        arr = (_nextTag[1] + _nextTag[2]).encode()
        if arr and len(arr) > 0:
            self.dispatch(sender, arr)