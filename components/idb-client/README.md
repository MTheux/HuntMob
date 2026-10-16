# Bridge iOS local

Cliente Meta idb 1.1.7 isolado em `.venv` e companion 1.7.0 do tap oficial `facebook/fb`, utilizados no worker macOS em 2026-10-13.

Setup de desenvolvimento:

```sh
brew tap facebook/fb
brew install facebook/fb/idb-companion
python3 -m venv components/idb-client/.venv
components/idb-client/.venv/bin/pip install fb-idb==1.1.7 protobuf==3.20.3
```

Fonte/licença upstream: https://github.com/facebook/idb · MIT.
Este ambiente não está incluído em uma release portátil validada. O SDK/runtime Apple são instalados pelo Xcode.
