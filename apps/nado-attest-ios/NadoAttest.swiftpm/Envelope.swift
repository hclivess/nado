// The chain's challenge and the {att, cdj, rp} envelope — byte-exact with ops/transaction_ops.register_device_challenge
// and the wallet's attestDevice(). Canonical JSON: sorted keys, no whitespace, ints as ints (hashing.canonical_bytes);
// the challenge list is [chain_id, sender, anchor_hash, max_block].
import Foundation
import CryptoKit

enum Envelope {
    static func challenge(sender: String, anchorHash: String, maxBlock: Int) -> [UInt8] {
        let canonical = "[\"\(Config.chainId)\",\"\(sender)\",\"\(anchorHash)\",\(maxBlock)]"
        return Blake2b.hash(Array(canonical.utf8), outLen: 32)
    }

    static func base64url(_ b: [UInt8]) -> String {
        Data(b).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    /// clientDataJSON for the app formats: type "nado.app" (the kernel checks it), the challenge, the App ID as origin.
    static func clientData(challenge: [UInt8]) -> Data {
        let s = "{\"type\":\"nado.app\",\"challenge\":\"\(base64url(challenge))\",\"origin\":\"\(Config.appId)\"}"
        return Data(s.utf8)
    }

    static func sha256(_ d: Data) -> Data { Data(SHA256.hash(data: d)) }

    /// CBOR {fmt: "apple-assertion", attStmt: {sig, authData, pub}} around what generateAssertion returned.
    static func wrapAssertion(signature: Data, authData: Data, pub: Data) -> Data {
        var out = Data([0xa2])
        out += cborText("fmt"); out += cborText("apple-assertion")
        out += cborText("attStmt"); out += Data([0xa3])
        out += cborText("authData"); out += cborBytes(authData)
        out += cborText("pub"); out += cborBytes(pub)
        out += cborText("sig"); out += cborBytes(signature)
        return out
    }

    /// Apple's assertion result is CBOR {"signature": bytes, "authenticatorData": bytes}; a minimal scan for both.
    static func unpackAssertion(_ cbor: Data) -> (sig: Data, authData: Data)? {
        guard let sig = cborFind(cbor, key: "signature"), let ad = cborFind(cbor, key: "authenticatorData") else { return nil }
        return (sig, ad)
    }

    /// The App Attest public key from the attestation object's authData COSE key: rpIdHash(32) flags(1) counter(4)
    /// aaguid(16) credIdLen(2) credId(32) then COSE {1:2, 3:-7, -1:1, -2: x(32), -3: y(32)} -> 0x04 || x || y.
    static func publicKeyPoint(fromAttestation att: Data) -> Data? {
        guard let ad = cborFind(att, key: "authData"), ad.count >= 55 else { return nil }
        let n = Int(ad[53]) << 8 | Int(ad[54])
        let cose = ad.subdata(in: (55 + n)..<ad.count)
        guard let x = coseCoord(cose, label: 0x21), let y = coseCoord(cose, label: 0x22) else { return nil }   // -2, -3
        return Data([0x04]) + x + y
    }

    // --- tiny CBOR helpers (definite lengths only, which is what Apple emits) ---
    static func cborText(_ s: String) -> Data { cborHead(3, s.utf8.count) + Data(s.utf8) }
    static func cborBytes(_ d: Data) -> Data { cborHead(2, d.count) + d }
    static func cborHead(_ major: UInt8, _ n: Int) -> Data {
        if n < 24 { return Data([major << 5 | UInt8(n)]) }
        if n < 256 { return Data([major << 5 | 24, UInt8(n)]) }
        if n < 65536 { return Data([major << 5 | 25, UInt8(n >> 8), UInt8(n & 0xff)]) }
        return Data([major << 5 | 26, UInt8(n >> 24), UInt8((n >> 16) & 0xff), UInt8((n >> 8) & 0xff), UInt8(n & 0xff)])
    }
    /// Find `key` (text) in a top-level CBOR map and return its byte-string value.
    static func cborFind(_ d: Data, key: String) -> Data? {
        let pat = cborText(key)
        guard let r = d.range(of: pat) else { return nil }
        var p = r.upperBound
        guard p < d.count else { return nil }
        let head = d[p]; guard head >> 5 == 2 else { return nil }
        let ai = Int(head & 0x1f); p += 1
        var n = ai
        if ai == 24 { n = Int(d[p]); p += 1 }
        else if ai == 25 { n = Int(d[p]) << 8 | Int(d[p + 1]); p += 2 }
        else if ai == 26 { n = Int(d[p]) << 24 | Int(d[p + 1]) << 16 | Int(d[p + 2]) << 8 | Int(d[p + 3]); p += 4 }
        guard p + n <= d.count else { return nil }
        return d.subdata(in: p..<(p + n))
    }
    /// COSE negative-int label (0x21 = -2, 0x22 = -3) followed by a 32-byte string (0x58 0x20).
    static func coseCoord(_ cose: Data, label: UInt8) -> Data? {
        let pat = Data([label, 0x58, 0x20])
        guard let r = cose.range(of: pat), r.upperBound + 32 <= cose.count else { return nil }
        return cose.subdata(in: r.upperBound..<(r.upperBound + 32))
    }
}
