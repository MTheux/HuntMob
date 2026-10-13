# HuntMob

Laboratório portátil de análise mobile do ecossistema HuntBox/Draxen.

O projeto coordena runtimes Android e iOS e envia artefatos autorizados ao
REA para análise estática/dinâmica. O runtime nunca escolhe o alvo: toda ação
exige um engagement válido, pacote allowlisted e aprovação explícita.

## Arquitetura inicial

```text
HuntMob Control Plane
├── Android: Genymotion + ADB
├── iOS: Apple Simulator + vPhone adapter
├── Analysis: REA + Ghidra + JADX/Apktool
└── Evidence: receipts, screenshots, logs and hashes
```

## Início rápido

```bash
python3 -m huntmob.cli status
python3 -m huntmob.cli providers
python3 -m huntmob.cli capabilities
python3 -m huntmob.cli plan ios --controller-os windows
python3 -m huntmob.cli plan ios --controller-os linux --privileged-ios
python3 -m unittest discover -s tests -v
```

O comando `status` é somente leitura. Criação, inicialização e alteração de
dispositivos serão adicionadas atrás dos gates de autorização.

## Limites

- Genymotion é o runtime Android; não oferece virtualização iOS.
- iOS local usa Apple Simulator; Corellium é o tier avançado e device clouds
  são opcionais para recursos que exigem hardware real.
- Em Windows/Linux, a UI funciona localmente e agenda iOS em um Mac worker,
  Corellium ou device cloud através de uma conexão privada autenticada.
- Biometria, câmera, localização e sensores são fixtures de teste, não bypasses.
- Nenhuma execução contra aplicativo ou sistema sem autorização documentada.

