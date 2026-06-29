import AppKit
import Foundation
import UniformTypeIdentifiers

struct Profile: Codable {
    let number: Int
    let displayNumber: Int?
    let name: String
    let fingerprint: Int
    let appPath: String
    let profilePath: String
    let args: [String]
    let proxy: String?
    let remark: String?
    let openUrls: [String]?
    let cookieJSON: String?
    let fingerprintConfig: FingerprintConfig?

    enum CodingKeys: String, CodingKey {
        case number
        case displayNumber = "display_number"
        case name
        case fingerprint
        case appPath = "app_path"
        case profilePath = "profile_path"
        case args
        case proxy
        case remark
        case openUrls = "open_urls"
        case cookieJSON = "cookie_json"
        case fingerprintConfig = "fingerprint_config"
    }
}

struct FingerprintConfig: Codable {
    var platform: String
    var chromeVersion: String
    var userAgent: String
    var width: Int
    var height: Int
    var deviceScaleFactor: String
    var cpuCores: Int
    var memoryGB: Int
    var webRTCPolicy: String
}

struct ProfileStore: Codable {
    var profiles: [Profile]
}

struct SharedExtensionStore: Codable {
    var paths: [String]
}

struct WindowState {
    let pid: Int32
    let profilePath: String
    let command: String
}

final class FixedPage: NSView {
    override var isFlipped: Bool { true }
}

final class ProfileManager {
    let dataRoot: URL
    let runtimeRoot: URL
    let configURL: URL
    let sharedExtensionsURL: URL
    let browserCandidates = [
        "/Applications/Chromium.app",
        "/Applications/Google Chrome.app",
    ]

    init(dataRoot: URL, runtimeRoot: URL) {
        self.dataRoot = dataRoot
        self.runtimeRoot = runtimeRoot
        self.configURL = dataRoot.appendingPathComponent("profiles/profiles.json")
        self.sharedExtensionsURL = dataRoot.appendingPathComponent("profiles/shared_extensions.json")
    }

