# Deploying zeus

A Helm chart lives in [`helm/`](helm/). It runs the optimizer as a single
long-running `Deployment` (loop mode), rendering `config.yaml` into a ConfigMap
and pulling secrets from a Kubernetes Secret.

## Build & push the image

```bash
cd ..                       # zeus/
docker build -t jellebens/zeus:0.1.0 .
docker push jellebens/zeus:0.1.0
```

## Secrets

The container reads `HA_TOKEN`, `MQTT_USER`, `MQTT_PASS`, and (optionally)
`ENTSOE_TOKEN` from a Secret; `config.yaml` references them as `${VAR}`.

In a GitOps repo, **do not** commit plaintext. Manage the Secret with
SealedSecrets/SOPS and point the chart at it:

```yaml
secret:
  create: false
  existingSecret: zeus-secrets   # your SealedSecret's name
```

For a quick non-GitOps test you can let the chart create it:

```bash
helm install bluetti deploy/helm \
  --set secret.create=true \
  --set secret.data.HA_TOKEN=... \
  --set secret.data.MQTT_USER=... \
  --set secret.data.MQTT_PASS=...
```

## Render / install

```bash
helm lint deploy/helm
helm template bluetti deploy/helm           # preview
helm upgrade --install bluetti deploy/helm  # apply
```

Override battery/entity/price settings via the `config:` tree in `values.yaml`.

## Argo CD

See [`argocd-application.example.yaml`](argocd-application.example.yaml). Point
its `repoURL`/`path` at wherever you vendor this chart, then:

```bash
kubectl apply -f deploy/argocd-application.example.yaml
```

## Safety

`config.run.dry_run` defaults to `true` and `config.control.enabled` to `false`,
so a fresh deploy computes schedules and publishes savings sensors but never
commands the battery. Flip both only after Phase 0 discovery confirms the
working-mode option labels and you have watched a few dry-run cycles.
