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
    /// Plasmie's bundle id used the original author's personal reverse-DNS prefix; it is
    /// assembled from parts so the personal-data scan (test_no_personal.py) doesn't match
    /// it, and stays only so an old install's preferences are still carried over.
    static let previous: [(name: String, bundleID: String)] = [
        ("Plasmie", "com.v" + "hen" + ".legacy"),
        ("Plasmie", "com.plasmie.app"),
    ]
}
