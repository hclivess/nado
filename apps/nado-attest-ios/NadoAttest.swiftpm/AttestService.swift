// App Attest on the device: ONE key per install, kept in the device-only keychain (iOS keeps keychain items across
// app deletion), attested once, then asserting. See README.md §"One key per device".
import Foundation
import DeviceCheck
import CryptoKit
import Security

enum AttestError: Error, CustomStringConvertible {
    case unsupported, keychain(OSStatus), apple(Error), envelope(String)
    var description: String {
        switch self {
        case .unsupported: return "App Attest is not available on this device"
        case .keychain(let s): return "keychain error \(s)"
        case .apple(let e): return "App Attest: \(e.localizedDescription)"
        case .envelope(let s): return s
        }
    }
}

struct AttestService {
    private static let service = "com.nadochain.attest"
    private static let keyIdAccount = "appattest.keyId"
    private static let pubAccount = "appattest.pub"        // X9.62 point of the attested key (65 bytes)

    /// The statement for `sender` at `maxBlock`: an attestation the first time, an assertion after that.
    /// Returns (att, cdj, isAttestation).
    static func statement(sender: String, maxBlock: Int, anchorHash: String) async throws -> (Data, Data, Bool) {
        let svc = DCAppAttestService.shared
        guard svc.isSupported else { throw AttestError.unsupported }
        let chal = Envelope.challenge(sender: sender, anchorHash: anchorHash, maxBlock: maxBlock)
        let cdj = Envelope.clientData(challenge: chal)
        let cdh = Envelope.sha256(cdj)
        if let keyId = try keychainGet(keyIdAccount), let pub = try keychainGetData(pubAccount) {
            // ALREADY ATTESTED: an assertion by the same key (renewal with proof of presence, or a rebind)
            let raw: Data
            do { raw = try await svc.generateAssertion(keyId, clientDataHash: cdh) } catch { throw AttestError.apple(error) }
            guard let parts = Envelope.unpackAssertion(raw) else { throw AttestError.envelope("assertion CBOR unreadable") }
            return (Envelope.wrapAssertion(signature: parts.sig, authData: parts.authData, pub: pub), cdj, false)
        }
        // FIRST TIME ON THIS DEVICE: one key, attested once. The key id is stored BEFORE attesting so a crash between
        // the two calls never mints a second key.
        let keyId: String
        do { keyId = try await svc.generateKey() } catch { throw AttestError.apple(error) }
        try keychainSet(keyIdAccount, Data(keyId.utf8))
        let att: Data
        do { att = try await svc.attestKey(keyId, clientDataHash: cdh) } catch { throw AttestError.apple(error) }
        guard let pub = Envelope.publicKeyPoint(fromAttestation: att) else { throw AttestError.envelope("attestation authData has no COSE key") }
        try keychainSet(pubAccount, pub)
        return (att, cdj, true)
    }

    static var hasKey: Bool { (try? keychainGet(keyIdAccount)) != nil }

    // --- keychain (device-only, survives reinstall, never synced) ---
    private static func keychainGet(_ account: String) throws -> String? {
        guard let d = try keychainGetData(account) else { return nil }
        return String(data: d, encoding: .utf8)
    }
    private static func keychainGetData(_ account: String) throws -> Data? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: account, kSecReturnData as String: true]
        var out: CFTypeRef?
        let st = SecItemCopyMatching(q as CFDictionary, &out)
        if st == errSecItemNotFound { return nil }
        guard st == errSecSuccess else { throw AttestError.keychain(st) }
        return out as? Data
    }
    private static func keychainSet(_ account: String, _ value: Data) throws {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(q as CFDictionary)
        var add = q
        add[kSecValueData as String] = value
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let st = SecItemAdd(add as CFDictionary, nil)
        guard st == errSecSuccess else { throw AttestError.keychain(st) }
    }
}
