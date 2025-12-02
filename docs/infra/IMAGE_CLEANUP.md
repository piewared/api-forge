# Image and Resource Cleanup Strategy

## Overview

The deployment system uses **content-based image tags** to ensure deterministic deployments:
- Same code → same tag → **no duplicate images**
- Different code → different tag → **forces fresh deployment**

### Tag Priority (in order):

1. **Clean Git Commit**: `git-{7-char-sha}` (e.g., `git-a1b2c3d`)
   - Used when: Working tree is clean (no uncommitted changes)
   - Benefit: Human-readable, traceable to exact commit

2. **Content Hash**: `hash-{12-char-hash}` (e.g., `hash-e3b0c44298fc`)
   - Used when: Uncommitted changes exist OR not a git repo
   - Benefit: Deterministic based on actual source file contents

3. **Timestamp Fallback**: `ts-{unix-timestamp}` (e.g., `ts-1733097600`)
   - Used when: Content hashing fails (rare edge case)

This ensures production deployments from git get traceable commit-based tags, while development work with uncommitted changes gets accurate content-based hashes.

This document explains how to manage Docker images and Kubernetes resources.

## Kubernetes ReplicaSet Cleanup

**Automatic Cleanup**: Kubernetes automatically manages ReplicaSet retention via `revisionHistoryLimit`.

**Configuration**: Set in `infra/helm/api-forge/values.yaml`:
```yaml
app:
  revisionHistoryLimit: 3  # Keep 3 old ReplicaSets for quick rollback

worker:
  revisionHistoryLimit: 3
```

Kubernetes will automatically delete older ReplicaSets beyond this limit. The deployment script also cleans up very old ReplicaSets (>1 hour with 0 replicas) as a safety measure.

## Docker Image Cleanup

### Strategy by Environment

#### Minikube (Development/Testing)

**Good News**: Content-based tags mean **fewer duplicate images**. If your code hasn't changed, the same tag is reused.

**When cleanup is needed**: Only after significant development with many code changes.

**Manual Cleanup**:
```bash
# List all images
minikube image ls | grep api-forge-app

# Remove specific old images (examples with different tag types)
minikube image rm docker.io/library/api-forge-app:git-a1b2c3d
minikube image rm docker.io/library/api-forge-app:hash-e3b0c44298fc

# Prune all unused images (safe - only removes unused)
minikube image prune
```

**Automated Cleanup Script**:
```bash
# Keep only the 3 most recent sha256-* tagged images
minikube image ls | grep "api-forge-app:sha256-" | sort -r | tail -n +4 | while read img; do
  minikube image rm "$img"
done
```

#### Production Kubernetes Clusters

**Strategy**: Leverage cluster-native garbage collection and registry policies.

**Options**:

1. **Kubelet Garbage Collection** (Automatic)
   - Kubernetes kubelet automatically removes unused container images
   - Configure in kubelet:
     ```yaml
     imageGCHighThresholdPercent: 85  # Start GC at 85% disk usage
     imageGCLowThresholdPercent: 80   # Stop GC at 80% disk usage
     imageMinimumGCAge: 2m             # Minimum age before GC
     ```

2. **Registry Retention Policies**
   - **Docker Registry**: Use [registry garbage collection](https://docs.docker.com/registry/garbage-collection/)
   - **Harbor**: Configure tag retention policies (e.g., keep last 10 tags)
   - **ECR**: Set lifecycle policies to expire old images
   - **GCR**: Use [image retention policies](https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy)
   - **ACR**: Configure [retention policies](https://docs.microsoft.com/en-us/azure/container-registry/container-registry-retention-policy)

3. **CI/CD Cleanup**
   - Add a cleanup step to your CI/CD pipeline
   - Example GitHub Actions:
     ```yaml
     - name: Clean old images
       run: |
         kubectl delete replicaset -n ${{ env.NAMESPACE }} \
           --field-selector status.replicas=0 \
           $(kubectl get rs -n ${{ env.NAMESPACE }} -o jsonpath='{range .items[?(@.status.replicas==0)]}{.metadata.name}{"\n"}{end}' | head -n -3)
     ```

4. **Third-party Tools**
   - **kube-janitor**: Automatic cleanup of Kubernetes resources
   - **reaper**: Clean up old ReplicaSets, Pods, and images
   - **kube-cleanup-operator**: Time-based resource cleanup

### Recommended Approach

**For Development (Minikube)**:
- Run manual `minikube image prune` weekly
- Or use the automated script above

**For Production**:
1. Configure kubelet garbage collection (already enabled by default in most clusters)
2. Set registry retention policies (keep last 10-20 deploy-* tags)
3. Keep `revisionHistoryLimit: 3` in Helm values (for quick rollback)
4. Optionally: Add kube-janitor for additional cleanup

### Why Not Clean Images in Deployment Script?

The deployment script intentionally does NOT remove Docker images for these reasons:

1. **Environment Agnostic**: Different environments have different image storage (local Docker, registry, etc.)
2. **Safety**: Avoid accidentally removing images that are still in use
3. **Performance**: Image cleanup can be slow and block deployments
4. **Best Practice**: Let each environment handle cleanup according to its own policies
5. **Separation of Concerns**: Deployment focuses on deploying, not maintenance

### Monitoring Image Accumulation

**Check image usage**:
```bash
# Minikube
minikube ssh -- df -h /var

# Kubernetes nodes
kubectl get nodes -o wide
kubectl top nodes
```

**Alert on disk usage**:
- Configure monitoring (Prometheus/Grafana) to alert when node disk usage exceeds 80%
- This will trigger kubelet's automatic garbage collection

## Summary

| Environment | Mechanism | Configuration |
|-------------|-----------|---------------|
| Minikube | Manual cleanup | Run `minikube image prune` periodically |
| K8s ReplicaSets | Automatic | `revisionHistoryLimit: 3` (already configured) |
| K8s Images | Kubelet GC | Already enabled by default |
| Registry | Retention Policy | Configure in your container registry |

The system is designed to be **self-maintaining** in production environments, while requiring **occasional manual cleanup** in development (Minikube).
