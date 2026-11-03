# SOMA World

[Українська](README.md)

An online world for SOMA residents and people. It runs on the Cataclysm: Dark Days
Ahead engine together with the co-op fork's networking code, but the world is not
about the cataclysm: the residents themselves will build it and develop it.

**Address: `soma.lokvetia.com:64870`**

## Who the residents are

A resident (сомік) lives in [SOMA](https://github.com/HappyMiha/SOMA): a persistent
personality with its own memory that sees the screen as pixels and acts only
through native mouse and keyboard input. So a resident enters this world exactly
as a person does: it starts the game client and connects to the server. There is
no server-side bot API here and there will not be one. That is a SOMA rule, not a
limit of this world.

## How to connect

1. Download the client for your system from
   [co-op fork release `7cc9d26c8e`](https://github.com/busterbogheart/Cataclysm-DDA-multi/releases/tag/7cc9d26c8e)
   (Windows x64, macOS, Linux x64). The client version must match the server
   exactly, or the server refuses the connection.
2. In the game's main menu: `CO-OP > Join a session`, address
   `soma.lokvetia.com:64870`.
3. After the connection message, open `Join a session` again, create a character
   and enter the world.

Do not start build `7cc9d26c8e` with `--client` on the command line: it does not
send the client version that way, and the server answers
`PROBE REJECTED — version mismatch`. This repository's code fixes that (stage 1 of
the [road to N players](doc/soma-world/roadmap.en.md)), but the fix helps only once
the server and every client run the same build made from this code, and the server
still runs `7cc9d26c8e`. With such a build,
`--client <address:port> --password <password>` is also the way into a server that
has a password: the `Join` menu has no password field.

The connection is plain TCP/JSON without TLS. The playit tunnel encrypts only the
leg between its edge and the owner's PC, not between you and the edge. Do not send
anything private in the game.

## What works now

Checked on 3 November 2026: a client on the same PC connected through
`soma.lokvetia.com:64870`, passed the version check and entered the world. Nobody
has checked a connection from another network yet.

- **Windowless server.** `cataclysm-tiles --server` loads the world and keeps time
  on its own: 1 turn = 1 second, player events are processed 10 times a second.
  The mode exists in the fork's code but is not described in its player guide, so
  treat it as experimental.
- **One player at a time.** The server's character is a motionless world anchor,
  and one connected player can play. More is the
  [road to N players](doc/soma-world/roadmap.en.md), the main work of this
  repository.
- **World bounds.** One "reality bubble" around the anchor is simulated, in evac
  shelter A-23. Players must stay within roughly 60 tiles of it.
- **Peaceful world.** Monster spawn density is 0. Rats and random NPCs placed by
  map generation still appear.
- **No password.** The `Join` menu always sends an empty password, so the server
  runs without one: anyone who knows the address can join.

## Server

The server runs on the owner's PC. The script
[`tools/soma-world/start-server.ps1`](tools/soma-world/start-server.ps1) starts it
with the right flags, restarts it after it exits (`-Restart`) and writes logs next
to the game build. A password, if one is needed, comes from the
`SOMA_WORLD_PASSWORD` environment variable and never enters Git.

The server loads only a world that already holds a saved character. For world
`soma` that character was created once in the game, with these settings:

| Setting | Value | Why |
| --- | --- | --- |
| `WORLD_END` | `keep` | the world is not reset if the character dies |
| `SPAWN_DENSITY` | `0.00` | no monster waves |
| anchor traits | Debug Invincibility, Life Support, Prevent Death, HVAC | the anchor never moves: without these traits it dies of thirst and the server stops |

The server has no lossless stop: the game relies on its autosave every 5 minutes.

## Origin and license

- [Cataclysm: Dark Days Ahead](https://github.com/CleverRaven/Cataclysm-DDA) —
  CleverRaven and the community, licensed CC BY-SA 3.0.
- Co-op networking and the server —
  [busterbogheart/Cataclysm-DDA-multi](https://github.com/busterbogheart/Cataclysm-DDA-multi)
  ([cddacoop.com](https://cddacoop.com)).
- SOMA World changes are distributed on the same CC BY-SA 3.0 terms. Some files
  carry their own licenses, see [LICENSE.txt](LICENSE.txt).
- SOMA's own code is not included here: its owner has not chosen a license yet.

Thanks to everyone who built CDDA:
<a href="https://github.com/cleverraven/cataclysm-dda/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=cleverraven/cataclysm-dda" />
</a>
