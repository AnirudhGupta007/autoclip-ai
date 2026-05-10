# AutoClip AI — Development Commands
# Run `make help` to see available targets

.PHONY: help setup backend frontend dev test lint clean up down logs rebuild ps shell-be shell-db

# Default: show help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ─── Setup ──────────────────────────────────────────────
setup: ## First-time setup (backend + frontend dependencies)
	@echo "Setting up backend..."
	cd backend && uv sync
	@echo "Setting up frontend..."
	cd frontend && npm install
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env — add your API keys"; fi
	@echo "Done. Run 'make dev' to start."

# ─── Development ────────────────────────────────────────
backend: ## Start backend server (FastAPI on :8000)
	cd backend && uv run uvicorn autoclip.main:app --reload --port 8000

frontend: ## Start frontend dev server (Vite on :5173)
	cd frontend && npm run dev

dev: ## Start both backend and frontend
	@echo "Starting backend on :8000 and frontend on :5173..."
	@make backend & make frontend

# ─── Testing ────────────────────────────────────────────
test: ## Run all tests
	cd backend && uv run pytest tests/ -v

test-cov: ## Run tests with coverage report
	cd backend && uv run pytest tests/ -v --cov=autoclip --cov-report=term-missing

test-fast: ## Run tests without verbose output
	cd backend && uv run pytest tests/ -q

# ─── Code Quality ───────────────────────────────────────
lint: ## Type-check and lint
	cd backend && uv run python -m py_compile src/autoclip/pipeline/graph.py
	cd backend && uv run python -m py_compile src/autoclip/pipeline/state.py
	cd backend && uv run python -c "from autoclip.pipeline.graph import pipeline; print('Graph compiles OK')"

# ─── Docker (one-command full stack) ────────────────────
up: ## Build + start all services (postgres + redis + backend + frontend)
	@if [ ! -f .env ]; then cp .env.example .env && echo ".env created — fill in GEMINI_API_KEY and GROQ_API_KEY then rerun"; exit 1; fi
	docker compose up -d --build
	@echo "→ http://localhost  (api: http://localhost/api/health)"

down: ## Stop all services (keeps volumes)
	docker compose down

nuke: ## Stop services AND wipe volumes (postgres, redis, uploads, outputs)
	docker compose down -v

logs: ## Tail logs (all services)
	docker compose logs -f --tail=200

logs-be: ## Tail backend logs
	docker compose logs -f --tail=200 backend

ps: ## Show service status
	docker compose ps

rebuild: ## Rebuild backend image and restart it
	docker compose build backend && docker compose up -d backend

shell-be: ## Open a shell inside the backend container
	docker compose exec backend bash

shell-db: ## Open psql in the postgres container
	docker compose exec postgres psql -U autoclip -d autoclip

# ─── Cleanup ────────────────────────────────────────────
clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf backend/.venv frontend/dist
