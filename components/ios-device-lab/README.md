# Fixture própria para iOS virtual

App UIKit mínimo, sem rede, credenciais ou dados de terceiros. Serve para
verificar instalação, abertura, contador de toques e rolagem no runtime de
pesquisa. Compile com `python3 scripts/build_ios_device_fixture.py` no Mac.

O binário usa plataforma iPhoneOS/arm64, deployment target iOS 14.0 e assinatura
ad-hoc. Não é um build para Simulator e não é apresentado como instalável em
iPhone físico. A aceitação no runtime virtual ainda deve ser validada.
O receipt registra hashes e distingue build de instalação/abertura.
