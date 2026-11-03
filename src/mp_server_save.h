#pragma once
#ifndef CATA_SRC_MP_SERVER_SAVE_H
#define CATA_SRC_MP_SERVER_SAVE_H

// Saving the world on a headless dedicated server (--server).
//
// A --server's periodic autosave (do_turn() -> game::autosave()) used to end in
// game::quicksave(), which is built for a local player at a screen.  It skips the
// save until the local avatar has acted since the last one, and a --server's
// anchor never acts (do_turn() zeroes its moves every turn), so the world was
// never written.  It also shows a "Saving game" popup, and a --server has no
// screen.
//
// Kept in an MP-only file (merge rule 1) so it cannot conflict with upstream save
// code.  The SP side is a single named callout in game::autosave().
//
// The server's handlers for a client's save_request and session_ending
// (mp_gamestate.cpp) still call quicksave(), which still writes nothing in
// --server.  They must not simply save here instead: they run inside
// process_mp_events(), which lets one turn action through per drain and counts
// both messages as turn actions.  A client action that arrives during the save
// would be dropped, and both sides would then wait on each other.  Those two
// messages have to be added to its is_state_sync list first.

namespace cata_mp
{

// --server only.  Writes the world with game::save(), with no popup or redraw,
// logs the outcome through mp_log() (stdout and cdda-mp-server.log) and returns
// whether the world was written.  A failed save, also one where game::save()
// throws, is logged, and the server keeps running.  Named callout (rule 4) from
// game::autosave().
bool mp_server_save_world();

} // namespace cata_mp

#endif // CATA_SRC_MP_SERVER_SAVE_H
