import SwiftUI
import DeviceCheck

struct ContentView: View {
    @State var address: String = ""
    @State var relay: String = Config.defaultRelay
    @State var busy = false
    @State var log: [String] = []

    var body: some View {
        NavigationView {
            Form {
                Section("Wallet or node to vouch for") {
                    TextField("address (46 hex characters)", text: $address)
                        .font(.system(.body, design: .monospaced)).autocorrectionDisabled().textInputAutocapitalization(.never)
                    TextField("relay", text: $relay).autocorrectionDisabled().textInputAutocapitalization(.never)
                }
                Section {
                    Button(busy ? "Working…" : "Test this device (no address needed)") {
                        Task { await selfTest() }
                    }.disabled(busy)
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
        .navigationViewStyle(.stack)
        .onAppear {
            log.append("App Attest supported on this device: \(DCAppAttestService.shared.isSupported)")
            log.append("App ID as seen by this build: \(Config.appId)")
            log.append("device key already created: \(AttestService.hasKey)")
        }
        .onOpenURL { url in
            // nadoattest://attest?addr=<46 hex>&relay=<url>
            let c = URLComponents(url: url, resolvingAgainstBaseURL: false)
            if let a = c?.queryItems?.first(where: { $0.name == "addr" })?.value { address = a.lowercased() }
            if let r = c?.queryItems?.first(where: { $0.name == "relay" })?.value, !r.isEmpty { relay = r }
        }
    }

    func valid(_ a: String) -> Bool { a.count == 46 && a.allSatisfy { $0.isHexDigit } }

    /// The one-tap experiment: attest a throwaway address so the relay parses and KEEPS the statement. Answers, in the
    /// log, whether App Attest works in this build at all.
    @MainActor func selfTest() async {
        busy = true; defer { busy = false }
        let probeAddress = String(repeating: "0", count: 46)
        do {
            let r = try await Relay(relay)
            let tip = try await r.tip()
            let target = tip + Config.targetMargin
            let anchor = try await r.blockHash(number: max(0, target - Config.anchorOffset))
            log.append("relay ok: tip \(tip)")
            let (att, cdj, first) = try await AttestService.statement(sender: probeAddress, maxBlock: target, anchorHash: anchor)
            log.append(first ? "App Attest WORKED: this device attested a new key (\(att.count) bytes)" : "App Attest WORKED: assertion by the existing key (\(att.count) bytes)")
            let pr = try await r.probe(att: att, cdj: cdj)
            if let sm = pr["summary"] as? [String: Any] {
                log.append("relay parsed it: fmt \(sm["fmt"] ?? "?"), \(sm["x5c_count"] ?? 0) certificate(s) — sample kept on the relay")
            } else {
                log.append("relay answer: \(pr)")
            }
        } catch {
            log.append("error: \(error)")
        }
    }

    @MainActor func attest() async {
        busy = true; defer { busy = false }
        do {
            let r = try await Relay(relay)
            let tip = try await r.tip()
            let target = tip + Config.targetMargin
            let anchor = try await r.blockHash(number: max(0, target - Config.anchorOffset))
            log.append("tip \(tip), target \(target), anchor \(anchor.prefix(12))…")
            let (att, cdj, first) = try await AttestService.statement(sender: address.lowercased(), maxBlock: target, anchorHash: anchor)
            log.append(first ? "attested this device's key (first time)" : "assertion by this device's key")
            if let pr = try? await r.probe(att: att, cdj: cdj), let sm = pr["summary"] as? [String: Any] {
                log.append("relay parsed it: fmt \(sm["fmt"] ?? "?"), \(sm["x5c_count"] ?? 0) certificate(s), sample kept")
            }
            let res = try await r.drop(sender: address.lowercased(), maxBlock: target, att: att, cdj: cdj)
            log.append("dropped on the relay: \(res)")
            log.append("Now the wallet picks it up and registers (keep it open).")
        } catch {
            log.append("error: \(error)")
        }
    }
}
