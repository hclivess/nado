#!/usr/bin/env python3
"""Generate NadoAttest.swiftpm — the Swift Playgrounds (iPad) app package — from NadoAttest/*.swift. Run after
editing any Swift source; the generated folder is committed so an iPad can clone the repo (Working Copy) and open it
without a Mac. Playgrounds can run the app on the iPad itself and, with a paid developer account signed in, upload it
to App Store Connect. What it cannot do, as far as Apple documents: add the App Attest entitlement — pressing Attest
in a Playgrounds build answers the open question "does App Attest work without the capability?" live."""
import os, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "NadoAttest")
OUT = os.path.join(HERE, "NadoAttest.swiftpm")
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith(".swift") and f != "Package.swift":
        os.remove(os.path.join(OUT, f))
for f in sorted(os.listdir(SRC)):
    if f.endswith(".swift"):
        dst = "MyApp.swift" if f == "NadoAttestApp.swift" else f
        body = open(os.path.join(SRC, f)).read().replace("struct NadoAttestApp: App", "struct MyApp: App")
        open(os.path.join(OUT, dst), "w").write(body)
open(os.path.join(OUT, "Package.swift"), "w").write('''// swift-tools-version: 5.9
import PackageDescription
import AppleProductTypes

let package = Package(
    name: "NadoAttest",
    platforms: [
        .iOS("17.0")
    ],
    products: [
        .iOSApplication(
            name: "NadoAttest",
            targets: ["AppModule"],
            bundleIdentifier: "com.nadochain.attest",
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .bicycle),
            accentColor: .presetColor(.blue),
            supportedDeviceFamilies: [
                .pad,
                .phone
            ],
            supportedInterfaceOrientations: [
                .portrait,
                .landscapeRight,
                .landscapeLeft,
                .portraitUpsideDown(.when(deviceFamilies: [.pad]))
            ],
            appCategory: .utilities
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: ".",
            swiftSettings: [
                .enableUpcomingFeature("BareSlashRegexLiterals")
            ]
        )
    ],
    swiftLanguageVersions: [.v5]
)
''')
print("generated", OUT, sorted(os.listdir(OUT)))
