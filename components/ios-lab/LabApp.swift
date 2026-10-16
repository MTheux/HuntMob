import SwiftUI
import LocalAuthentication

@main struct HuntMobLab: App {
    var body: some Scene { WindowGroup { LabView() } }
}
struct LabView: View {
    @State private var count = 0
    @State private var biometricResult = "Nenhum teste biométrico executado"
    @State private var networkResult = "Nenhuma requisição de teste enviada"
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("HuntMob iOS Lab").font(.title2.bold())
                    Text("Fixture local para validar instalação, toque e fluidez. Não representa uma análise de segurança de outro aplicativo.").font(.subheadline).foregroundStyle(.secondary)
                }
                Section("Teste de interação") {
                    Button("Toques confirmados: \(count) · aumentar") { count += 1 }
                    Text("Role a lista para testar o vídeo e o gesto no Simulator.")
                }
                Section("Biometria do Simulator") {
                    Button("Solicitar Face ID / Touch ID") {
                        let context = LAContext()
                        var error: NSError?
                        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) else {
                            biometricResult = "Biometria indisponível: habilite o cadastro de teste no painel"
                            return
                        }
                        context.evaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, localizedReason: "Validar eventos na fixture HuntMob") { success, _ in
                            DispatchQueue.main.async { biometricResult = success ? "Evento aprovado pelo iOS" : "Evento recusado pelo iOS" }
                        }
                    }
                    Text(biometricResult)
                }
                Section("Proxy do laboratório") {
                    Button("Enviar requisição local de teste") {
                        let configuration = URLSessionConfiguration.ephemeral
                        if let value = ProcessInfo.processInfo.environment["HUNTMOB_LAB_PROXY_PORT"], let port = Int(value), port == 18083 {
                            configuration.connectionProxyDictionary = ["HTTPEnable":1,"HTTPProxy":"127.0.0.1","HTTPPort":port,"ExcludeSimpleHostnames":false,"ExceptionsList":[]] as [String:Any]
                        }
                        let url = URL(string: "http://localhost:18089/huntmob/ping")!
                        URLSession(configuration: configuration).dataTask(with: url) { _, response, error in
                            DispatchQueue.main.async {
                                networkResult = (response as? HTTPURLResponse).map { "HTTP \($0.statusCode) recebido" } ?? "Servidor local indisponível ou conexão recusada"
                            }
                        }.resume()
                    }
                    Text(networkResult)
                }
                Section("Itens de teste") {
                    ForEach(1...40, id: \.self) { item in
                        NavigationLink("Controle de laboratório \(item)") {
                            VStack(spacing: 24) {
                                Image(systemName: "iphone").font(.system(size: 64)).foregroundStyle(.red)
                                Text("Item \(item)").font(.largeTitle.bold())
                                Text("Navegação executada no iOS Simulator real.")
                            }.padding().navigationTitle("Controle \(item)")
                        }
                    }
                }
            }.navigationTitle("HuntMob").tint(.red).preferredColorScheme(.dark)
        }
    }
}
