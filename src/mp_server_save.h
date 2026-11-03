#pragma once
#ifndef CATA_SRC_MP_SERVER_SAVE_H
#define CATA_SRC_MP_SERVER_SAVE_H

// Saving the world on a headless dedicated server (--server).
//
// Every --server save goes through game::quicksave(): the periodic autosave
// (do_turn() -> game::autosave()) and a client's save_request and
// session_ending (handle_remote_action() in mp_gamestate.cpp).  quicksave()
// writes only after something happened since the last save; on a --server,
// do_turn() counts each simulated turn for that.  The save itself comes here,
// through a single named callout in quicksave(), because a --server has no
// player to show a failure to and no handler above do_turn() for an exception.
//
// Kept in an MP-only file so it cannot conflict with upstream save code.

namespace cata_mp
{

// --server only.  Writes the world with game::save(), logs the outcome through
// mp_log() (stdout and cdda-mp-server.log) and returns whether the world was
// written.  A failed save, including one where game::save() throws, is logged,
// and the server keeps running.  Named callout from game::quicksave().
bool mp_server_save_world();

} // namespace cata_mp

#endif // CATA_SRC_MP_SERVER_SAVE_H