    static func defaultDataRoot() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return base.appendingPathComponent("指纹浏览器", isDirectory: true)
    }

    func defaultFingerprintConfig() -> FingerprintConfig {
        FingerprintConfig(
            platform: "macos",
            chromeVersion: "148",
            userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_2) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.7778.215 Safari/537.36",
            width: 1280,
            height: 720,
            deviceScaleFactor: "1",
            cpuCores: 8,
            memoryGB: 8,
            webRTCPolicy: "disable-non-proxied-udp"
        )
    }

    func defaultBrowserAppPath() -> String {
        browserCandidates.first(where: { FileManager.default.fileExists(atPath: $0) }) ?? browserCandidates[0]
    }

    func browserDisplayName() -> String {
        URL(fileURLWithPath: defaultBrowserAppPath()).lastPathComponent
    }

    func resolvedBrowserAppPath(preferred: String?) -> String {
        let trimmed = preferred?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !trimmed.isEmpty, FileManager.default.fileExists(atPath: trimmed) {
            return trimmed
        }
        return defaultBrowserAppPath()
    }

    func fingerprintArgs(_ config: FingerprintConfig) -> [String] {
        var args = [
            "--fingerprint-platform=\(config.platform)",
            "--fingerprint-brand-version=\(config.chromeVersion)",
            "--user-agent=\(config.userAgent)",
            "--window-size=\(config.width),\(config.height)",
            "--force-device-scale-factor=\(config.deviceScaleFactor)",
            "--fingerprint-hardware-concurrency=\(config.cpuCores)",
        ]
        if config.webRTCPolicy == "disable-non-proxied-udp" {
            args.append("--disable-non-proxied-udp")
        }
        return args
    }

    func load() -> [Profile] {
        try? FileManager.default.createDirectory(at: dataRoot, withIntermediateDirectories: true)
        migrateLegacyDataIfNeeded()
        let saved: [Profile]
        if let data = try? Data(contentsOf: configURL) {
            let decoded = (try? JSONDecoder().decode(ProfileStore.self, from: data).profiles) ?? []
            saved = decoded.map { profile in
                let cleanName = localizedProfileName(profile.name)
                return Profile(
                    number: profile.number,
                    displayNumber: profile.displayNumber ?? profile.number,
                    name: cleanName,
                    fingerprint: profile.fingerprint,
                    appPath: repairedAppPath(savedPath: profile.appPath, name: cleanName, number: profile.number),
                    profilePath: repairedProfilePath(savedPath: profile.profilePath, number: profile.number),
                    args: profile.args,
                    proxy: profile.proxy,
                    remark: profile.remark,
                    openUrls: profile.openUrls,
                    cookieJSON: profile.cookieJSON,
                    fingerprintConfig: profile.fingerprintConfig
                )
            }
        } else {
            saved = []
        }

        var byNumber = Dictionary(uniqueKeysWithValues: saved.map { ($0.number, $0) })
        for profile in scanGeneratedProfiles() where byNumber[profile.number] == nil {
            byNumber[profile.number] = profile
        }

        let merged = byNumber.values.sorted { $0.number < $1.number }
        save(merged)
        return merged
    }

    func migrateLegacyDataIfNeeded() {
        let fileManager = FileManager.default
        let legacyRoot = Bundle.main.bundleURL.deletingLastPathComponent()
        let legacyProfilesURL = legacyRoot.appendingPathComponent("profiles")
        let legacyAppsURL = legacyRoot.appendingPathComponent("apps")
        let legacySharedExtensionsURL = legacyProfilesURL.appendingPathComponent("shared_extensions.json")
        let destinationProfilesURL = dataRoot.appendingPathComponent("profiles")
        let destinationAppsURL = dataRoot.appendingPathComponent("apps")

        let hasLegacyProfiles = fileManager.fileExists(atPath: legacyProfilesURL.path)
        let hasLegacyApps = fileManager.fileExists(atPath: legacyAppsURL.path)
        guard hasLegacyProfiles || hasLegacyApps else { return }

        try? fileManager.createDirectory(at: destinationProfilesURL, withIntermediateDirectories: true)
        try? fileManager.createDirectory(at: destinationAppsURL, withIntermediateDirectories: true)

        if hasLegacyProfiles {
            migrateDirectoryContents(from: legacyProfilesURL, to: destinationProfilesURL)
        }
        if hasLegacyApps {
            migrateDirectoryContents(from: legacyAppsURL, to: destinationAppsURL)
        }
        if fileManager.fileExists(atPath: legacySharedExtensionsURL.path),
           !fileManager.fileExists(atPath: sharedExtensionsURL.path) {
            try? fileManager.copyItem(at: legacySharedExtensionsURL, to: sharedExtensionsURL)
        }
    }

    func migrateDirectoryContents(from source: URL, to destination: URL) {
        let fileManager = FileManager.default
        guard let items = try? fileManager.contentsOfDirectory(at: source, includingPropertiesForKeys: nil) else {
            return
        }
        for item in items {
            let target = destination.appendingPathComponent(item.lastPathComponent)
            guard !fileManager.fileExists(atPath: target.path) else { continue }
            do {
                try fileManager.moveItem(at: item, to: target)
            } catch {
                try? fileManager.copyItem(at: item, to: target)
            }
        }
    }

    func save(_ profiles: [Profile]) {
        let store = ProfileStore(profiles: profiles)
        guard let data = try? JSONEncoder.pretty.encode(store) else { return }
        do {
            try FileManager.default.createDirectory(
                at: configURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            if FileManager.default.fileExists(atPath: configURL.path) {
                let backupURL = configURL.deletingLastPathComponent()
                    .appendingPathComponent("profiles.backup.json")
                try? FileManager.default.removeItem(at: backupURL)
                try? FileManager.default.copyItem(at: configURL, to: backupURL)
            }
            let tempURL = configURL.deletingLastPathComponent()
                .appendingPathComponent(".profiles.json.tmp")
            try data.write(to: tempURL, options: [.atomic])
            if FileManager.default.fileExists(atPath: configURL.path) {
                _ = try FileManager.default.replaceItemAt(configURL, withItemAt: tempURL)
            } else {
                try FileManager.default.moveItem(at: tempURL, to: configURL)
            }
        } catch {
            NSLog("保存 profiles.json 失败: \(error.localizedDescription)")
        }
    }

    func loadSharedExtensions() -> [String] {
        guard let data = try? Data(contentsOf: sharedExtensionsURL) else { return [] }
        let decoded = (try? JSONDecoder().decode(SharedExtensionStore.self, from: data))?.paths ?? []
        return decoded
            .map(canonicalPath)
            .filter { FileManager.default.fileExists(atPath: $0) }
    }

    func saveSharedExtensions(_ paths: [String]) {
        let unique = Array(NSOrderedSet(array: paths.map(canonicalPath))) as? [String] ?? paths.map(canonicalPath)
        let store = SharedExtensionStore(paths: unique.filter { FileManager.default.fileExists(atPath: $0) })
        guard let data = try? JSONEncoder.pretty.encode(store) else { return }
        do {
            try FileManager.default.createDirectory(
                at: sharedExtensionsURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: sharedExtensionsURL, options: [.atomic])
        } catch {
            NSLog("保存 shared_extensions.json 失败: \(error.localizedDescription)")
        }
    }

    func addSharedExtensions(_ urls: [URL]) {
        let existing = loadSharedExtensions()
        let appended = urls.map { canonicalPath($0.path) }
        saveSharedExtensions(existing + appended)
    }

    func removeSharedExtension(at index: Int) {
        var paths = loadSharedExtensions()
        guard paths.indices.contains(index) else { return }
        paths.remove(at: index)
        saveSharedExtensions(paths)
    }

    func clearSharedExtensions() {
        saveSharedExtensions([])
    }

    func repairedAppPath(savedPath: String, name: String, number: Int) -> String {
        if FileManager.default.fileExists(atPath: savedPath) {
            return savedPath
        }
        let cleanURL = cleanAppURL(name: name, number: number)
        if FileManager.default.fileExists(atPath: cleanURL.path) {
            return cleanURL.path
        }
        let legacyURL = dataRoot.appendingPathComponent("apps/\(sanitizedProfileName(name)) \(number).app")
        if FileManager.default.fileExists(atPath: legacyURL.path) {
            return legacyURL.path
        }
        return cleanURL.path
    }

    func repairedProfilePath(savedPath: String, number: Int) -> String {
        if FileManager.default.fileExists(atPath: savedPath) {
            return canonicalPath(savedPath)
        }
        return canonicalPath(dataRoot.appendingPathComponent("profiles/profile-\(number)").path)
    }

    func nextNumber(_ profiles: [Profile]) -> Int {
        let used = Set(profiles.map { $0.number })
        var number = 1
        while used.contains(number) {
            number += 1
        }
        return number
    }

    func scanGeneratedProfiles() -> [Profile] {
        let appsURL = dataRoot.appendingPathComponent("apps")
        guard let enumerator = FileManager.default.enumerator(
            at: appsURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }

        let regex = try? NSRegularExpression(pattern: #"profile-([0-9]+)"#)
        var result: [Profile] = []
        for case let appURL as URL in enumerator where appURL.pathExtension == "app" {
            let path = appURL.path
            let number: Int?
            if let regex,
               let match = regex.firstMatch(in: path, range: NSRange(path.startIndex..., in: path)),
               let range = Range(match.range(at: 1), in: path) {
                number = Int(path[range])
            } else {
                let fileName = appURL.lastPathComponent
                let fallback = try? NSRegularExpression(pattern: #"^(.+) ([0-9]+)\.app$"#)
                if let fallback,
                   let match = fallback.firstMatch(in: fileName, range: NSRange(fileName.startIndex..., in: fileName)),
                   let range = Range(match.range(at: 2), in: fileName) {
                    number = Int(fileName[range])
                } else {
                    number = nil
                }
            }
            guard let number else { continue }
            let displayName = localizedProfileName(String(appURL.deletingPathExtension().lastPathComponent))
            let profilePath = dataRoot.appendingPathComponent("profiles/profile-\(number)").path
            let fingerprint = 10000 + number - 1
            result.append(Profile(
                number: number,
                displayNumber: number,
                name: displayName,
                fingerprint: fingerprint,
                appPath: appURL.path,
                profilePath: canonicalPath(profilePath),
                args: [],
                proxy: nil,
                remark: nil,
                openUrls: nil,
                cookieJSON: nil,
                fingerprintConfig: nil
            ))
        }
        return result
    }

    func createProfile(
        currentProfiles: [Profile],
        sourceApp: String,
        appName: String,
        displayNumber: Int?,
        seedBase: Int,
        language: String,
        timezone: String,
        proxy: String,
        extraArgs: String,
        cookieText: String,
        openUrls: [String],
        remark: String,
        fingerprintConfig: FingerprintConfig
    ) throws -> Profile {
        let number = nextNumber(currentProfiles)
        let fingerprint = seedBase + number - 1

        var args = fingerprintArgs(fingerprintConfig)
        if !language.isEmpty {
            args.append("--lang=\(language)")
            args.append("--accept-lang=\(language)")
        }
        if !timezone.isEmpty {
            args.append("--timezone=\(timezone)")
        }
        if !proxy.isEmpty {
            args.append("--proxy-server=\(proxy)")
        }
        args.append(contentsOf: extraArgs.split(separator: "\n").map(String.init).filter { !$0.isEmpty })

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.currentDirectoryURL = dataRoot
        process.arguments = [
            runtimeRoot.appendingPathComponent("tools/create_fingerprint_profiles.py").path,
            "--count", "1",
            "--start", "\(number)",
            "--source-app", sourceApp,
            "--output-dir", dataRoot.appendingPathComponent("apps").path,
            "--profile-dir", dataRoot.appendingPathComponent("profiles").path,
            "--app-name", appName,
            "--fingerprint-base", "\(fingerprint)",
            "--force",
            "--cookie-json", cookieText,
        ] + openUrls.map { "--open-url=\($0)" } + args.map { "--extra-arg=\($0)" }

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        process.waitUntilExit()

        if process.terminationStatus != 0 {
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw NSError(domain: "FingerprintManager", code: Int(process.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: message
            ])
        }

        return Profile(
            number: number,
            displayNumber: displayNumber ?? number,
            name: appName,
            fingerprint: fingerprint,
            appPath: cleanAppURL(name: appName, number: number).path,
            profilePath: canonicalPath(dataRoot.appendingPathComponent("profiles/profile-\(number)").path),
            args: args,
            proxy: proxy.isEmpty ? nil : proxy,
            remark: remark.isEmpty ? nil : remark,
            openUrls: openUrls.isEmpty ? nil : openUrls,
            cookieJSON: cookieText.isEmpty ? nil : cookieText,
            fingerprintConfig: fingerprintConfig
        )
    }

    func rebuildLauncher(for profile: Profile) throws {
        let appURL = URL(fileURLWithPath: profile.appPath)
        let launcherURL = appURL.appendingPathComponent("Contents/MacOS/FingerprintLauncher")
        let profileURL = URL(fileURLWithPath: profile.profilePath)
        let chromiumBinary = chromiumExecutablePath()

        var args = normalizedArgs(for: profile)
        if !args.contains(where: { $0.hasPrefix("--fingerprint=") }) {
            args.insert("--fingerprint=\(profile.fingerprint)", at: 0)
        }
        let urls = profile.openUrls ?? []
        let cookieText = profile.cookieJSON ?? ""
        if !cookieText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            try rebuildBootstrapExtension(profileURL: profileURL, cookieText: cookieText)
        } else {
            let extensionURL = profileURL.appendingPathComponent("bootstrap_extension")
            if FileManager.default.fileExists(atPath: extensionURL.path) {
                try? FileManager.default.removeItem(at: extensionURL)
            }
        }
        var extensionPaths = loadSharedExtensions()
        let bootstrapPath = profileURL.appendingPathComponent("bootstrap_extension").path
        if FileManager.default.fileExists(atPath: bootstrapPath) {
            extensionPaths.append(bootstrapPath)
        }
        if !extensionPaths.isEmpty {
            let joined = extensionPaths
                .map(canonicalPath)
                .filter { FileManager.default.fileExists(atPath: $0) }
                .joined(separator: ",")
            if !joined.isEmpty {
                args.append("--load-extension=\(joined)")
            }
        }

        let quoted = args.map { "\"\($0.replacingOccurrences(of: "\"", with: "\\\""))\"" }.joined(separator: " ")
        let quotedURLs = urls.map(normalizedOpenURL)
            .filter { !$0.isEmpty }
            .map { "\"\($0.replacingOccurrences(of: "\"", with: "\\\""))\"" }
            .joined(separator: " ")
        let script = """
        #!/bin/zsh
        set -e

        EXECUTABLE="\(chromiumBinary)"
        PROFILE_DIR="\(profile.profilePath)"

        mkdir -p "$PROFILE_DIR"
        exec "$EXECUTABLE" \\
          --user-data-dir="$PROFILE_DIR" \\
          --no-first-run \\
          --no-default-browser-check \\
          \(quoted) \\
          \(quotedURLs) \\
          "$@"
        """
        try script.write(to: launcherURL, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: launcherURL.path)
        _ = try? Process.run(URL(fileURLWithPath: "/usr/bin/codesign"), arguments: ["--force", "--deep", "--sign", "-", appURL.path])
    }

    func chromiumExecutablePath() -> String {
        let sourceApp = URL(fileURLWithPath: defaultBrowserAppPath())
        let infoURL = sourceApp.appendingPathComponent("Contents/Info.plist")
        if let infoData = try? Data(contentsOf: infoURL),
           let plist = try? PropertyListSerialization.propertyList(from: infoData, options: [], format: nil) as? [String: Any],
           let executable = plist["CFBundleExecutable"] as? String {
            return sourceApp.appendingPathComponent("Contents/MacOS/\(executable)").path
        }
        return sourceApp.appendingPathComponent("Contents/MacOS/Chromium").path
    }

    func renamedProfile(_ profile: Profile, to rawName: String) throws -> Profile {
        let cleanName = sanitizedProfileName(rawName.isEmpty ? profile.name : rawName)
        let targetAppURL = cleanAppURL(name: cleanName, number: profile.number)
        let currentAppURL = URL(fileURLWithPath: profile.appPath)

        if currentAppURL.path != targetAppURL.path {
            if FileManager.default.fileExists(atPath: targetAppURL.path) {
                throw NSError(domain: "FingerprintManager", code: 20, userInfo: [
                    NSLocalizedDescriptionKey: "目标窗口名称已存在：\(targetAppURL.lastPathComponent)"
                ])
            }
            try FileManager.default.createDirectory(
                at: targetAppURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try FileManager.default.moveItem(at: currentAppURL, to: targetAppURL)
            cleanupEmptyParentDirectory(of: currentAppURL)
        }

        try updateAppDisplayName(appURL: targetAppURL, displayName: cleanName)
        _ = try? Process.run(URL(fileURLWithPath: "/usr/bin/codesign"), arguments: ["--force", "--deep", "--sign", "-", targetAppURL.path])

        return Profile(
            number: profile.number,
            displayNumber: profile.displayNumber,
            name: cleanName,
            fingerprint: profile.fingerprint,
            appPath: targetAppURL.path,
            profilePath: profile.profilePath,
            args: profile.args,
            proxy: profile.proxy,
            remark: profile.remark,
            openUrls: profile.openUrls,
            cookieJSON: profile.cookieJSON,
            fingerprintConfig: profile.fingerprintConfig
        )
    }

    func updateIcon(for profile: Profile) throws {
        let badgeNumber = max(1, profile.displayNumber ?? profile.number)
        let sourceIcon = URL(fileURLWithPath: resolvedBrowserAppPath(preferred: nil))
            .appendingPathComponent("Contents/Resources/app.icns")
        let appURL = URL(fileURLWithPath: profile.appPath)
        let targetIcon = appURL.appendingPathComponent("Contents/Resources/profile.icns")
        let runtimeIcon = appURL.appendingPathComponent("Contents/Resources/app.icns")
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.currentDirectoryURL = dataRoot
        process.arguments = [
            "-c",
            """
            from pathlib import Path
            import sys
            sys.path.insert(0, \(String(reflecting: runtimeRoot.appendingPathComponent("tools").path)))
            import create_fingerprint_profiles as gen
            source = Path(\(String(reflecting: sourceIcon.path)))
            target = Path(\(String(reflecting: targetIcon.path)))
            runtime = Path(\(String(reflecting: runtimeIcon.path)))
            work = Path(\(String(reflecting: dataRoot.appendingPathComponent("apps/.icon-work").path)))
            work.mkdir(parents=True, exist_ok=True)
            base = gen.icon_base_image(source, work)
            gen.make_numbered_icon(base, \(badgeNumber), target, work)
            runtime.write_bytes(target.read_bytes())
            """
        ]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let message = String(data: data, encoding: .utf8) ?? "图标生成失败"
            throw NSError(domain: "FingerprintManager", code: Int(process.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: message
            ])
        }
        if FileManager.default.fileExists(atPath: runtimeIcon.path) {
            try FileManager.default.removeItem(at: runtimeIcon)
        }
        try FileManager.default.copyItem(at: targetIcon, to: runtimeIcon)
        try disableAssetCatalogIcon(appURL: appURL)
        try removeBundleIconName(appURL: appURL)
        _ = try? FileManager.default.removeItem(at: dataRoot.appendingPathComponent("apps/.icon-work"))
        _ = try? Process.run(URL(fileURLWithPath: "/usr/bin/codesign"), arguments: ["--force", "--deep", "--sign", "-", profile.appPath])
    }

    func removeBundleIconName(appURL: URL) throws {
        let infoURL = appURL.appendingPathComponent("Contents/Info.plist")
        let data = try Data(contentsOf: infoURL)
        guard var plist = try PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any] else {
            return
        }
        plist["CFBundleIconFile"] = "app.icns"
        plist.removeValue(forKey: "CFBundleIconName")
        let output = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try output.write(to: infoURL)
    }

    func disableAssetCatalogIcon(appURL: URL) throws {
        let resourcesURL = appURL.appendingPathComponent("Contents/Resources")
        let assetsURL = resourcesURL.appendingPathComponent("Assets.car")
        let disabledURL = resourcesURL.appendingPathComponent("Assets.car.disabled")
        if FileManager.default.fileExists(atPath: assetsURL.path) {
            if FileManager.default.fileExists(atPath: disabledURL.path) {
                try? FileManager.default.removeItem(at: disabledURL)
            }
            try FileManager.default.moveItem(at: assetsURL, to: disabledURL)
        }
    }

    func updateAppDisplayName(appURL: URL, displayName: String) throws {
        let infoURL = appURL.appendingPathComponent("Contents/Info.plist")
        let data = try Data(contentsOf: infoURL)
        guard var plist = try PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any] else {
            return
        }
        plist["CFBundleDisplayName"] = displayName
        plist["CFBundleName"] = displayName
        if var urlTypes = plist["CFBundleURLTypes"] as? [[String: Any]] {
            for index in urlTypes.indices {
                if urlTypes[index]["CFBundleURLName"] != nil {
                    urlTypes[index]["CFBundleURLName"] = "\(displayName) 地址"
                }
            }
            plist["CFBundleURLTypes"] = urlTypes
        }
        let output = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try output.write(to: infoURL)
        try updateLocalizedDisplayNames(appURL: appURL, displayName: displayName)
    }

    func cleanAppURL(name: String, number: Int) -> URL {
        dataRoot.appendingPathComponent("apps/profile-\(number)/\(sanitizedProfileName(name)).app")
    }

    func cleanupEmptyParentDirectory(of appURL: URL) {
        let parent = appURL.deletingLastPathComponent()
        guard parent.lastPathComponent.hasPrefix("profile-") else { return }
        if let items = try? FileManager.default.contentsOfDirectory(atPath: parent.path), items.isEmpty {
            try? FileManager.default.removeItem(at: parent)
        }
    }

    func updateLocalizedDisplayNames(appURL: URL, displayName: String) throws {
        let resourcesURL = appURL.appendingPathComponent("Contents/Resources")
        guard let enumerator = FileManager.default.enumerator(at: resourcesURL, includingPropertiesForKeys: nil) else {
            return
        }
        let content = """
        CFBundleDisplayName = "\(displayName)";
        CFBundleName = "\(displayName)";
        """
        for case let fileURL as URL in enumerator where fileURL.lastPathComponent == "InfoPlist.strings" {
            try content.write(to: fileURL, atomically: true, encoding: .utf8)
        }
    }

    func sanitizedProfileName(_ value: String) -> String {
        let forbidden = CharacterSet(charactersIn: "/:")
        let clean = value
            .components(separatedBy: forbidden)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return clean.isEmpty ? "资料" : String(clean.prefix(50))
    }

    func normalizedArgs(for profile: Profile) -> [String] {
        let replacedPrefixes = [
            "--fingerprint-platform=",
            "--fingerprint-brand-version=",
            "--user-agent=",
            "--window-size=",
            "--force-device-scale-factor=",
            "--fingerprint-hardware-concurrency=",
            "--disable-non-proxied-udp",
            "--load-extension=",
        ]
        var args = profile.args.filter { arg in
            !replacedPrefixes.contains { prefix in arg == prefix || arg.hasPrefix(prefix) }
        }
        if let config = profile.fingerprintConfig {
            args = fingerprintArgs(config) + args
        }
        return args
    }

    func rebuildBootstrapExtension(profileURL: URL, cookieText: String) throws {
        let extensionURL = profileURL.appendingPathComponent("bootstrap_extension")
        if FileManager.default.fileExists(atPath: extensionURL.path) {
            try FileManager.default.removeItem(at: extensionURL)
        }
        try FileManager.default.createDirectory(at: extensionURL, withIntermediateDirectories: true)
        let manifest: [String: Any] = [
            "manifest_version": 3,
            "name": "资料启动助手",
            "version": "1.0",
            "permissions": ["cookies", "storage"],
            "host_permissions": ["<all_urls>"],
            "background": ["service_worker": "worker.js"],
            "content_scripts": [[
                "matches": ["<all_urls>"],
                "js": ["content.js"],
                "run_at": "document_start",
            ]],
        ]
        let manifestData = try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted])
        try manifestData.write(to: extensionURL.appendingPathComponent("manifest.json"))
        let importID = sha256Hex(cookieText)
        let worker = """
        const cookies = \(cookieText.isEmpty ? "[]" : cookieText);
        const importId = "\(importID)";
        const importKey = "cookie-import:" + importId;

        function cookieUrl(cookie) {
          if (cookie.url) return cookie.url;
          const domain = String(cookie.domain || "").replace(/^\\./, "");
          if (!domain) return null;
          const scheme = cookie.secure === false ? "http" : "https";
          const path = cookie.path || "/";
          return `${scheme}://${domain}${path}`;
        }

        async function importCookies() {
          for (const source of cookies) {
            const cookie = { ...source };
            cookie.url = cookieUrl(cookie);
            if (!cookie.url || !cookie.name) continue;
            delete cookie.hostOnly;
            delete cookie.session;
            delete cookie.storeId;
            try {
              await chrome.cookies.set(cookie);
            } catch (error) {
              console.warn("Cookie import failed", cookie.name, error);
            }
          }
        }

        async function boot() {
          const state = await chrome.storage.local.get(importKey);
          if (state[importKey]) return;
          await importCookies();
          await chrome.storage.local.set({ [importKey]: true });
        }
        chrome.runtime.onInstalled.addListener(boot);
        chrome.runtime.onStartup.addListener(boot);
        chrome.runtime.onMessage.addListener((message) => {
          if (message && message.type === "import-cookies") {
            boot();
          }
        });
        """
        try worker.write(to: extensionURL.appendingPathComponent("worker.js"), atomically: true, encoding: .utf8)
        try #"chrome.runtime.sendMessage({ type: "import-cookies" }).catch(() => {});"#
            .write(to: extensionURL.appendingPathComponent("content.js"), atomically: true, encoding: .utf8)
    }

    func sha256Hex(_ value: String) -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/shasum")
        process.arguments = ["-a", "256"]
        let input = Pipe()
        let output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        do {
            try process.run()
            input.fileHandleForWriting.write(Data(value.utf8))
            input.fileHandleForWriting.closeFile()
            process.waitUntilExit()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let text = String(data: data, encoding: .utf8) ?? ""
            return text.split(separator: " ").first.map(String.init) ?? "\(abs(value.hashValue))"
        } catch {
            return "\(abs(value.hashValue))"
        }
    }

    func jsonArray(_ values: [String]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: values, options: [])) ?? Data("[]".utf8)
        return String(data: data, encoding: .utf8) ?? "[]"
    }

    func normalizedOpenURL(_ value: String) -> String {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            return ""
        }
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") || trimmed.hasPrefix("chrome-extension://") {
            return trimmed
        }
        if trimmed.contains("://") {
            return trimmed
        }
        return "https://\(trimmed)"
    }

    func localizedProfileName(_ name: String) -> String {
        if name.hasPrefix("Fingerprint ") {
            return "资料 " + name.dropFirst("Fingerprint ".count)
        }
        return name
    }

    func open(_ profile: Profile) {
        try? rebuildLauncher(for: profile)
        let config = NSWorkspace.OpenConfiguration()
        config.createsNewApplicationInstance = true
        NSWorkspace.shared.openApplication(at: URL(fileURLWithPath: profile.appPath), configuration: config)
    }

    func runningWindows() -> [String: WindowState] {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["wwaxo", "pid=,command="]
        let pipe = Pipe()
        process.standardOutput = pipe
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return [:]
        }

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8) else { return [:] }

        var result: [String: WindowState] = [:]
        for line in output.split(separator: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            let parts = trimmed.split(separator: " ", maxSplits: 1)
            guard
                parts.count == 2,
                let pid = Int32(parts[0]),
                parts[1].contains("/Contents/MacOS/Chromium"),
                !parts[1].contains("Chromium Helper")
            else {
                continue
            }

            let command = String(parts[1])
            guard let path = logicalProfilePath(from: command) else { continue }
            if !path.isEmpty {
                result[path] = WindowState(pid: pid, profilePath: path, command: command)
            }
        }
        return result
    }

    func logicalProfilePath(from command: String) -> String? {
        extractUserDataDir(from: command).map(canonicalPath)
    }

    func canonicalPath(_ path: String) -> String {
        URL(fileURLWithPath: path).standardizedFileURL.path
    }

    func extractUserDataDir(from command: String) -> String? {
        extractArgument("--user-data-dir=", from: command)
    }

    func extractArgument(_ prefix: String, from command: String) -> String? {
        guard let range = command.range(of: prefix) else { return nil }
        var after = String(command[range.upperBound...])
        if after.hasPrefix("\"") {
            after.removeFirst()
            return after.split(separator: "\"", maxSplits: 1).first.map(String.init)
        }
        if after.hasPrefix("'") {
            after.removeFirst()
            return after.split(separator: "'", maxSplits: 1).first.map(String.init)
        }
        return after.split(separator: " ", maxSplits: 1).first.map(String.init)
    }

    func close(_ state: WindowState) {
        kill(state.pid, SIGTERM)
    }

    func forceClose(_ state: WindowState) {
        kill(state.pid, SIGKILL)
    }

    func clearCache(_ profile: Profile) throws {
        let profileURL = URL(fileURLWithPath: profile.profilePath)
        if FileManager.default.fileExists(atPath: profileURL.path) {
            try FileManager.default.removeItem(at: profileURL)
        }
        try FileManager.default.createDirectory(at: profileURL, withIntermediateDirectories: true)
    }

    func delete(_ profile: Profile, from profiles: [Profile]) throws -> [Profile] {
        try deleteFiles(for: profile)
        let updated = profiles.filter { $0.number != profile.number }
        save(updated)
        return updated
    }

    func deleteFiles(for profile: Profile) throws {
        let appURL = URL(fileURLWithPath: profile.appPath)
        let profileURL = URL(fileURLWithPath: profile.profilePath)
        if FileManager.default.fileExists(atPath: appURL.path) {
            try FileManager.default.removeItem(at: appURL)
        }
        if FileManager.default.fileExists(atPath: profileURL.path) {
            try FileManager.default.removeItem(at: profileURL)
        }
    }
}

