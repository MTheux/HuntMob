# HuntBox Mob

Laboratório portátil de análise mobile do ecossistema HuntBox/Draxen.

O projeto coordena runtimes Android e iOS e envia artefatos autorizados ao
REA para análise estática/dinâmica. O runtime nunca escolhe o alvo: toda ação
exige um engagement válido, pacote allowlisted e aprovação explícita.

## Arquitetura inicial

```text
HuntBox Mob Control Plane
├── Android: Genymotion + ADB
├── iOS: Apple Simulator + vPhone adapter
├── Analysis: REA + Ghidra + JADX/Apktool
└── Evidence: receipts, screenshots, logs and hashes
```

## Início rápido

```bash
python3 -m huntbox_mob.cli status
python3 -m unittest discover -s tests -v
```

O comando `status` é somente leitura. Criação, inicialização e alteração de
dispositivos serão adicionadas atrás dos gates de autorização.

## Limites

- Genymotion é o runtime Android; não oferece virtualização iOS.
- iOS usa Apple Simulator para compatibilidade e vPhone apenas em laboratório.
- Biometria, câmera, localização e sensores são fixtures de teste, não bypasses.
- Nenhuma execução contra aplicativo ou sistema sem autorização documentada.

