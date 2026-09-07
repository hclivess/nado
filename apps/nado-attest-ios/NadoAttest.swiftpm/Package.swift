// swift-tools-version: 5.9
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
