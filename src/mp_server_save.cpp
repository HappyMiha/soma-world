#include "mp_server_save.h"

#include <chrono>
#include <exception>
#include <string>

#include "calendar.h"
#include "cata_path.h"
#include "game.h"
#include "mp_gamestate.h"
#include "path_info.h"

namespace cata_mp
{

bool mp_server_save_world()
{
    mp_log( "[cdda-mp] SERVER-SAVE: saving the world, turn=" +
            std::to_string( to_turn<int>( calendar::turn ) ) );
    const std::chrono::steady_clock::time_point started = std::chrono::steady_clock::now();
    bool saved = false;
    std::string error;
    try {
        saved = g->save();
    } catch( const std::exception &err ) {
        // game::save() catches only std::ios::failure, but its last write (the .pt
        // file) throws std::runtime_error, and nothing above do_turn() catches it:
        // the whole server would go down over one failed save.
        error = err.what();
    }
    const long long elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                     std::chrono::steady_clock::now() - started ).count();
    if( saved ) {
        mp_log( "[cdda-mp] SERVER-SAVE: world saved, elapsed=" + std::to_string( elapsed_ms ) +
                "ms" );
    } else {
        // Headless, game::save()'s own popups go nowhere.  A failed map write
        // reports its reason only in one, so debug.log then says just "game not
        // saved": point at the world folder as well.
        mp_log( "[cdda-mp] SERVER-SAVE: save FAILED, elapsed=" + std::to_string( elapsed_ms ) +
                "ms" + ( error.empty() ? std::string() : " (" + error + ")" ) +
                " — the server keeps running.  See " + PATH_INFO::debug().generic_u8string() +
                ".  If it only says 'game not saved', check free space and permissions under " +
                PATH_INFO::world_base_save_path().generic_u8string() + "." );
    }
    return saved;
}

} // namespace cata_mp