extension JSONEncoder {
    static var pretty: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSTableViewDataSource, NSTableViewDelegate {
    var window: NSWindow!
    var tableView: NSTableView!
    var profiles: [Profile] = []
    var filteredProfiles: [Profile] = []
    var running: [String: WindowState] = [:]
    var manager: ProfileManager!
    var apiProcess: Process?
    var filterMode = "all"
    var sharedExtensions: [String] = []

    let sourceField = NSTextField(string: "")
    let appNameField = NSTextField(string: "资料")
    let seedField = NSTextField(string: "10000")
    let langField = NSTextField(string: "zh-CN")
    let timezoneField = NSTextField(string: "Asia/Shanghai")
    let proxyField = NSTextField(string: "")
    let extraArgsView = NSTextView()
    let searchField = NSSearchField()
    let statsLabel = NSTextField(labelWithString: "")
    var createNameField: NSTextField?
    var createProxyField: NSTextField?
    var createLangField: NSTextField?
    var createTimezoneField: NSTextField?
    var createRemarkView: NSTextView?
    var createCookieView: NSTextView?
    var createUrlsView: NSTextView?
    var createArgsView: NSTextView?
    var createPlatformField: NSTextField?
    var createChromeVersionField: NSTextField?
    var createUAView: NSTextView?
    var createWidthField: NSTextField?
    var createHeightField: NSTextField?
    var createDPRField: NSTextField?
    var createCPUField: NSTextField?
    var createMemoryField: NSTextField?
    var createWebRTCField: NSTextField?
    var createSeedField: NSTextField?
    var createDisplayNumberField: NSTextField?
    var batchCountField: NSTextField?
    var batchNameField: NSTextField?
    var editJSONView: NSTextView?
    var editingProfileNumber: Int?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let appURL = Bundle.main.bundleURL
        let dataRoot = ProfileManager.defaultDataRoot()
        let runtimeRoot = appURL.appendingPathComponent("Contents/Resources/runtime")
        manager = ProfileManager(dataRoot: dataRoot, runtimeRoot: runtimeRoot)
        sourceField.stringValue = manager.defaultBrowserAppPath()
        profiles = manager.load().sorted { $0.number < $1.number }
        sharedExtensions = manager.loadSharedExtensions()
        filteredProfiles = profiles
        buildWindow()
        refreshWindowsAsync()
    }

