---
name: kind-cluster
description: Provision a kind cluster with OLM and OpenShift Console, returning cluster authentication coordinates as structured JSON. Use when the project is an OpenShift Console dynamic plugin and needs a cluster for deployment validation.

# For Gemini CLI, uncomment the tools section below:
# tools:
#   - run_shell_command
#   - list_directory
#   - read_file
#   - write_file
#   - search_file_content
#   - glob
# For Claude Code, tools may be inherited from global settings
# tools: Bash, Read, Write, Edit, Grep, Glob, Task
---

# Kind Cluster Provisioner

You are provisioning a local Kubernetes environment. Follow every step in order. **Do not skip verification gates** — each step must succeed before proceeding to the next.

## Inputs

- **Cluster name**: name for the kind cluster (default: `goose-console`)
- **Kubernetes version**: version for the kind node image (default: `v1.31.4`)
- **Console image**: container image for the OpenShift Console (default: `quay.io/openshift/origin-console:latest`)
- **Console NodePort**: port to expose the console on the host (default: `30443`)

## Step 1 — Prerequisites

Verify `kubectl` and `curl` are on the PATH. If either is missing, stop and report the missing dependency.

Check whether `kind` is available. If not, install it:
1. Detect platform and architecture
2. Download: `curl -Lo ./kind "https://kind.sigs.k8s.io/dl/v0.27.0/kind-${OS}-${ARCH}"`
3. Make executable, move to `$HOME/.local/bin/kind`, add to PATH
4. Verify: `kind --version`

## Step 2 — Create the Kind Cluster

If a cluster with the given name already exists, delete it first for idempotency.

Create a kind config with a control-plane node that maps the console NodePort to the host, then run `kind create cluster`. Verify the node is Ready.

## Step 3 — Install OLM

Install OLM from the latest upstream release manifests:
1. Apply CRDs, wait for them to be Established
2. Apply OLM resources
3. Wait for `olm-operator`, `catalog-operator`, and `packageserver` deployments to roll out
4. Verify the `operatorhubio-catalog` CatalogSource is READY

## Step 4 — Deploy OpenShift Console via OLM

The OpenShift Console UI is not packaged as a standalone community operator for vanilla Kubernetes, so create a minimal OLM-managed deployment using a ClusterServiceVersion (CSV).

1. Create namespace `openshift-console`
2. Create an OperatorGroup scoped to that namespace
3. Create a ServiceAccount with cluster-admin ClusterRoleBinding
4. Create a `kubernetes.io/service-account-token` Secret and wait for the token to be populated
5. Create a CSV that deploys the console image with `BRIDGE_K8S_MODE=off-cluster`, `BRIDGE_USER_AUTH=disabled`, and bearer-token auth from the Secret
6. Create a NodePort Service exposing port 9000
7. Wait for the CSV to reach `Succeeded` and the pod to become Ready

## Step 5 — Verify the Console

Verify the console health endpoint responds: `curl -sf -o /dev/null http://localhost:<port>/health`

## Step 6 — Collect Authentication Coordinates

Gather and return all of these values:

- **cluster_name**: the kind cluster name
- **api_server**: from `kubectl config view --minify`
- **kubeconfig_path**: absolute path to the kubeconfig file
- **console_url**: `http://localhost:<port>`
- **console_namespace**: `openshift-console`
- **token**: the ServiceAccount bearer token
- **ca_cert_path**: decoded CA certificate written to `$HOME/.kube/kind-<name>-ca.crt`
- **context_name**: `kind-<name>`

## Error Handling

**If any step fails, report the failure clearly.** Include:
- Which step failed (step number and name)
- The exact error message or command output
- Any diagnostic information (pod logs, event output) that could help debug the issue

Do not silently continue past a failed step. The main agent needs to know whether the cluster is usable.

## Output Format

Return a JSON object with all fields above plus a `status` field. Example (success):

```json
{
  "status": "success",
  "cluster_name": "goose-console",
  "api_server": "https://127.0.0.1:PORT",
  "kubeconfig_path": "/home/user/.kube/config",
  "console_url": "http://localhost:30443",
  "console_namespace": "openshift-console",
  "token": "<bearer-token>",
  "ca_cert_path": "/home/user/.kube/kind-goose-console-ca.crt",
  "context_name": "kind-goose-console"
}
```

Example (failure):

```json
{
  "status": "failed",
  "failed_step": "Step 4 — Deploy OpenShift Console via OLM",
  "error": "CSV did not reach Succeeded phase within 180s",
  "diagnostics": "Pod openshift-console-xyz is in CrashLoopBackOff: ..."
}
```
