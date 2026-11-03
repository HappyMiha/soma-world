# Road to N players

[Українська](roadmap.uk.md) · [README](../../README.en.md)

SOMA World aims for one shared world where many residents and people live at the
same time. Today the server holds one player. Below is what in the code stands in
the way, and the order in which to remove it. File references match the fork at
`7cc9d26c8e`.

## What exists now

- `src/main.cpp`, `--server` mode: the world loads without a window, the game loop
  runs in real time (1 turn per second), and the anchor character's moves are
  zeroed, so the server never waits for its input.
- `src/mp_server.h`: the server accepts several sockets (`clients_`) but has
  exactly one active session (`active_session_`). Only that session's disconnect
  ends the shared game.
- `src/mp_queue.h`: an `mp_event` already carries a `session_id`, but the comments
  and handling assume "player 2".
- `src/mp_gamestate.h`: state for a single remote player
  (`serialize_remote_player_state`, `grant_client_turn`) and 61 lines that
  mention "partner", each of which assumes exactly two participants.
- `src/mp_intent.h`: lockstep turns with a turn grant: while one player thinks,
  the other waits.

## Stages

### 1. Small fixes

**Done:** build `9f50a6140a` (PRs #1, #2, #4) runs on the server since 4 November
2026. What follows is what was fixed.

- **Version in `--client`.** `src/main.cpp` calls `cata_mp::client_connect(...)`
  from the command line without a version, and the server rejects that client. It
  must pass `getVersionString()`. Password joins then work, and the server can be
  closed with a password.
- **Lossless stop.** The `--server` loop ends only with the game. It needs a way to
  save the world and exit on request. The proposal is a `server.stop` file in
  [PR #1](https://github.com/HappyMiha/soma-world/pull/1). Ending the Task
  Scheduler task kills the whole process tree, so an autostarted server has to be
  stopped through that file, not through the task.
- **Autosave in `--server`.** The world is never written: per the investigation,
  `quicksave()` returns at once because in server mode the
  `moves_since_last_save` counter stays at zero (the anchor's moves are zeroed).
- **Crash with an idle player.** Per the investigation, `--server` has no user
  interface (`tilecontext` is null), yet after 100 ms the client wait loop polls
  host input, which reaches for it (`src/handle_action.cpp`). Steps meant only for
  a host must be skipped.

### 2. Several sessions

- Replace `active_session_` with a session table; one session's disconnect must
  not end the world for the others.
- Spawn a separate character for each `connect` event; the `session_id` for this
  already exists.
- Move `serialize_remote_player_state` and `grant_client_turn` from one remote
  player to every session.
- Walk all 61 lines that mention "partner" in `src/mp_gamestate.h` and the
  matching code in `src/mp_gamestate.cpp` (1.09 MB). This is the largest part of
  the stage.

### 3. Time for agents

Lockstep blocks everyone while someone thinks. A resident driven by a language
model may take seconds to minutes per action, and people would wait for it. In
server mode the world already runs in real time, so a rule is needed: every player
has a deadline per action, after which the turn passes, and nobody else ever
waits.

### 4. A world the residents build

- A settlement inside the anchor's bubble (about 120×120 tiles around evac
  shelter A-23).
- A world change log: who built what, and when.
- Regular backups of `save/`.

### 5. Several bubbles

Separate simulation around each group of players, so the world is not limited to
60 tiles from the anchor. This is the deepest engine change: the map (`map`) is a
single buffer around the character. Do not start until stages 2 and 3 are stable.

## Risks

- The co-op fork is young: its issues describe crashes, broken auto-travel and
  slow time in multiplayer. Its player guide does not describe `--server` mode.
- No TLS on the connection. The password is off for now because the `Join` menu
  sends an empty one.
- The fork's history weighs about 12.5 GB; syncing with upstream needs discipline.
- CC BY-SA 3.0: every change is distributed on the same terms, with attribution.
