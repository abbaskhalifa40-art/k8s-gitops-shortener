#!/usr/bin/env bash
# bootstrap.sh
# Builds the whole platform on a local kind cluster, in order:
#   1. kind cluster (3 nodes)
#   2. Traefik ingress controller
#   3. metrics-server (needed for the autoscaler)
#   4. kube-prometheus-stack (Prometheus + Grafana) and the app dashboard
#   5. Argo CD
#   6. The Argo CD Application, which deploys the shortener from Git
#
# Safe to re-run: every step is an upgrade/install, not a fresh create.
set -euo pipefail

# Pinned chart versions, so a run today and a run in 6 months behave
# the same. Bump these deliberately.
TRAEFIK_VERSION="42.3.0"
METRICS_SERVER_VERSION="3.14.0"
PROM_STACK_VERSION="92.21.1"
ARGOCD_VERSION="10.14.0"

cd "$(dirname "$0")/.."

for tool in docker kind kubectl helm; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool (see README > Prerequisites)"; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "Docker isn't running. Open Docker Desktop first."; exit 1; }

echo "==> 1/6 Creating kind cluster"
if ! kind get clusters | grep -qx gitops; then
  kind create cluster --config cluster/kind-config.yaml
fi
kubectl config use-context kind-gitops

echo "==> Adding Helm repos"
helm repo add traefik https://traefik.github.io/charts >/dev/null
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server >/dev/null
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo update >/dev/null

echo "==> 2/6 Traefik ingress"
helm upgrade --install traefik traefik/traefik --version "$TRAEFIK_VERSION" \
  -n traefik --create-namespace -f cluster/traefik-values.yaml --wait

echo "==> 3/6 metrics-server"
# --kubelet-insecure-tls is needed on kind because the kubelets use
# self-signed certificates. Never use it on a real cluster.
helm upgrade --install metrics-server metrics-server/metrics-server \
  --version "$METRICS_SERVER_VERSION" -n kube-system \
  --set 'args={--kubelet-insecure-tls}' --wait

echo "==> 4/6 Prometheus and Grafana (takes a few minutes)"
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  --version "$PROM_STACK_VERSION" -n monitoring --create-namespace \
  -f cluster/monitoring-values.yaml --wait --timeout 10m
kubectl apply -f monitoring/dashboard.yaml

echo "==> 5/6 Argo CD"
helm upgrade --install argocd argo/argo-cd --version "$ARGOCD_VERSION" \
  -n argocd --create-namespace -f cluster/argocd-values.yaml --wait --timeout 10m

echo "==> 6/6 Deploying the app through Argo CD"
kubectl apply -f argocd/shortener-app.yaml

echo
echo "Done. Argo CD is now syncing the app from GitHub (1-2 minutes)."
echo
echo "  App:      http://shortener.localtest.me/healthz"
echo "  Argo CD:  http://argocd.localtest.me  (user: admin)"
echo "  Grafana:  http://grafana.localtest.me  (user: admin)"
echo
echo "Passwords:  make passwords"
