# HuntMob remoto via Tailscale — v1, 14/10/2026

## Operação

O Android/Simulator e as ferramentas continuam no computador worker. iPad ou notebook remoto usam o navegador para vídeo, toque/arraste, teclado, Proxy, Reverse, Frida e evidências conforme as capacidades já validadas do dispositivo. Não replica o runtime no iPad e não adiciona capacidades iOS pendentes.

No worker:

```sh
PYTHONPATH=src python3 -m huntmob.cli ui --port 8090
```

Em outro terminal, mantendo a UI ligada:

```sh
PYTHONPATH=src python3 -m huntmob.cli remote
```

O comando inicia gateway em 127.0.0.1:8091 e configura uma rota HTTPS privada Tailscale na porta 8443. Imprime a URL. No iPad, conecte Tailscale com a mesma identidade do proprietário do worker e abra essa URL no Safari. Use Dispositivos para escolher Android/iOS; Ferramentas abre o painel; Teclado permite enviar texto ao campo previamente focado no app.

Se o comando pedir liberação de Serve, o proprietário deve abrir o link oficial emitido pelo CLI para habilitar HTTPS/Serve na conta e repetir o comando. Não houve autorização automática na conta durante esta implementação. A tentativa local confirmou esse requisito; ainda não há rota HTTPS HuntMob ativa.

O computador precisa permanecer ligado, conectado ao Tailscale e com a UI/runtime ativos. Suspensão ou encerramento desconecta o acesso. Ctrl+C no processo remoto encerra sua rota, preservando UI, dispositivo e demais serviços. Não há garantia de desempenho em redes com latência elevada; H.264 usa WebCodecs quando disponível, caso contrário o viewer usa MJPEG existente.

## Controles

- Tailscale Serve, sem Funnel público, sem abrir portas no roteador, sem bind 0.0.0.0.
- Somente identidade do proprietário obtida do Tailscale local; identidade ausente, outra conta ou dispositivo tagged sem identidade são negados.
- Cabeçalhos de identidade são confiáveis somente no gateway loopback, atrás do Serve, que remove valores fornecidos pelo cliente.
- POST exige Origin HTTPS exata; upstream mantém CSRF e autorizações por ação.
- Destino de proxy fixo loopback. Upload limitado a 512 MB; vídeo repassado incrementalmente sem buffer de stream completo.
- Portas já configuradas são recusadas. Teardown verifica que a configuração ainda corresponde ao próprio gateway antes de removê-la. Não modifica ACLs nem usa serve reset.
- Remote gateway utiliza o mesmo worker/encoder. Não inicia segunda captura/emulador.
- Texto é apagado do campo após envio; não é armazenado pelo controle. Limites de caracteres dependem do canal de input atual.

## Evidências e limites

Gateway testado com HTTP local real: controle de identidade, isolamento, Origin, upload/body e transmissão incremental. UI verificada em viewport 1024×768; seletor Android/iOS, painel recolhível, teclado e erro de caractere não suportado.

Tailscale local está Running; serviços existentes nas portas 8501 e 8503 preservados. Serve HTTPS pediu habilitação na conta. Nenhuma conexão iPad/Safari real, certificado HTTPS ou latência WAN foi validada. Estes itens permanecem pendentes, não se confundem com os testes locais.

Referências: https://tailscale.com/docs/features/tailscale-serve (identidade e localhost); https://tailscale.com/docs/reference/tailscale-cli/serve (configuração/remoção por porta).

Alterações locais, sem commit/push/deploy.

## Atualização de ativação

O proprietário liberou Serve na conta; a página oficial confirmou “Tailscale Serve is ready to use”. `huntmob remote` iniciou gateway loopback 8091 e rota HTTPS privada 8443. Readback de Serve confirmou HTTPS e destino loopback, sem AllowFunnel; rotas 8501/8503 preservadas. Gateway real respondeu 403 sem identidade e 200 com identidade autorizada (teste loopback controlado, não é prova de identidade enviada pelo Serve).

URL ativa: https://mac-studio.tail381dfe.ts.net:8443 . Processo remoto mantido ligado. Tentativa de HTTPS por curl/navegador no próprio Mac deu timeout; acesso TLS de outro dispositivo/iPad continua pendente. Não foi afirmada uma causa para o timeout nem alteradas ACLs para contorná-lo.
