import AppKit
import WebKit

final class Viewer: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var origin: String = ""
    var launched = false
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let main = NSMenu(), appMenu = NSMenu(), item = NSMenuItem()
        main.addItem(item);item.submenu = appMenu
        appMenu.addItem(withTitle: "Conectar ao worker", action: #selector(prompt), keyEquivalent: "o").target = self
        appMenu.addItem(withTitle: "Recarregar tela", action: #selector(reload), keyEquivalent: "r").target = self
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Sair", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = main
        window = NSWindow(contentRect: NSRect(x:0,y:0,width:560,height:920), styleMask:[.titled,.closable,.miniaturizable,.resizable], backing:.buffered, defer:false)
        window.title = "HuntMob Viewer";window.minSize = NSSize(width:400,height:600);window.center()
        let config = WKWebViewConfiguration();config.preferences.javaScriptCanOpenWindowsAutomatically = false
        web = WKWebView(frame:window.contentView!.bounds,configuration:config);web.navigationDelegate = self;web.autoresizingMask = [.width,.height]
        window.contentView!.addSubview(web);window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
        launched = true
        prompt()
    }
    func validated(_ value: String) -> URL? {
        guard var parts = URLComponents(string:value), let host = parts.host, parts.user == nil, parts.password == nil, parts.fragment == nil, parts.path == "" || parts.path == "/" else { return nil }
        let local = parts.scheme == "http" && ["localhost","127.0.0.1","::1"].contains(host)
        let remote = parts.scheme == "https" && host.hasSuffix(".ts.net")
        guard local || remote else { return nil }
        let items = parts.queryItems ?? []
        for item in items {
            if item.name == "viewer" && item.value == "1" { continue }
            if item.name == "platform" && ["ios","android"].contains(item.value ?? "") { continue }
            if item.name == "device", let value = item.value, value.range(of:"^[a-zA-Z0-9_-]{1,100}$",options:.regularExpression) != nil { continue }
            return nil
        }
        parts.path = "/";parts.queryItems = items.filter{$0.name != "viewer"} + [URLQueryItem(name:"viewer",value:"1")]
        return parts.url
    }
    func connect(_ value:String) {
        guard let url = validated(value) else {
            let alert = NSAlert();alert.messageText = "URL inválida";alert.informativeText = "Use a raiz do worker local ou HTTPS privado do Tailscale.";alert.runModal();return
        }
        origin = "\(url.scheme!)://\(url.host!):\(url.port ?? (url.scheme == "https" ? 443:80))"
        web.load(URLRequest(url:url))
    }
    @objc func prompt() {
        let alert = NSAlert();alert.messageText = "Conectar ao dispositivo";alert.informativeText = "O emulador continua no worker. Remoto: conecte o Tailscale e informe a URL HTTPS do HuntMob.";alert.addButton(withTitle:"Conectar");alert.addButton(withTitle:"Cancelar")
        let input = NSTextField(string:"http://127.0.0.1:8090/");input.frame = NSRect(x:0,y:0,width:380,height:28);alert.accessoryView = input
        if alert.runModal() == .alertFirstButtonReturn { connect(input.stringValue) }
    }
    @objc func reload() { web.reload() }
    func application(_ application:NSApplication,open urls:[URL]) {
        for url in urls where url.scheme == "huntmob-viewer" && url.host == "open" {
            if let target = URLComponents(url:url,resolvingAgainstBaseURL:false)?.queryItems?.first(where:{$0.name == "url"})?.value {
                if launched { connect(target) }
                else { DispatchQueue.main.asyncAfter(deadline:.now()+1) { self.connect(target) } }
            }
        }
    }
    func webView(_ webView:WKWebView,decidePolicyFor action:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url = action.request.url else { decisionHandler(.cancel);return }
        let current = "\(url.scheme ?? "")://\(url.host ?? ""):\(url.port ?? (url.scheme == "https" ? 443:80))"
        decisionHandler(current == origin && action.targetFrame != nil ? .allow:.cancel)
    }
    func webView(_ webView:WKWebView,didFailProvisionalNavigation navigation:WKNavigation!,withError error:Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        let alert = NSAlert();alert.messageText = "Worker indisponível";alert.informativeText = "Verifique a URL, o Tailscale e se o computador permanece ligado. Certificados continuam sendo validados.";alert.runModal()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
}
let app = NSApplication.shared
let delegate = Viewer();app.delegate = delegate;app.run()
