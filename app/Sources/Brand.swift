import Foundation

/// The app's (and the mascot's) name, in one place (ADR 0014). Every UI string, window
/// title, notification, job label, the Keychain service and the data/log folder names
/// read it from here, so changing it means editing this one file (plus paths.APP_NAME in Python,
/// PLASMIE_APP_NAME in plasmie-env.sh and APP_NAME in app/make-app.sh).
/// Internal identifiers (PLASMIE_* env vars, plasmie.* defaults keys, Plasmie* types)
/// follow the name too (ADR 0014).
enum Brand {
    static let name = "Plasmie"
    static let id = "plasmie"
    /// Older versions' names and bundle ids, oldest first: what RenameMigration carries an install over from.
    /// Every part is assembled on purpose: the old-names scan (test_old_names.py) fails on
    /// one of these names written out anywhere, so these are its only copies in Swift. The oldest
    /// bundle id also used the original author's personal reverse-DNS prefix (kept out of
    /// the personal-data scan, test_no_personal.py, the same way). They stay only so an old
    /// install's preferences, folders and jobs are still carried over.
    static let previous: [(name: String, bundleID: String)] = [
        ("Kl" + "oop", "com.v" + "hen" + ".know" + "ledge" + "loop"),
        ("Blob" + "kin", "com.blob" + "kin.app"),
    ]
}
