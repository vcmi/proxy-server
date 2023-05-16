# VCMI Proxy Server

The purpose of this program is to connect VCMI users together to allow online multiplayer.

## Quick start

Following snippet will start proxy server so clients can connect to `0.0.0.0:5002`
If server has static IP and/or web address, clients can connect by using this address.
Local clients can connect by `localhost:5002` or `127.0.0.1:5002`
```
cd proxyServer
python3.8 Server.py &
```

To stop server
```
skill python3.8
```

**Note:** _& symbol in the end runs script in detached mode so it will work even after user session was closed._

## Arguments

Program can be started with arguments or without them, full command has following format:

```
python3.8 server.py logging=info port=5002 capacity=50 healthcheck=30
```
In example above all arguments have their default values.

### Detailed description of arguments

- `logging` level of logging event to be written into file. Possible options are:
  - `debug` - if this level activated, debug log events will be written into `proxyServer_debug.log` file
  - `info`
  - `warning`
  - `error`
  - `critical`
- `port` port where clients should connect
- `capacity` maximum allowed amount of clients to be connected
- `healthcheck` time in seconds. When is passed, server requests health status of clients (starting form protocol 4)

## Lobby protocol description

### Packing

Each message has a packet structure, which means that it has infomation about structure size.
First 4 bytes stand for structure size (in bytes) then server waits for all bytes to be received.

### Handshaking

When first pack is obtained server determines whether it lobby connection or game connection (pipe)
If structure has a string "Ayia!" then it's game connection. Otherwise lobby connection is assumed.

Since connection type is determined, than appropriate handshaking is expected.
- For Lobby coneection
  - protocol version - one byte
  - string encoding. Check one byte - if zero, then `utf-8` is assumed. If non-zero, this byte stands for encoding name size. Then next bytes are read to get encoding name. Examples: `5utf-8`, `6cp1251`

- For Pipe connection
  - Fist struct is always `Ayia!`
  - Second struct is either `client` or `server`
  - Third struct is stands for uuid `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### Lobby protocol

Lobby protocol has different format for client and server messages.
This file describes only server protocol. See vcmi documentation for client protocol

Overall format of server protocol: `<COMMAND>ARGUMENT(s)`

- <GREETINGS>username
  - expected to be first command. Autorizes client in lobby
- <VER>version
  - full vcmi version
- <MSG>message
  - ask server to broadcast message to other players. Can have target like @username or @all to send to everyone
- <NEW>name
  - ask server to create new room with name specified. Client will be joined to this room as host.
- <PSWD>password
  - if client is a host of room, new room password will be set. Otherwise, password will be checked before joining to the room
- <COUNT>players
  - sets total amount of players to be set for new room
- <JOIN>name
  - asks server to join player to the room with name specified
- <HOSTMODE>mode
  - asks server to set room into mode specified (must be integer) and broadcast it
- <MODS>mods
  - notifies server about mods client has. Mods has following format: `mod1_name&mod1_version;mod2_name&mod2_version;...`
- <LEAVE>name
  - ask server to leave room with name specified
  - If client is a host for that room, then room will be destroyed
- <KICK>username
  - ask sever to kick player with username specified from room which current client is joined
  - client must be room host
- <READY>name
  - notifies server about client reasiness for room name specified. Client must be joined to this room
- <FORCESTART>name
  - asks server to start session for room with name specified immediately.
  - This command used to ensure backward compatibility with older clients who cannot send `READY` command
- <ROOT>field
  - debug command to be typed manually. Used to obtain statistic from the server. See `lobby.py` for information about fields
- <ALIVE>any
  - obsolete command, unused. Server ignores it.
