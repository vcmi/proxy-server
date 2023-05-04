from sender import Sender

#game modes
NEW_GAME = 0
LOAD_GAME = 1

class Room:
    total = 1 # total amount of players
    joined = 0 # amount of players joined to the session
    password = "" # password to connect
    protected = False # if True, password is required to join to the session
    name: str # name of room
    host: Sender # player socket who created the room
    players = [] # list of clients of players, joined to the session
    mods = {} # modname - version pairs of enabled by host mods
    gamemode = NEW_GAME # game
    started = False

    def __init__(self, host: Sender, name: str) -> None:
        self.name = name
        self.host = host
        self.players = [host]
        self.joined = 1
        self.gamemode = NEW_GAME
        self.mods = {}

    def isJoined(self, player: Sender) -> bool:
        return player in self.players

    def join(self, player: Sender):
        if not self.isJoined(player) and self.joined < self.total:
            self.players.append(player)
            self.joined += 1

    def leave(self, player: Sender):
        if not self.isJoined(player) or player == self.host or player not in self.players:
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
            if not pl.client.ready:
                return False
        
        return True
    
    def resetPlayersReady(self):
        for pl in self.players:
            pl.client.ready = False

