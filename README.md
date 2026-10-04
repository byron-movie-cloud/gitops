# Movie Cloud GitOps

The `charts/movie-cloud` Helm chart deploys the independently built auth, movie,
user, and Flutter web repositories. Each repository publishes its own image to
GitHub Container Registry after tests pass. A push to a component's default
branch then dispatches its full commit SHA here, and this repository updates
that component's image tag in `values-production.yaml`.

## Cross-repository workflow secret

Create a fine-grained personal access token with **Contents: Read and write**
access to this `gitops` repository. Add it as the `GITOPS_TOKEN` Actions secret
in each of the auth, movie, user, and frontend repositories. The service-side
workflows use it only to send a repository-dispatch event; this repository uses
its own `GITHUB_TOKEN` to commit the version change. Pull requests and pushes to
non-default branches do not update production values.

## Cluster prerequisites

- A Kubernetes cluster with an Ingress controller matching `ingress.className`.
- The four images pushed to GHCR. For private packages, create the
  `ghcr-pull-secret` image pull secret in the target namespace.
- One database credential Secret per Spring service. The databases are external
  to this chart (for example, separate PostgreSQL databases on RDS).

Each database Secret must provide `host`, `port`, `name`, `user`, and `password`
keys. Create secrets out of band; do not commit credentials or plaintext secret
values to this repository.

## Install or upgrade

Set the ingress host in `values-production.yaml`; image repositories are already
configured for the `byron-movie-cloud` GitHub organization and image tags are
updated automatically after successful default-branch publishes. Then run:

```sh
helm upgrade --install movie-cloud ./charts/movie-cloud \
  --namespace movie-cloud --create-namespace \
  --values values-production.yaml
```

Check rollout status with `kubectl get deployments,services,ingress -n movie-cloud`
and `kubectl rollout status deployment -n movie-cloud`.

The chart uses TCP probes because Spring Security protects HTTP endpoints by
default. The API images read `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD` from the corresponding existing Kubernetes Secret.
