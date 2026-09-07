// Mirrors protocol.py — MUST track the chain. A mismatch here produces statements every node refuses.
import Foundation

enum Config {
    static let chainId = "betanet-7"            // protocol.CHAIN_ID
    static let anchorOffset = 150               // protocol.POSW_ANCHOR_OFFSET (anchor = target − this)
    static let targetMargin = 30                // the wallet's REG_TARGET_MARGIN (blocks ahead the register lands)
    static let defaultRelay = "https://get.nadochain.com"
    static let urlScheme = "nadoattest"         // nadoattest://attest?addr=<46 hex>&relay=<url>
    /// "<TEAMID>.<bundle id>" — what the chain pins in DEVICE_ATTEST_APPLE_APP_IDS. Read from the bundle at run time.
    static var appId: String {
        let team = Bundle.main.object(forInfoDictionaryKey: "AppIdentifierPrefix") as? String ?? ""
        return team + (Bundle.main.bundleIdentifier ?? "com.nadochain.attest")
    }
}
