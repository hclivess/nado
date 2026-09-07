import SwiftUI

struct ContentView: View {
    @State var address: String = ""
    @State var relay: String = Config.defaultRelay
    @State var busy = false
    @State var log: [String] = []

    var body: some View {
        NavigationStack {
            Form {
                Section("Wallet or node to vouch for") {
                    TextField("address (46 hex characters)", text: $address)
                        .font(.system(.body, design: .monospaced)).autocorrectionDisabled().textInputAutocapitalization(.never)
                    TextField("relay", text: $relay).autocorrectionDisabled().textInputAutocapitalization(.never)
                }
                Section {
                    Button(busy ? "Attesting…" : (AttestService.hasKey ? "Attest with this device's key" : "Attest — create this device's key")) {
                        Task { await attest() }
                    }.disabled(busy || !valid(address))
                } footer: {
                    Text("This device's Secure Enclave vouches for the address. One key per device, for life; the statement reaches the wallet through the relay. No coins, no account key here.")
                }
                Section("Log") {
                    ForEach(log.indices, id: \.self) { i in Text(log[i]).font(.footnote).textSelection(.enabled) }
                }
            }
            .navigationTitle("NADO Attest")
        }
        .onOpenURL { url in
            // nadoattest://attest?addr=<46 hex>&relay=<url>
            let c = URLComponents(url: url, resolvingAgainstBaseURL: false)
            if let a = c?.queryItems?.first(where: { $0.name == "addr" })?.value { address = a.lowercased() }
            if let r = c?.queryItems?.first(where: { $0.name == "relay" })?.value, !r.isEmpty { relay = r }
        }
    }

    func valid(_ a: String) -> Bool { a.count == 46 && a.allSatisfy { $0.isHexDigit } }

    func attest() async {
        busy = true; defer { busy = false }
        do {
            let r = try await Relay(relay)
            let tip = try await r.tip()
            let target = tip + Config.targetMargin
            let anchor = try await r.blockHash(number: max(0, target - Config.anchorOffset))
            log.append("tip \(tip), target \(target), anchor \(anchor.prefix(12))…")
            let (att, cdj, first) = try await AttestService.statement(sender: address.lowercased(), maxBlock: target, anchorHash: anchor)
            log.append(first ? "attested this device's key (first time)" : "assertion by this device's key")
            let res = try await r.drop(sender: address.lowercased(), maxBlock: target, att: att, cdj: cdj)
            log.append("dropped on the relay: \(res)")
            log.append("Now the wallet picks it up and registers (keep it open).")
        } catch {
            log.append("error: \(error)")
        }
    }
}