    func buildWindow() {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1320, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "指纹浏览器"
        window.center()

        let root = NSStackView()
        root.orientation = .horizontal
        root.spacing = 0
        root.translatesAutoresizingMaskIntoConstraints = false
        window.contentView?.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor),
            root.topAnchor.constraint(equalTo: window.contentView!.topAnchor),
            root.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor),
        ])

        root.addArrangedSubview(sidebarView())
        root.addArrangedSubview(mainView())

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func sidebarView() -> NSView {
        let sidebar = NSStackView()
        sidebar.orientation = .vertical
        sidebar.spacing = 12
        sidebar.edgeInsets = NSEdgeInsets(top: 18, left: 14, bottom: 18, right: 14)
        sidebar.wantsLayer = true
        sidebar.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        sidebar.widthAnchor.constraint(equalToConstant: 228).isActive = true

        let title = NSTextField(labelWithString: "指纹浏览器")
        title.font = .systemFont(ofSize: 22, weight: .semibold)
        title.textColor = .labelColor
        sidebar.addArrangedSubview(title)

        let subtitle = NSTextField(labelWithString: "本地资料管理")
        subtitle.font = .systemFont(ofSize: 12)
        subtitle.textColor = .secondaryLabelColor
        sidebar.addArrangedSubview(subtitle)

        sidebar.addArrangedSubview(spacer(height: 10))

        let filterTitle = NSTextField(labelWithString: "筛选")
        filterTitle.font = .systemFont(ofSize: 11, weight: .semibold)
        filterTitle.textColor = .secondaryLabelColor
        sidebar.addArrangedSubview(filterTitle)
        sidebar.addArrangedSubview(groupItem("全部窗口", count: profiles.count, selected: filterMode == "all"))
        sidebar.addArrangedSubview(groupItem("已打开", count: profiles.filter { running[$0.profilePath] != nil }.count, selected: filterMode == "opened"))
        sidebar.addArrangedSubview(groupItem("未打开", count: profiles.filter { running[$0.profilePath] == nil }.count, selected: filterMode == "closed"))

        sidebar.addArrangedSubview(spacer(height: 14))

        let infoTitle = NSTextField(labelWithString: "信息")
        infoTitle.font = .systemFont(ofSize: 11, weight: .semibold)
        infoTitle.textColor = .secondaryLabelColor
        sidebar.addArrangedSubview(infoTitle)
        sidebar.addArrangedSubview(sidebarInfoLabel("当前模式", value: "独立资料目录"))
        sidebar.addArrangedSubview(sidebarInfoLabel("浏览器来源", value: manager.browserDisplayName()))
        sidebar.addArrangedSubview(sidebarInfoLabel("资料数量", value: "\(profiles.count)"))

        sidebar.addArrangedSubview(NSView())

        return sidebar
    }
    
    func groupItem(_ title: String, count: Int, selected: Bool) -> NSView {
        let container = NSView()
        container.translatesAutoresizingMaskIntoConstraints = false
        container.heightAnchor.constraint(equalToConstant: 28).isActive = true

        let button = NSButton(title: title, target: self, action: actionForFilterTitle(title))
        button.frame = NSRect(x: 0, y: 0, width: 180, height: 28)
        button.isBordered = false
        button.setButtonType(.momentaryPushIn)
        button.bezelStyle = .recessed
        button.font = .systemFont(ofSize: 13, weight: selected ? .semibold : .regular)
        button.alignment = .left
        button.contentTintColor = selected ? .controlAccentColor : .labelColor
        container.addSubview(button)

        let countField = NSTextField(labelWithString: "\(count)")
        countField.font = .systemFont(ofSize: 12, weight: .medium)
        countField.textColor = selected ? .controlAccentColor : .secondaryLabelColor
        countField.alignment = .right
        countField.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(countField)

        NSLayoutConstraint.activate([
            button.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            button.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            button.topAnchor.constraint(equalTo: container.topAnchor),
            button.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            countField.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            countField.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -4),
            countField.widthAnchor.constraint(equalToConstant: 28),
        ])

        return container
    }

    func sidebarInfoLabel(_ title: String, value: String) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .firstBaseline
        row.distribution = .fill
        row.spacing = 6

        let titleField = NSTextField(labelWithString: title)
        titleField.textColor = .secondaryLabelColor
        titleField.font = .systemFont(ofSize: 11)
        titleField.setContentHuggingPriority(.defaultHigh, for: .horizontal)
        row.addArrangedSubview(titleField)

        let flexible = NSView()
        flexible.setContentHuggingPriority(.defaultLow, for: .horizontal)
        flexible.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        row.addArrangedSubview(flexible)

        let valueField = NSTextField(labelWithString: value)
        valueField.textColor = .labelColor
        valueField.font = .systemFont(ofSize: 11, weight: .medium)
        valueField.alignment = .right
        valueField.lineBreakMode = .byTruncatingMiddle
        valueField.setContentHuggingPriority(.required, for: .horizontal)
        valueField.setContentCompressionResistancePriority(.required, for: .horizontal)
        row.addArrangedSubview(valueField)
        return row
    }

    func actionForFilterTitle(_ title: String) -> Selector {
        switch title {
        case "已打开":
            return #selector(filterOpened)
        case "未打开":
            return #selector(filterClosed)
        default:
            return #selector(showAllFilter)
        }
    }
    
    func spacer(height: CGFloat) -> NSView {
        let view = NSView()
        view.heightAnchor.constraint(equalToConstant: height).isActive = true
        return view
    }

    func spacer(width: CGFloat) -> NSView {
        let view = NSView()
        view.widthAnchor.constraint(equalToConstant: width).isActive = true
        return view
    }

    func mainView() -> NSView {
        let main = NSStackView()
        main.orientation = .vertical
        main.spacing = 14
        main.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        main.wantsLayer = true
        main.layer?.backgroundColor = NSColor(calibratedWhite: 0.95, alpha: 1).cgColor
        main.addArrangedSubview(topBarView())
        main.addArrangedSubview(toolbarView())
        main.addArrangedSubview(tablePanelView())
        return main
    }

    func topBarView() -> NSView {
        let bar = NSStackView()
        bar.orientation = .horizontal
        bar.spacing = 12
        bar.edgeInsets = NSEdgeInsets(top: 16, left: 18, bottom: 16, right: 18)
        bar.wantsLayer = true
        bar.layer?.backgroundColor = NSColor.white.cgColor
        bar.layer?.cornerRadius = 14

        let title = NSTextField(labelWithString: "浏览器窗口")
        title.font = .boldSystemFont(ofSize: 22)
        bar.addArrangedSubview(title)

        let subtitle = NSTextField(labelWithString: "创建、管理并重新打开独立资料窗口")
        subtitle.textColor = .secondaryLabelColor
        subtitle.font = .systemFont(ofSize: 12)
        bar.addArrangedSubview(subtitle)

        bar.addArrangedSubview(NSView())

        statsLabel.textColor = .secondaryLabelColor
        statsLabel.font = .systemFont(ofSize: 12, weight: .medium)
        updateStats()
        bar.addArrangedSubview(statsLabel)
        return bar
    }

    func toolbarView() -> NSView {
        let outer = NSStackView()
        outer.orientation = .vertical
        outer.spacing = 12
        outer.edgeInsets = NSEdgeInsets(top: 14, left: 16, bottom: 14, right: 16)
        outer.wantsLayer = true
        outer.layer?.backgroundColor = NSColor.white.cgColor
        outer.layer?.cornerRadius = 14

        let firstRow = NSStackView()
        firstRow.orientation = .horizontal
        firstRow.spacing = 8
        firstRow.alignment = .centerY
        firstRow.addArrangedSubview(sectionLabel("创建"))
        firstRow.addArrangedSubview(primaryButton("新建窗口", #selector(showCreateProfileDialog)))
        firstRow.addArrangedSubview(button("批量创建", #selector(showBatchCreateDialog)))
        firstRow.addArrangedSubview(spacer(width: 14))
        firstRow.addArrangedSubview(sectionLabel("批量"))
        firstRow.addArrangedSubview(button("打开全部", #selector(openAllProfiles)))
        firstRow.addArrangedSubview(button("关闭全部", #selector(closeAllProfiles)))
        firstRow.addArrangedSubview(button("刷新", #selector(refreshWindows)))
        firstRow.addArrangedSubview(NSView())
        searchField.placeholderString = "搜索名称 / 序号 / 备注 / 网址"
        searchField.target = self
        searchField.action = #selector(searchChanged)
        searchField.controlSize = .large
        searchField.widthAnchor.constraint(equalToConstant: 260).isActive = true
        firstRow.addArrangedSubview(searchField)
        outer.addArrangedSubview(firstRow)

        let secondRow = NSStackView()
        secondRow.orientation = .horizontal
        secondRow.spacing = 8
        secondRow.alignment = .centerY
        secondRow.addArrangedSubview(sectionLabel("选中"))
        secondRow.addArrangedSubview(button("打开", #selector(openSelected)))
        secondRow.addArrangedSubview(button("关闭", #selector(closeSelected)))
        secondRow.addArrangedSubview(button("编辑", #selector(editSelected)))
        secondRow.addArrangedSubview(button("重置资料", #selector(clearSelectedCache)))
        secondRow.addArrangedSubview(button("删除", #selector(deleteSelected)))
        secondRow.addArrangedSubview(spacer(width: 14))
        secondRow.addArrangedSubview(sectionLabel("工具"))
        secondRow.addArrangedSubview(button("导入", #selector(importProfiles)))
        secondRow.addArrangedSubview(button("导出", #selector(exportProfiles)))
        secondRow.addArrangedSubview(button("扩展管理", #selector(showSharedExtensionsDialog)))
        secondRow.addArrangedSubview(button("API 服务", #selector(toggleApiServer)))
        secondRow.addArrangedSubview(button("指纹检测", #selector(openFingerprintCheck)))
        secondRow.addArrangedSubview(NSView())
        outer.addArrangedSubview(secondRow)
        
        return outer
    }

    func tablePanelView() -> NSView {
        let panel = NSStackView()
        panel.orientation = .vertical
        panel.spacing = 8
        panel.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 12, right: 12)
        panel.wantsLayer = true
        panel.layer?.backgroundColor = NSColor.white.cgColor
        panel.layer?.cornerRadius = 14

        let tabs = NSStackView()
        tabs.orientation = .horizontal
        tabs.spacing = 8
        tabs.addArrangedSubview(sectionLabel("筛选"))
        tabs.addArrangedSubview(primaryButton("全部", #selector(showAllFilter)))
        tabs.addArrangedSubview(button("已打开", #selector(filterOpened)))
        tabs.addArrangedSubview(button("未打开", #selector(filterClosed)))
        tabs.addArrangedSubview(NSView())
        tabs.addArrangedSubview(button("在访达中显示", #selector(revealSelected)))
        panel.addArrangedSubview(tabs)

        tableView = NSTableView()
        tableView.delegate = self
        tableView.dataSource = self
        tableView.rowHeight = 34
        tableView.usesAlternatingRowBackgroundColors = true
        tableView.columnAutoresizingStyle = .noColumnAutoresizing
        tableView.allowsColumnReordering = false
        tableView.allowsColumnResizing = false
        tableView.intercellSpacing = NSSize(width: 6, height: 2)
        addColumn("number", "序号", 54)
        addColumn("name", "窗口名称", 154)
        addColumn("status", "状态", 62)
        addColumn("site", "打开网址", 188)
        addColumn("proxy", "代理", 124)
        addColumn("remark", "备注", 128)
        addColumn("details", "详情", 224)
        addColumn("actions", "操作", 118)
        tableView.doubleAction = #selector(openSelected)
        tableView.headerView?.wantsLayer = true

        let scroll = NSScrollView()
        scroll.documentView = tableView
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.borderType = .noBorder
        panel.addArrangedSubview(scroll)

        return panel
    }

    func addColumn(_ identifier: String, _ title: String, _ width: CGFloat) {
        let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(identifier))
        column.title = title
        column.width = width
        column.minWidth = width
        column.maxWidth = width
        column.resizingMask = []
        tableView.addTableColumn(column)
    }

    func label(_ text: String) -> NSTextField {
        let field = NSTextField(labelWithString: text)
        field.alignment = .left
        return field
    }

    func button(_ title: String, _ action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        return button
    }

    func primaryButton(_ title: String, _ action: Selector) -> NSButton {
        let button = button(title, action)
        button.contentTintColor = NSColor(calibratedRed: 0.08, green: 0.27, blue: 0.95, alpha: 1)
        return button
    }

    func sectionLabel(_ text: String) -> NSTextField {
        let field = NSTextField(labelWithString: text)
        field.font = .systemFont(ofSize: 11, weight: .semibold)
        field.textColor = .secondaryLabelColor
        return field
    }

    func menuItem(_ title: String) -> NSTextField {
        let field = NSTextField(labelWithString: title)
        field.textColor = NSColor.white.withAlphaComponent(0.82)
        field.font = .systemFont(ofSize: 14)
        field.heightAnchor.constraint(equalToConstant: 34).isActive = true
        return field
    }

    func selectedMenuItem(_ title: String) -> NSTextField {
        let field = menuItem("  \(title)")
        field.textColor = .white
        field.font = .boldSystemFont(ofSize: 14)
        field.wantsLayer = true
        field.layer?.backgroundColor = NSColor(calibratedRed: 0.06, green: 0.18, blue: 0.72, alpha: 1).cgColor
        field.layer?.cornerRadius = 7
        return field
    }

    func updateStats() {
        let opened = profiles.filter { running[$0.profilePath] != nil }.count
        statsLabel.stringValue = "已用 \(profiles.count) / 总数 \(profiles.count)    已打开 \(opened)"
    }

    func applyFilter() {
        let keyword = searchField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if keyword.isEmpty {
            filteredProfiles = profiles
        } else {
            filteredProfiles = profiles.filter {
                $0.name.localizedCaseInsensitiveContains(keyword)
                    || ($0.remark ?? "").localizedCaseInsensitiveContains(keyword)
                    || ($0.proxy ?? "").localizedCaseInsensitiveContains(keyword)
                    || ($0.openUrls ?? []).joined(separator: " ").localizedCaseInsensitiveContains(keyword)
                    || "\($0.displayNumber ?? $0.number)".contains(keyword)
                    || "\($0.number)".contains(keyword)
                    || "\($0.fingerprint)".contains(keyword)
            }
        }
        if filterMode == "opened" {
            filteredProfiles = filteredProfiles.filter { running[$0.profilePath] != nil }
        } else if filterMode == "closed" {
            filteredProfiles = filteredProfiles.filter { running[$0.profilePath] == nil }
        }
        updateStats()
        tableView?.reloadData()
    }

    func numberOfRows(in tableView: NSTableView) -> Int {
        filteredProfiles.count
    }

    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let id = tableColumn?.identifier.rawValue ?? ""
        let profile = filteredProfiles[row]
        let value: String
        switch id {
        case "number": value = "\(profile.displayNumber ?? profile.number)"
        case "name": value = profile.name
        case "status": value = running[profile.profilePath] == nil ? "未开" : "运行"
        case "site": value = profile.openUrls?.first ?? "-"
        case "proxy": value = profile.proxy?.isEmpty == false ? profile.proxy! : "直连"
        case "remark": value = profile.remark?.isEmpty == false ? profile.remark! : "-"
        case "details":
            let pid = running[profile.profilePath].map { " PID:\($0.pid)" } ?? ""
            if let config = profile.fingerprintConfig {
                value = "独立资料  \(config.platform)  \(config.width)x\(config.height)  指纹:\(profile.fingerprint)\(pid)"
            } else {
                value = "独立资料  指纹:\(profile.fingerprint)\(pid)"
            }
        case "actions":
            return actionCell(row: row, isRunning: running[profile.profilePath] != nil)
        default: value = "-"
        }
        let cell = NSTextField(labelWithString: value)
        cell.lineBreakMode = .byTruncatingMiddle
        cell.toolTip = value
        if id == "status" {
            cell.textColor = running[profile.profilePath] == nil ? .secondaryLabelColor : NSColor.systemGreen
            cell.font = .boldSystemFont(ofSize: 12)
        }
        return cell
    }

    func actionCell(row: Int, isRunning: Bool) -> NSView {
        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.spacing = 6
        stack.alignment = .centerY

        let open = NSButton(title: isRunning ? "关闭" : "打开", target: self, action: isRunning ? #selector(closeRowButton(_:)) : #selector(openRowButton(_:)))
        open.bezelStyle = .rounded
        open.tag = row
        open.controlSize = .small
        stack.addArrangedSubview(open)

        let edit = NSButton(title: "编辑", target: self, action: #selector(editRowButton(_:)))
        edit.bezelStyle = .rounded
        edit.tag = row
        edit.controlSize = .small
        stack.addArrangedSubview(edit)
        return stack
    }

    @objc func searchChanged() {
        applyFilter()
    }

    @objc func showAllFilter() {
        filterMode = "all"
        applyFilter()
    }

    @objc func filterOpened() {
        filterMode = "opened"
        applyFilter()
    }

    @objc func filterClosed() {
        filterMode = "closed"
        applyFilter()
    }

    @objc func chooseApp() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: "/Applications")
        if panel.runModal() == .OK, let url = panel.url {
            sourceField.stringValue = url.path
        }
    }

    @objc func toggleApiServer() {
        if let process = apiProcess, process.isRunning {
            process.terminate()
            apiProcess = nil
            alert("本地 API 已关闭")
            return
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.currentDirectoryURL = manager.dataRoot
        process.arguments = [manager.runtimeRoot.appendingPathComponent("tools/local_api.py").path]
        var env = ProcessInfo.processInfo.environment
        env["FINGERPRINT_API_KEY"] = "local-dev-key"
        env["FINGERPRINT_API_PORT"] = "18787"
        env["FINGERPRINT_DATA_ROOT"] = manager.dataRoot.path
        process.environment = env
        do {
            try process.run()
            apiProcess = process
            alert("本地 API 已启动：http://127.0.0.1:18787\n请求头：X-API-Key: local-dev-key")
        } catch {
            alert(error.localizedDescription)
        }
    }

    @objc func openFingerprintCheck() {
        let urls = [
            "https://browserleaks.com/",
            "https://pixelscan.net/",
        ]
        for url in urls {
            NSWorkspace.shared.open(URL(string: url)!)
        }
    }

    @objc func showCreateProfileDialog() {
        editingProfileNumber = nil
        showProfileForm(profile: nil)
    }

    func showProfileForm(profile: Profile?) {
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 920, height: 700),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        panel.title = profile == nil ? "创建窗口" : "编辑环境"
        panel.center()

        createNameField = NSTextField(string: profile?.name ?? appNameField.stringValue)
        createProxyField = NSTextField(string: profile?.proxy ?? proxyField.stringValue)
        createLangField = NSTextField(string: langField.stringValue)
        createTimezoneField = NSTextField(string: timezoneField.stringValue)
        createSeedField = NSTextField(string: profile.map { "\($0.fingerprint)" } ?? seedField.stringValue)
        createDisplayNumberField = NSTextField(string: profile.map { "\($0.displayNumber ?? $0.number)" } ?? "")

        let defaults = profile?.fingerprintConfig ?? manager.defaultFingerprintConfig()
        createPlatformField = NSTextField(string: defaults.platform)
        createChromeVersionField = NSTextField(string: defaults.chromeVersion)
        createWidthField = NSTextField(string: "\(defaults.width)")
        createHeightField = NSTextField(string: "\(defaults.height)")
        createDPRField = NSTextField(string: defaults.deviceScaleFactor)
        createCPUField = NSTextField(string: "\(defaults.cpuCores)")
        createMemoryField = NSTextField(string: "\(defaults.memoryGB)")
        createWebRTCField = NSTextField(string: defaults.webRTCPolicy)
        createUAView = textArea("User Agent")
        createUAView?.string = defaults.userAgent
        createRemarkView = textArea("请填写浏览器窗口备注")
        createRemarkView?.string = profile?.remark ?? ""
        createCookieView = textArea("选填，支持数组 JSON 格式 Cookie")
        createCookieView?.string = profile?.cookieJSON ?? ""
        createUrlsView = textArea("每行一个网址，请加 http://、https:// 或 chrome-extension://")
        createUrlsView?.string = (profile?.openUrls ?? []).joined(separator: "\n")
        createArgsView = textArea("每行一个启动参数")
        createArgsView?.string = profile?.args.joined(separator: "\n") ?? extraArgsView.string

        let tabs = NSTabView()
        tabs.frame = NSRect(x: 24, y: 84, width: 872, height: 582)
        tabs.tabViewType = .topTabsBezelBorder
        tabs.addTabViewItem(tabItem("基础设置", basicCreatePage()))
        tabs.addTabViewItem(tabItem("指纹设置", fingerprintCreatePage()))
        tabs.addTabViewItem(tabItem("Cookie 与网址", cookieCreatePage()))
        tabs.addTabViewItem(tabItem("启动参数", argsCreatePage()))
        panel.contentView?.addSubview(tabs)

        let cancel = button("取消", #selector(closeCreateDialog(_:)))
        cancel.frame = NSRect(x: 724, y: 28, width: 76, height: 32)
        panel.contentView?.addSubview(cancel)
        let create = primaryButton(profile == nil ? "创建并打开" : "保存", #selector(createProfileFromDialog(_:)))
        create.frame = NSRect(x: 808, y: 28, width: 88, height: 32)
        panel.contentView?.addSubview(create)

        window.beginSheet(panel)
    }

    func tabItem(_ title: String, _ view: NSView) -> NSTabViewItem {
        let item = NSTabViewItem(identifier: title)
        item.label = title
        item.view = view
        return item
    }

    func basicCreatePage() -> NSView {
        let page = FixedPage(frame: NSRect(x: 0, y: 0, width: 872, height: 582))
        addFormRow(page, y: 28, leftLabel: "窗口名称", leftField: createNameField!, rightLabel: "标签", rightField: disabledField("默认"))
        addFormRow(page, y: 80, leftLabel: "选择分组", leftField: disabledField("默认分组"), rightLabel: "隔离方式", rightField: disabledField("独立资料目录"))
        addFormRow(page, y: 132, leftLabel: "代理设置", leftField: createProxyField!, rightLabel: "语言", rightField: createLangField!)
        addFormRow(page, y: 184, leftLabel: "时区", leftField: createTimezoneField!, rightLabel: "图标序号", rightField: createDisplayNumberField!)
        addFormRow(page, y: 236, leftLabel: "指纹种子", leftField: createSeedField!, rightLabel: "多开设置", rightField: disabledField("允许"))
        addTextBlock(page, title: "备注", textView: createRemarkView!, y: 308, height: 180)
        return page
    }

    func fingerprintCreatePage() -> NSView {
        let page = FixedPage(frame: NSRect(x: 0, y: 0, width: 872, height: 582))
        addFormRow(page, y: 28, leftLabel: "操作系统", leftField: createPlatformField!, rightLabel: "浏览器版本", rightField: createChromeVersionField!)
        addFormRow(page, y: 80, leftLabel: "窗口宽度", leftField: createWidthField!, rightLabel: "窗口高度", rightField: createHeightField!)
        addFormRow(page, y: 132, leftLabel: "DPR", leftField: createDPRField!, rightLabel: "WebRTC", rightField: createWebRTCField!)
        addFormRow(page, y: 184, leftLabel: "CPU 核数", leftField: createCPUField!, rightLabel: "设备内存 GB", rightField: createMemoryField!)
        addTextBlock(page, title: "User Agent", textView: createUAView!, y: 256, height: 200)
        return page
    }

    func cookieCreatePage() -> NSView {
        let page = FixedPage(frame: NSRect(x: 0, y: 0, width: 872, height: 582))
        addTextBlock(page, title: "Cookie", textView: createCookieView!, y: 28, height: 220)
        addTextBlock(page, title: "打开指定网址", textView: createUrlsView!, y: 310, height: 170)
        return page
    }

    func argsCreatePage() -> NSView {
        let page = FixedPage(frame: NSRect(x: 0, y: 0, width: 872, height: 582))
        addTextBlock(page, title: "启动参数", textView: createArgsView!, y: 28, height: 430)
        return page
    }

    func addFormRow(_ page: NSView, y: CGFloat, leftLabel: String, leftField: NSView, rightLabel: String, rightField: NSView) {
        let labelWidth: CGFloat = 82
        let fieldWidth: CGFloat = 270
        let rowHeight: CGFloat = 32
        addFixedLabel(leftLabel, to: page, frame: NSRect(x: 30, y: y + 6, width: labelWidth, height: 20))
        leftField.frame = NSRect(x: 120, y: y, width: fieldWidth, height: rowHeight)
        page.addSubview(leftField)
        addFixedLabel(rightLabel, to: page, frame: NSRect(x: 430, y: y + 6, width: labelWidth, height: 20))
        rightField.frame = NSRect(x: 522, y: y, width: fieldWidth, height: rowHeight)
        page.addSubview(rightField)
    }

    func addTextBlock(_ page: NSView, title: String, textView: NSTextView, y: CGFloat, height: CGFloat) {
        addFixedLabel(title, to: page, frame: NSRect(x: 30, y: y, width: 160, height: 20), alignment: .left)
        let scroll = NSScrollView(frame: NSRect(x: 30, y: y + 30, width: 762, height: height))
        scroll.documentView = textView
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        page.addSubview(scroll)
    }

    func addFixedLabel(_ text: String, to page: NSView, frame: NSRect, alignment: NSTextAlignment = .right) {
        let field = NSTextField(labelWithString: text)
        field.alignment = alignment
        field.frame = frame
        page.addSubview(field)
    }

    func disabledField(_ text: String) -> NSTextField {
        let field = NSTextField(string: text)
        field.isEnabled = false
        return field
    }

    func textArea(_ tooltip: String) -> NSTextView {
        let view = NSTextView()
        view.font = .systemFont(ofSize: 13)
        view.toolTip = tooltip
        return view
    }

    func textSection(_ title: String, _ view: NSTextView, height: CGFloat) -> NSView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.spacing = 4
        stack.addArrangedSubview(label(title))
        let scroll = NSScrollView()
        scroll.documentView = view
        scroll.hasVerticalScroller = true
        scroll.heightAnchor.constraint(equalToConstant: height).isActive = true
        stack.addArrangedSubview(scroll)
        return stack
    }

    @objc func closeCreateDialog(_ sender: NSButton) {
        if let panel = sender.window as? NSPanel {
            window.endSheet(panel)
            panel.close()
        }
    }

    @objc func createProfileFromDialog(_ sender: NSButton) {
        if let panel = sender.window as? NSPanel {
            window.endSheet(panel)
            panel.close()
        }
        if editingProfileNumber == nil {
            createProfile()
        } else {
            saveProfileFromForm()
        }
    }

    @objc func showBatchCreateDialog() {
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 220),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        panel.title = "批量创建"
        panel.center()

        let root = NSStackView()
        root.orientation = .vertical
        root.spacing = 12
        root.edgeInsets = NSEdgeInsets(top: 16, left: 18, bottom: 16, right: 18)
        root.translatesAutoresizingMaskIntoConstraints = false
        panel.contentView?.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: panel.contentView!.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: panel.contentView!.trailingAnchor),
            root.topAnchor.constraint(equalTo: panel.contentView!.topAnchor),
            root.bottomAnchor.constraint(equalTo: panel.contentView!.bottomAnchor),
        ])

        batchNameField = NSTextField(string: appNameField.stringValue.isEmpty ? "资料" : appNameField.stringValue)
        batchCountField = NSTextField(string: "5")
        let grid = NSGridView(views: [
            [label("名称前缀"), batchNameField!],
            [label("创建数量"), batchCountField!],
            [label("说明"), label("批量创建不会自动打开窗口")],
        ])
        grid.rowSpacing = 10
        grid.columnSpacing = 10
        grid.column(at: 1).xPlacement = .fill
        root.addArrangedSubview(grid)

        let footer = NSStackView()
        footer.orientation = .horizontal
        footer.spacing = 10
        footer.addArrangedSubview(NSView())
        footer.addArrangedSubview(button("取消", #selector(closeCreateDialog(_:))))
        footer.addArrangedSubview(primaryButton("开始创建", #selector(batchCreateFromDialog(_:))))
        root.addArrangedSubview(footer)
        window.beginSheet(panel)
    }

    @objc func batchCreateFromDialog(_ sender: NSButton) {
        if let panel = sender.window as? NSPanel {
            window.endSheet(panel)
            panel.close()
        }
        let count = max(1, min(100, Int(batchCountField?.stringValue ?? "1") ?? 1))
        let name = batchNameField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? "资料"
        do {
            profiles = manager.load().sorted { $0.number < $1.number }
            for _ in 0..<count {
                let config = manager.defaultFingerprintConfig()
                let profile = try manager.createProfile(
                    currentProfiles: profiles,
                    sourceApp: sourceField.stringValue,
                    appName: name.isEmpty ? "资料" : name,
                    displayNumber: nil,
                    seedBase: Int(seedField.stringValue) ?? 10000,
                    language: langField.stringValue,
                    timezone: timezoneField.stringValue,
                    proxy: proxyField.stringValue,
                    extraArgs: extraArgsView.string,
                    cookieText: "",
                    openUrls: [],
                    remark: "批量创建",
                    fingerprintConfig: config
                )
                profiles.append(profile)
                profiles.sort { $0.number < $1.number }
                try manager.updateIcon(for: profile)
                manager.save(profiles)
            }
            applyFilter()
        } catch {
            alert(error.localizedDescription)
        }
    }

    @objc func createProfile() {
        do {
            profiles = manager.load().sorted { $0.number < $1.number }
            let windowName = createNameField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? appNameField.stringValue
            let proxy = createProxyField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? proxyField.stringValue
            let language = createLangField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? langField.stringValue
            let timezone = createTimezoneField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? timezoneField.stringValue
            let urls = (createUrlsView?.string ?? "")
                .split(separator: "\n")
                .map { manager.normalizedOpenURL(String($0)) }
                .filter { !$0.isEmpty }
            let args = createArgsView?.string ?? extraArgsView.string
            let cookieText = createCookieView?.string ?? ""
            let remark = createRemarkView?.string.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let defaults = manager.defaultFingerprintConfig()
            let fingerprintConfig = FingerprintConfig(
                platform: createPlatformField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.platform,
                chromeVersion: createChromeVersionField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.chromeVersion,
                userAgent: createUAView?.string.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.userAgent,
                width: Int(createWidthField?.stringValue ?? "") ?? defaults.width,
                height: Int(createHeightField?.stringValue ?? "") ?? defaults.height,
                deviceScaleFactor: createDPRField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.deviceScaleFactor,
                cpuCores: Int(createCPUField?.stringValue ?? "") ?? defaults.cpuCores,
                memoryGB: Int(createMemoryField?.stringValue ?? "") ?? defaults.memoryGB,
                webRTCPolicy: createWebRTCField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.webRTCPolicy
            )
            let profile = try manager.createProfile(
                currentProfiles: profiles,
                sourceApp: sourceField.stringValue,
                appName: windowName.isEmpty ? "资料" : windowName,
                displayNumber: Int(createDisplayNumberField?.stringValue ?? ""),
                seedBase: Int(createSeedField?.stringValue ?? seedField.stringValue) ?? 10000,
                language: language,
                timezone: timezone,
                proxy: proxy,
                extraArgs: args,
                cookieText: cookieText,
                openUrls: urls,
                remark: remark,
                fingerprintConfig: fingerprintConfig
            )
            try manager.updateIcon(for: profile)
            profiles.append(profile)
            profiles.sort { $0.number < $1.number }
            manager.save(profiles)
            applyFilter()
            manager.open(profile)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                self.refreshWindowsAsync()
            }
        } catch {
            alert(error.localizedDescription)
        }
    }

    func currentFingerprintConfigFromForm() -> FingerprintConfig {
        let defaults = manager.defaultFingerprintConfig()
        return FingerprintConfig(
            platform: createPlatformField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.platform,
            chromeVersion: createChromeVersionField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.chromeVersion,
            userAgent: createUAView?.string.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.userAgent,
            width: Int(createWidthField?.stringValue ?? "") ?? defaults.width,
            height: Int(createHeightField?.stringValue ?? "") ?? defaults.height,
            deviceScaleFactor: createDPRField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.deviceScaleFactor,
            cpuCores: Int(createCPUField?.stringValue ?? "") ?? defaults.cpuCores,
            memoryGB: Int(createMemoryField?.stringValue ?? "") ?? defaults.memoryGB,
            webRTCPolicy: createWebRTCField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? defaults.webRTCPolicy
        )
    }

    @objc func saveProfileFromForm() {
        guard let number = editingProfileNumber,
              let old = profiles.first(where: { $0.number == number }) else { return }
        let name = createNameField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? old.name
        let urls = (createUrlsView?.string ?? "")
            .split(separator: "\n")
            .map { manager.normalizedOpenURL(String($0)) }
            .filter { !$0.isEmpty }
        let args = (createArgsView?.string ?? old.args.joined(separator: "\n"))
            .split(separator: "\n")
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        let updated = Profile(
            number: old.number,
            displayNumber: Int(createDisplayNumberField?.stringValue ?? "") ?? old.displayNumber ?? old.number,
            name: name.isEmpty ? old.name : name,
            fingerprint: Int(createSeedField?.stringValue ?? "") ?? old.fingerprint,
            appPath: old.appPath,
            profilePath: old.profilePath,
            args: args,
            proxy: createProxyField?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines),
            remark: createRemarkView?.string.trimmingCharacters(in: .whitespacesAndNewlines),
            openUrls: urls.isEmpty ? nil : urls,
            cookieJSON: createCookieView?.string.trimmingCharacters(in: .whitespacesAndNewlines),
            fingerprintConfig: currentFingerprintConfigFromForm()
        )
        do {
            let normalized = Profile(
                number: updated.number,
                displayNumber: updated.displayNumber,
                name: updated.name,
                fingerprint: updated.fingerprint,
                appPath: updated.appPath,
                profilePath: updated.profilePath,
                args: manager.normalizedArgs(for: updated),
                proxy: updated.proxy?.isEmpty == false ? updated.proxy : nil,
                remark: updated.remark?.isEmpty == false ? updated.remark : nil,
                openUrls: updated.openUrls,
                cookieJSON: updated.cookieJSON?.isEmpty == false ? updated.cookieJSON : nil,
                fingerprintConfig: updated.fingerprintConfig
            )
            let renamed = try manager.renamedProfile(normalized, to: normalized.name)
            try manager.updateIcon(for: renamed)
            profiles = profiles.map { $0.number == number ? renamed : $0 }.sorted { $0.number < $1.number }
            manager.save(profiles)
            try manager.rebuildLauncher(for: renamed)
            applyFilter()
            editingProfileNumber = nil
        } catch {
            alert(error.localizedDescription)
        }
    }

    @objc func openSelected() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        manager.open(filteredProfiles[row])
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.refreshWindowsAsync()
        }
    }

    @objc func openAllProfiles() {
        for profile in filteredProfiles {
            manager.open(profile)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            self.refreshWindowsAsync()
        }
    }

    @objc func openRowButton(_ sender: NSButton) {
        guard sender.tag >= 0 && sender.tag < filteredProfiles.count else { return }
        manager.open(filteredProfiles[sender.tag])
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.refreshWindowsAsync()
        }
    }

    @objc func closeRowButton(_ sender: NSButton) {
        guard sender.tag >= 0 && sender.tag < filteredProfiles.count else { return }
        let profile = filteredProfiles[sender.tag]
        let states = manager.runningWindows()
        guard let state = states[profile.profilePath] else { return }
        manager.close(state)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            self.refreshWindowsAsync()
        }
    }

    @objc func editRowButton(_ sender: NSButton) {
        guard sender.tag >= 0 && sender.tag < filteredProfiles.count else { return }
        let profile = filteredProfiles[sender.tag]
        editingProfileNumber = profile.number
        showProfileForm(profile: profile)
    }

    @objc func refreshWindows() {
        refreshWindowsAsync()
    }

    func refreshWindowsAsync() {
        DispatchQueue.global(qos: .userInitiated).async {
            let states = self.manager.runningWindows()
            DispatchQueue.main.async {
                self.running = states
                self.applyFilter()
            }
        }
    }

    @objc func closeSelected() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        let states = manager.runningWindows()
        guard let state = states[filteredProfiles[row].profilePath] else { return }
        manager.close(state)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            self.refreshWindowsAsync()
        }
    }

    @objc func closeAllProfiles() {
        let states = manager.runningWindows()
        let profilePaths = Set(profiles.map { $0.profilePath })
        for (path, state) in states where profilePaths.contains(path) {
            manager.close(state)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            let remaining = self.manager.runningWindows()
            for (path, state) in remaining where profilePaths.contains(path) {
                self.manager.forceClose(state)
            }
            self.refreshWindowsAsync()
        }
    }

    @objc func editSelected() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        let profile = filteredProfiles[row]
        editingProfileNumber = profile.number
        showProfileForm(profile: profile)
    }

    @objc func editSelectedJSON() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        let profile = filteredProfiles[row]
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 560),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        panel.title = "编辑环境配置"
        panel.center()

        let view = NSTextView(frame: NSRect(x: 18, y: 62, width: 724, height: 470))
        view.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        let encoder = JSONEncoder.pretty
        if let data = try? encoder.encode(profile), let text = String(data: data, encoding: .utf8) {
            view.string = text
        }
        editJSONView = view

        let scroll = NSScrollView(frame: view.frame)
        scroll.documentView = view
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = true
        scroll.borderType = .bezelBorder
        panel.contentView?.addSubview(scroll)

        let cancel = button("取消", #selector(closeCreateDialog(_:)))
        cancel.frame = NSRect(x: 570, y: 20, width: 72, height: 30)
        panel.contentView?.addSubview(cancel)
        let save = primaryButton("保存", #selector(saveEditedProfile(_:)))
        save.tag = profile.number
        save.frame = NSRect(x: 650, y: 20, width: 92, height: 30)
        panel.contentView?.addSubview(save)

        window.beginSheet(panel)
    }

    @objc func saveEditedProfile(_ sender: NSButton) {
        guard let text = editJSONView?.string.data(using: .utf8) else { return }
        do {
            let decoded = try JSONDecoder().decode(Profile.self, from: text)
            let profile = Profile(
                number: decoded.number,
                displayNumber: decoded.displayNumber,
                name: decoded.name,
                fingerprint: decoded.fingerprint,
                appPath: decoded.appPath,
                profilePath: decoded.profilePath,
                args: manager.normalizedArgs(for: decoded),
                proxy: decoded.proxy,
                remark: decoded.remark,
                openUrls: decoded.openUrls,
                cookieJSON: decoded.cookieJSON,
                fingerprintConfig: decoded.fingerprintConfig
            )
            let renamed = try manager.renamedProfile(profile, to: profile.name)
            try manager.updateIcon(for: renamed)
            profiles = profiles.map { $0.number == sender.tag ? renamed : $0 }.sorted { $0.number < $1.number }
            manager.save(profiles)
            try manager.rebuildLauncher(for: renamed)
            applyFilter()
            if let panel = sender.window as? NSPanel {
                window.endSheet(panel)
                panel.close()
            }
        } catch {
            alert("JSON 格式错误：\(error.localizedDescription)")
        }
    }

    @objc func clearSelectedCache() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        let profile = filteredProfiles[row]
        let confirm = NSAlert()
        confirm.messageText = "重置浏览器数据"
        confirm.informativeText = "确定重置 \(profile.name)？这会删除该窗口的 Cookie、缓存、本地存储和登录状态。"
        confirm.addButton(withTitle: "重置")
        confirm.addButton(withTitle: "取消")
        guard confirm.runModal() == .alertFirstButtonReturn else { return }
        if let state = running[profile.profilePath] {
            manager.close(state)
        }
        DispatchQueue.global(qos: .utility).async {
            do {
                try self.manager.clearCache(profile)
                DispatchQueue.main.async {
                    self.alert("数据已重置")
                    self.refreshWindowsAsync()
                }
            } catch {
                DispatchQueue.main.async {
                    self.alert(error.localizedDescription)
                }
            }
        }
    }

    @objc func deleteSelected() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        let profile = filteredProfiles[row]
        let confirm = NSAlert()
        confirm.messageText = "删除环境"
        confirm.informativeText = "确定删除 \(profile.name)？会删除对应 App 和资料目录。"
        confirm.addButton(withTitle: "删除")
        confirm.addButton(withTitle: "取消")
        guard confirm.runModal() == .alertFirstButtonReturn else { return }
        if let state = running[profile.profilePath] {
            manager.close(state)
        }
        profiles = profiles.filter { $0.number != profile.number }.sorted { $0.number < $1.number }
        manager.save(profiles)
        applyFilter()
        DispatchQueue.global(qos: .utility).async {
            do {
                try self.manager.deleteFiles(for: profile)
                DispatchQueue.main.async {
                    self.refreshWindowsAsync()
                }
            } catch {
                DispatchQueue.main.async {
                    self.alert(error.localizedDescription)
                }
            }
        }
    }

    @objc func exportProfiles() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "profiles-export.json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let data = try JSONEncoder.pretty.encode(ProfileStore(profiles: profiles))
            try data.write(to: url)
        } catch {
            alert(error.localizedDescription)
        }
    }

    @objc func importProfiles() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.json]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            let data = try Data(contentsOf: url)
            let imported = try JSONDecoder().decode(ProfileStore.self, from: data).profiles
            var byNumber = Dictionary(uniqueKeysWithValues: profiles.map { ($0.number, $0) })
            for profile in imported {
                byNumber[profile.number] = profile
            }
            profiles = byNumber.values.sorted { $0.number < $1.number }
            manager.save(profiles)
            applyFilter()
        } catch {
            alert(error.localizedDescription)
        }
    }

    @objc func revealSelected() {
        let row = tableView.selectedRow
        guard row >= 0 else { return }
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: filteredProfiles[row].appPath)])
    }

    @objc func showSharedExtensionsDialog() {
        sharedExtensions = manager.loadSharedExtensions()
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 460),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        panel.title = "扩展管理"
        panel.center()

        let content = FixedPage(frame: NSRect(x: 0, y: 0, width: 760, height: 460))

        let hint = NSTextField(labelWithString: "扩展只导入一份，所有窗口启动时都会加载；但扩展的设置、缓存、登录状态仍保存在各自窗口资料里。")
        hint.frame = NSRect(x: 24, y: 20, width: 712, height: 38)
        hint.textColor = .secondaryLabelColor
        hint.lineBreakMode = .byWordWrapping
        hint.maximumNumberOfLines = 2
        content.addSubview(hint)

        let addButton = primaryButton("导入扩展", #selector(importSharedExtension))
        addButton.frame = NSRect(x: 24, y: 70, width: 94, height: 30)
        content.addSubview(addButton)

        let clearButton = button("清空全部", #selector(clearSharedExtensionsAction))
        clearButton.frame = NSRect(x: 126, y: 70, width: 88, height: 30)
        content.addSubview(clearButton)

        let rebuildButton = button("同步到全部窗口", #selector(rebuildAllLaunchersForExtensions))
        rebuildButton.frame = NSRect(x: 222, y: 70, width: 122, height: 30)
        content.addSubview(rebuildButton)

        let listView = NSTextView(frame: NSRect(x: 0, y: 0, width: 690, height: 250))
        listView.isEditable = false
        listView.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        listView.string = sharedExtensionsListText()

        let scroll = NSScrollView(frame: NSRect(x: 24, y: 112, width: 712, height: 260))
        scroll.documentView = listView
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.identifier = NSUserInterfaceItemIdentifier("sharedExtensionsList")
        content.addSubview(scroll)

        let removeLabel = NSTextField(labelWithString: "删除指定扩展序号")
        removeLabel.frame = NSRect(x: 24, y: 388, width: 110, height: 22)
        content.addSubview(removeLabel)

        let removeField = NSTextField(string: "")
        removeField.frame = NSRect(x: 140, y: 384, width: 80, height: 28)
        removeField.identifier = NSUserInterfaceItemIdentifier("removeExtensionIndexField")
        content.addSubview(removeField)

        let removeButton = button("删除", #selector(removeSharedExtensionAction(_:)))
        removeButton.frame = NSRect(x: 228, y: 384, width: 64, height: 28)
        content.addSubview(removeButton)

        let closeButton = button("关闭", #selector(closeCreateDialog(_:)))
        closeButton.frame = NSRect(x: 664, y: 414, width: 72, height: 30)
        content.addSubview(closeButton)

        panel.contentView = content
        window.beginSheet(panel)
    }

    func sharedExtensionsListText() -> String {
        let items = manager.loadSharedExtensions()
        if items.isEmpty {
            return "当前还没有共享扩展。\n\n导入后，所有窗口下次启动都会自动加载这些扩展。"
        }
        return items.enumerated().map { index, path in
            "\(index + 1). \(path)"
        }.joined(separator: "\n")
    }

    func refreshSharedExtensionsPanel(_ panel: NSPanel?) {
        guard let panel,
              let content = panel.contentView,
              let scroll = content.subviews.first(where: { $0 is NSScrollView && $0.identifier?.rawValue == "sharedExtensionsList" }) as? NSScrollView,
              let textView = scroll.documentView as? NSTextView else {
            return
        }
        sharedExtensions = manager.loadSharedExtensions()
        textView.string = sharedExtensionsListText()
    }

    @objc func importSharedExtension() {
        let openPanel = NSOpenPanel()
        openPanel.canChooseDirectories = true
        openPanel.canChooseFiles = false
        openPanel.allowsMultipleSelection = true
        openPanel.message = "请选择已解压的 Chrome 扩展目录（目录内应有 manifest.json）"
        guard openPanel.runModal() == .OK else { return }
        let valid = openPanel.urls.filter {
            FileManager.default.fileExists(atPath: $0.appendingPathComponent("manifest.json").path)
        }
        if valid.isEmpty {
            alert("没有检测到有效扩展目录，目录内需要包含 manifest.json")
            return
        }
        manager.addSharedExtensions(valid)
        if let keyWindow = NSApp.keyWindow as? NSPanel {
            refreshSharedExtensionsPanel(keyWindow)
        }
    }

    @objc func clearSharedExtensionsAction() {
        manager.clearSharedExtensions()
        if let keyWindow = NSApp.keyWindow as? NSPanel {
            refreshSharedExtensionsPanel(keyWindow)
        }
    }

    @objc func removeSharedExtensionAction(_ sender: NSButton) {
        guard let panel = sender.window as? NSPanel,
              let content = panel.contentView,
              let field = content.subviews.first(where: { $0.identifier?.rawValue == "removeExtensionIndexField" }) as? NSTextField,
              let index = Int(field.stringValue), index > 0 else {
            alert("请输入要删除的扩展序号")
            return
        }
        manager.removeSharedExtension(at: index - 1)
        field.stringValue = ""
        refreshSharedExtensionsPanel(panel)
    }

    @objc func rebuildAllLaunchersForExtensions() {
        sharedExtensions = manager.loadSharedExtensions()
        for profile in profiles {
            try? manager.rebuildLauncher(for: profile)
        }
        alert("已同步到全部窗口。已打开的窗口需要重新打开后才会加载新扩展。")
        if let keyWindow = NSApp.keyWindow as? NSPanel {
            refreshSharedExtensionsPanel(keyWindow)
        }
    }

    func alert(_ text: String) {
        let alert = NSAlert()
        alert.messageText = "指纹浏览器"
        alert.informativeText = text
        alert.runModal()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
