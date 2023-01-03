# VCMI Proxy Server

The purpose of this program is to connect VCMI users together to allow online multiplayer.

## Quick start

Following snippet will start proxy server so clients can connect to `0.0.0.0:5002`
If server has static IP and/or web address, clients can connect by using this address.
Local clients can connect by `localhost:5002` or `127.0.0.1:5002`
```
cd proxy-server
python3.8 proxyServer.py &
```

To stop server
```
skill python3.8
```

**Note:** _& symbol in the end runs script in detached mode so it will work even after user session was closed._

## Arguments

Program can be started with arguments or without them, full command has following format:

```
python3.8 proxyServer.py logging=info port=5002 capacity=50 healthcheck=30
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
