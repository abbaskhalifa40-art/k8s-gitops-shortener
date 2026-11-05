# Shortcuts. Run `make help` to list them.
.PHONY: help up down test lint chart-lint passwords status load-test

help: ## Show this list
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up: ## Create the cluster and install everything
	./scripts/bootstrap.sh

down: ## Delete the cluster (everything goes, nothing is left running)
	kind delete cluster --name gitops

status: ## Show the app's pods, autoscaler and Argo CD sync state
	kubectl get application shortener -n argocd
	kubectl get pods,hpa -n shortener

passwords: ## Print the Argo CD and Grafana admin passwords
	@echo "Argo CD: $$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
	@echo "Grafana: $$(kubectl -n monitoring get secret monitoring-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"

test: ## Run the app's unit tests
	cd app && python3 -m pytest -q

lint: ## Lint the app code
	cd app && ruff check . && ruff format --check .

chart-lint: ## Lint and render the Helm chart
	helm lint charts/shortener --strict
	helm template shortener charts/shortener >/dev/null

load-test: ## Send traffic so you can watch the autoscaler and Grafana react
	@for i in $$(seq 1 2000); do \
	  curl -s -o /dev/null -X POST http://shortener.localtest.me/api/links \
	    -H 'Content-Type: application/json' -d '{"url":"https://example.com/'$$i'"}' & \
	  [ $$((i % 50)) -eq 0 ] && wait; \
	done; wait; echo "Sent 2000 requests"
