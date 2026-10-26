# HuntMob — instalação e operação em um comando.
# `make` sozinho mostra esta ajuda.

.DEFAULT_GOAL := help
.PHONY: help up down logs native emulator build test clean

help: ## Mostra os comandos disponíveis
	@echo "HuntMob — comandos:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Mais comum: 'make up' sobe a UI leve em http://127.0.0.1:8090"
	@echo "Para Android real no mac, pareie um worker: 'make native'"

up: ## Sobe a UI governada leve (docker compose up; sem KVM, roda em qualquer host)
	docker compose up -d --build ui
	@echo
	@echo "HuntMob UI: http://127.0.0.1:8090"
	@echo "Status: make logs    Parar: make down"

down: ## Para e remove os containers
	docker compose down

logs: ## Acompanha os logs da UI
	docker compose logs -f ui

native: ## macOS/Windows: pareia worker nativo (Android via HVF/WHPX) + gateway, com URL de acesso
	python3 scripts/run-platform.py

emulator: ## Linux x86_64 + /dev/kvm: Android completo dentro do container
	docker compose --profile emulator up -d --build huntmob-emulator
	@echo "HuntMob (emulador): http://127.0.0.1:8090"

build: ## Constrói a imagem da UI leve
	docker compose build ui

test: ## Roda a suíte de testes
	PYTHONPATH=src python3 -m unittest discover -s tests

clean: ## Remove containers e volumes (apaga SDK/AVDs/workspaces em volume)
	docker compose down -v --remove-orphans
