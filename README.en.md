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

1. Download the client from
   [SOMA World release `24802636a6`](https://github.com/HappyMiha/soma-world/releases/tag/soma-24802636a6)
   (Windows x64 only for now) and unpack it. The client version must match the
   server exactly, or the server refuses the connection.
2. Run `cataclysm-tiles.exe`. The build is unsigned, so Windows SmartScreen may
   stop it: "More info", then "Run anyway".
3. In the game's main menu: `CO-OP > Join a session`, address
   `soma.lokvetia.com:64870`.
4. After the connection message press any key: the character menu opens by
   itself, and there is no need to choose `Join a session` again. Choose
   `New character`, and `Load existing character` next time.
5. The bar at the bottom of the screen starts with `host: Tyesha`. That is the
   host, the server's anchor character, not you. Your own name is on the character
   sheet (`@`).

Step-by-step instructions covering every window are in the archive next to
`cataclysm-tiles.exe`, in `HOW-TO-JOIN.txt`; its source is
[`tools/soma-world/release`](tools/soma-world/release).

The command line works too: `--client soma.lokvetia.com:64870`. The same, with
`--password <password>`, is the way into a server that has a password: the `Join`
menu has no password field.

The connection is plain TCP/JSON without TLS. The playit tunnel encrypts only the
leg between its edge and the owner's PC, not between you and the edge. Do not send
anything private in the game.

## What works now

Checked on 4 November 2026. Build `24802636a6`, which runs now, differs from
`9f50a6140a` only in how the server takes client packets (quotes and other
characters in names, packets it cannot accept) and by the `host:` label on the bar
at the bottom of the screen. After the deploy a scripted client
passed the version check through `soma.lokvetia.com:64870`, entered the world, did
nothing for 90 seconds (the server did not crash), asked for a save and left; the
world was written to disk. A resident on another PC played in the world through
the same address for more than five hours with the `9f50a6140a` GUI client.
Joining with the `24802636a6` GUI client has not been checked yet.

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
- **The world is saved.** Autosave runs every 5 minutes or 50 turns, and the world
  is also written when a player asks for a save and when a player leaves. While a
  connected player thinks, the world stands still, because the game is turn-based,
  so there is nothing to save then.
- **Peaceful world.** Monster spawn density is 0. Rats and random NPCs placed by
  map generation still appear.
- **No password.** The `Join` menu always sends an empty password, so the server
  runs without one: anyone who knows the address can join.

## Server

The server runs on the owner's PC as the Windows Task Scheduler task "SOMA World
server". It starts 30 seconds after the owner signs in and keeps the server alive.
The local port is 38080; the playit tunnel leads there from
`soma.lokvetia.com:64870`. Port 8080 is unsuitable: on this PC it belongs to the
Temporal UI of Lokvetia Core.

Scripts in [`tools/soma-world`](tools/soma-world):

| Script | What it does |
| --- | --- |
| `install-autostart.ps1` | registers the task: no stored password, runs only while the owner is signed in, no time limit |
| `start-server.ps1` | starts the server and supervises it: restarts it after a crash or a hang but not after a requested stop, stops a hang or a crash dialog, refuses to start while anything else uses the world's saves |
| `stop-server.ps1` | asks the server to save the world and exit, then stops the task, the supervising loop and anything still running |
| `release/package-release.ps1` | packs the client folder into the release archive: adds `HOW-TO-JOIN.txt` and the `README.txt` header and leaves out `data\cache`, because the game takes a cache written by another build for stale and shows a message for every file |

Start it again with `Start-ScheduledTask -TaskName 'SOMA World server'`. A
password, if one is needed, comes from the `SOMA_WORLD_PASSWORD` environment
variable and never enters Git.

The server build is in `game\SomaWorld-24802636a6`. The previous one,
`game\SomaWorld-8352fc80c6`, stays for a rollback: stop the server, copy
`save\soma` from the current build into it, then `install-autostart.ps1 -GameDir
<folder>` and `Start-ScheduledTask`. Players then need a client of that build
again. Logs are in `server-logs` next to the game build:
`server-<time>.out.log` (the game) and `wrapper.log` (the supervisor). The game
also appends to `%USERPROFILE%\cdda-mp-server.log`, which every build of the fork
shares.

After a Windows Update restart, Windows signs the owner back in by itself, so the
server returns. After a shutdown or a sign-out it returns only with the next
sign-in.

The server loads only a world that already holds a saved character. For world
`soma` that character was created once in the game, with these settings:

| Setting | Value | Why |
| --- | --- | --- |
| `WORLD_END` | `keep` | the world is not reset if the character dies |
| `SPAWN_DENSITY` | `0.00` | no monster waves |
| anchor traits | Debug Invincibility, Life Support, Prevent Death, HVAC | the anchor never moves: without these traits it dies of thirst and the server stops |

### Stopping without losses

A server built from this repository's code saves the world and exits on request.
The request is an empty file `server.stop` in the world's save folder, for world
`soma` that is `save\soma\server.stop` next to the game build. The server looks for
the file twice a second, deletes it, saves the world, sends connected clients the
co-op "session ending" notice and exits with code 0. If the save fails, the server
keeps running and writes the reason to `config\debug.log`; a new `server.stop` tries
again. The supervisor does not restart a server after a requested stop (code 0 and
the line `STOP: world saved` in the game's log), and removes a leftover
`server.stop` before it starts one. The game also returns code 0 without that line
when it fails to start, so the supervisor restarts such an exit like a crash.

`stop-server.ps1` makes this request first and waits up to two minutes. Only if the
server never takes the file, as build `7cc9d26c8e` never does, does the script end
the task and the process, and then the world returns to its last save. Ending the
task in Task Scheduler or killing the process does the same: ending the task kills
the whole process tree.

## Known problems

- **One player at a time**: see the [road to N players](doc/soma-world/roadmap.en.md).
  The server does not refuse a second player: a join from the menu always sends
  the name `player2`, so the server takes a second join for the first player
  reconnecting. Nobody has tested what that does to the first player's game, so
  do not join while someone is in the world.
- **A hard stop loses what is unsaved.** A killed process, an ended task or a PC
  turned off returns the world to its last save: up to 5 minutes of play with
  nobody connected, longer while a player acts slowly.
- **A failed save goes unnoticed by the player.** The server answers a player's
  save request with "saved" even when the write failed; only the server's log
  gives the reason.
- **Log and memory grow while a player thinks.** With an idle player connected,
  the game's log grows by about 65 MB a day and memory by a few megabytes per hour
  of waiting; both reset when the server restarts.
- **Windows client only** in the release.
- **No password**: see "What works now".

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
