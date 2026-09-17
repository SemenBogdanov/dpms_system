import Foundation
import Security
import Darwin

// This helper accesses only its own item. It has no command that prints a value.
let service = "ru.dpms.local-llm.gateway.v1"
let account = "gateway"
let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: service,
    kSecAttrAccount as String: account,
    kSecAttrSynchronizable as String: false,
]

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

let args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first else { fail("Expected provision, check, run, or probe-vps") }
guard #filePath.hasPrefix("/") else { fail("Rebuild using an absolute Swift source path") }
let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent()

switch command {
case "provision":
    guard args.count == 1 else { fail("Unexpected arguments") }
    var bytes = [UInt8](repeating: 0, count: 32)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
        fail("Random source unavailable")
    }
    let value = Data(bytes).base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
    var item = query
    item[kSecValueData as String] = Data(value.utf8)
    item[kSecAttrLabel as String] = "DPMS local model gateway"
    let result = SecItemAdd(item as CFDictionary, nil)
    if result == errSecDuplicateItem {
        print("existing_item_preserved")
    } else if result == errSecSuccess {
        print("created")
    } else {
        fail("Cannot provision gateway item in macOS Keychain")
    }
case "check":
    guard args.count == 1 else { fail("Unexpected arguments") }
    var lookup = query
    lookup[kSecReturnAttributes as String] = true
    lookup[kSecMatchLimit as String] = kSecMatchLimitOne
    let result = SecItemCopyMatching(lookup as CFDictionary, nil)
    guard result == errSecSuccess else { fail("Gateway item unavailable") }
    print("item_present")
case "run", "probe-vps":
    guard args.count == 1 else { fail("Gateway entrypoint is fixed; arguments are not accepted") }
    var lookup = query
    lookup[kSecReturnData as String] = true
    lookup[kSecMatchLimit as String] = kSecMatchLimitOne
    var item: CFTypeRef?
    guard SecItemCopyMatching(lookup as CFDictionary, &item) == errSecSuccess,
          let data = item as? Data,
          let value = String(data: data, encoding: .utf8),
          value.range(of: "^[A-Za-z0-9_-]{43,256}$", options: .regularExpression) != nil else {
        fail("Gateway item unavailable; unlock login Keychain before starting")
    }
    let executable = source.appendingPathComponent(".venv/bin/python").path
    let entrypoint = command == "run" ? "gateway.py" : "synthetic_vps_probe.py"
    let arguments = [executable, "-E", "-s", source.appendingPathComponent(entrypoint).path]
    let inherited = ProcessInfo.processInfo.environment
    var environment = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PYTHONUNBUFFERED": "1"]
    for name in ["HOME", "DPMS_LOCAL_LLM_MODEL", "DPMS_LOCAL_LLM_STATE_DIRECTORY"] {
        if let setting = inherited[name] { environment[name] = setting }
    }
    if command == "probe-vps", let socket = inherited["SSH_AUTH_SOCK"] {
        environment["SSH_AUTH_SOCK"] = socket
    }
    environment["DPMS_LOCAL_LLM_BEARER"] = value
    guard chdir(source.path) == 0 else { fail("Cannot enter gateway directory") }
    var argv = arguments.map { strdup($0) }
    var envp = environment.sorted(by: { $0.key < $1.key }).map { strdup("\($0.key)=\($0.value)") }
    guard argv.allSatisfy({ $0 != nil }), envp.allSatisfy({ $0 != nil }) else {
        fail("Cannot prepare gateway process")
    }
    argv.append(nil)
    envp.append(nil)
    // Keep launchd's PID and process group; spawning a child can leave an orphan.
    argv.withUnsafeMutableBufferPointer { arguments in
        envp.withUnsafeMutableBufferPointer { environment in
            _ = execve(executable, arguments.baseAddress!, environment.baseAddress!)
        }
    }
    fail("Cannot start gateway process")
default:
    fail("Unknown command")
}
