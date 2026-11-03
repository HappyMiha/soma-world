#pragma once
#ifndef CATA_SRC_MP_SERVER_SAVE_H
#define CATA_SRC_MP_SERVER_SAVE_H

// Saving the world on a headless dedicated server (--server).
//
// game::quicksave() is the one place a --server's world can be written: the
// periodic autosave (do_turn() -> game::autosave()) calls it, and so do the
// server's handlers for a client's save_request and session_ending.  It is built
// for a local player at a screen.  It skips the save until the local avatar has
// acted since the last one, and a --server's anchor never acts (do_turn() zeroes
// its moves every turn), so the world was never written.  It also shows a
// "Saving game" popup, and a --server has no screen.
//
// Kept in an MP-only file (merge rule 1) so it cannot conflict with upstream save
// code.  The SP side is a single named callout at the top of game::quicksave().

namespace cata_mp
{

// Named callout (rule 4) from game::quicksave() (game_io.cpp).  Outside --server it
// does nothing and returns false, and quicksave() runs exactly as in SP.  In
// --server it writes the world with game::save(), with no popup or redraw, logs
// the outcome through mp_log() (stdout and cdda-mp-server.log) and returns true,
// also when the save failed: the server keeps running, and quicksave() restarts
// the autosave clock as it does after any quicksave.
bool mp_server_quicksave();

} // namespace cata_mp

#endif // CATA_SRC_MP_SERVER_SAVE_H
