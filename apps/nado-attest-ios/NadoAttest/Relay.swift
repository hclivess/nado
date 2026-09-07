// The relay is any NADO node's HTTP API (get.nadochain.com by default). Three calls: the tip, the anchor block's
// hash, and the drop. No account key ever touches the app — it only carries a device statement.
import Foundation

struct RelayError: Error, CustomStringConvertible { let description: String }

struct Relay {
    let base: URL

    init(_ url: String) throws {
        guard let u = URL(string: url.trimmingCharacters(in: .whitespacesAndNewlines)) else { throw RelayError(description: "relay url invalid") }
        base = u
    }

    func json(_ path: String, body: Data? = nil) async throws -> [String: Any] {
        var req = URLRequest(url: base.appendingPathComponent(path))
        req.timeoutInterval = 15
        if let body {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = body
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse else { throw RelayError(description: "no HTTP response") }
        guard (200..<300).contains(http.statusCode) else {
            throw RelayError(description: "\(path): HTTP \(http.statusCode) \(String(data: data, encoding: .utf8) ?? "")")
        }
        guard let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw RelayError(description: "\(path): not a JSON object") }
        return obj
    }

    func tip() async throws -> Int {
        let d = try await json("get_latest_block")
        guard let n = d["block_number"] as? Int else { throw RelayError(description: "tip unreadable") }
        return n
    }

    func blockHash(number: Int) async throws -> String {
        var comps = URLComponents(url: base.appendingPathComponent("get_block"), resolvingAgainstBaseURL: false)!
        comps.queryItems = [URLQueryItem(name: "number", value: String(number)), URLQueryItem(name: "hash_only", value: "1")]
        var req = URLRequest(url: comps.url!)
        req.timeoutInterval = 15
        let (data, _) = try await URLSession.shared.data(for: req)
        guard let d = try JSONSerialization.jsonObject(with: data) as? [String: Any], let h = d["block_hash"] as? String, h.count == 64 else {
            throw RelayError(description: "anchor block \(number) unavailable")
        }
        return h
    }

    /// POST /device_attest_probe {att, cdj}: the relay parses the statement and KEEPS it as a sample (this is how the
    /// first real device statement reaches the maintainers for verification while the chain still refuses the format).
    func probe(att: Data, cdj: Data) async throws -> [String: Any] {
        let body: [String: Any] = ["att": att.base64EncodedString(), "cdj": cdj.base64EncodedString(), "cid": "nado-attest-app"]
        return try await json("device_attest_probe", body: try JSONSerialization.data(withJSONObject: body))
    }

    /// POST /node_attest_drop {sender, max_block, device:{att, cdj, rp}} — the receiving wallet picks it up.
    func drop(sender: String, maxBlock: Int, att: Data, cdj: Data) async throws -> [String: Any] {
        let body: [String: Any] = ["sender": sender, "max_block": maxBlock,
                                   "device": ["att": att.base64EncodedString(), "cdj": cdj.base64EncodedString(), "rp": Config.appId]]
        return try await json("node_attest_drop", body: try JSONSerialization.data(withJSONObject: body))
    }
}
