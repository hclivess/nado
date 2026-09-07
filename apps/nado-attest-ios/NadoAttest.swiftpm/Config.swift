// Mirrors protocol.py — MUST track the chain. A mismatch here produces statements every node refuses.
import Foundation
import Security

enum Config {
    static let chainId = "betanet-7"            // protocol.CHAIN_ID
    static let anchorOffset = 150               // protocol.POSW_ANCHOR_OFFSET (anchor = target − this)
    static let targetMargin = 30                // the wallet's REG_TARGET_MARGIN (blocks ahead the register lands)
    static let defaultRelay = "https://get.nadochain.com"
    static let urlScheme = "nadoattest"         // nadoattest://attest?addr=<46 hex>&relay=<url>
    /// "<TEAMID>.<bundle id>" — what the chain pins in DEVICE_ATTEST_APPLE_APP_IDS, and what Apple hashes into the
    /// statement's rpIdHash. Read from the keychain: the app's default access group IS its App ID (the one reliable
    /// way to learn the team prefix at run time — a Playgrounds build has no AppIdentifierPrefix in its Info.plist,
    /// and the 2026-09-07 iPad sample carried a guessed origin for exactly that reason).
    static var appId: String {
        if let g = keychainAccessGroup() { return g }
        let team = Bundle.main.object(forInfoDictionaryKey: "AppIdentifierPrefix") as? String ?? ""
        return team + (Bundle.main.bundleIdentifier ?? "com.nadochain.attest")
    }

    private static func keychainAccessGroup() -> String? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "com.nadochain.attest.appid",
                                kSecAttrAccount as String: "probe"]
        var add = q; add[kSecValueData as String] = Data([1])
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(add as CFDictionary, nil)                       // idempotent: exists already after the first run
        var read = q; read[kSecReturnAttributes as String] = true
        var out: CFTypeRef?
        guard SecItemCopyMatching(read as CFDictionary, &out) == errSecSuccess,
              let attrs = out as? [String: Any], let group = attrs[kSecAttrAccessGroup as String] as? String, !group.isEmpty else { return nil }
        return group
    }
}
