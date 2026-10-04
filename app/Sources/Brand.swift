import Foundation

/// The app's (and the mascot's) name, in one place (ADR 0028). Every UI string, window
/// title, notification, job label, the Keychain service and the data/log folder names
/// read it from here, so a rename is this one file (plus paths.APP_NAME in Python,
/// PLASMIE_APP_NAME in plasmie-env.sh and APP_NAME in app/make-app.sh).
/// Internal identifiers users never see (PLASMIE_* env vars, plasmie.* defaults keys, Plasmie*
/// types) keep the old name on purpose.
enum Brand {
    static let name = "Plasmie"
    static let id = "plasmie"
    /// Earlier names, oldest first: what RenameMigration carries an install over from.
    static let previous: [(name: String, bundleID: String)] = [
        ("Plasmie", "com.plasmie.legacy"),
        ("Plasmie", "com.plasmie.app"),
    ]
}
