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

## AWS and EKS playground setup

The deployment target is an existing EKS cluster. The previously selected
context was an EKS cluster in `eu-north-1`; verify the cluster name and account
in the AWS console before running commands. These steps create AWS/Kubernetes
resources and can incur charges.

### 1. Get an authorized Kubernetes context

For a short-lived playground, the AWS root user can be used in the AWS console
or CloudShell to bootstrap access. Avoid creating or saving root access keys.
For `kubectl`, use an IAM role or user with an EKS access entry; root is not a
good long-lived cluster identity.

In the EKS console, open the cluster's **Access** tab and ensure the IAM role or
user you will use has an access entry with the `AmazonEKSClusterAdminPolicy`
cluster access policy. Then, in CloudShell or a terminal authenticated as that
identity, configure and verify the context:

```sh
aws sts get-caller-identity
aws eks update-kubeconfig --region eu-north-1 --name <cluster-name>
kubectl config current-context
kubectl get nodes
```

Do not continue unless `kubectl get nodes` shows the intended EKS cluster.

### 2. Provide PostgreSQL databases and credentials

Provision PostgreSQL reachable from the EKS VPC (for example, one RDS instance
with separate `auth`, `movie`, and `user` databases). Allow inbound TCP 5432 only
from the EKS node/pod security group as appropriate. Prepare one private env
file per service with these keys:

```text
host=<RDS endpoint>
port=5432
name=<database name>
user=<database username>
password=<database password>
```

Store the files outside Git, then create the Kubernetes Secrets in the target
namespace. For a disposable test, a local file can be used; for a lasting setup,
prefer AWS Secrets Manager with an external-secrets integration.

```sh
kubectl create namespace movie-cloud
kubectl create secret generic auth-db-credentials -n movie-cloud \
  --from-env-file="$HOME/.secrets/auth-db.env"
kubectl create secret generic movie-db-credentials -n movie-cloud \
  --from-env-file="$HOME/.secrets/movie-db.env"
kubectl create secret generic user-db-credentials -n movie-cloud \
  --from-env-file="$HOME/.secrets/user-db.env"
```

Each Secret must contain `host`, `port`, `name`, `user`, and `password`. Never
commit these env files or put credentials in Helm values.

### 3. Make GHCR images pullable

The production values reference `ghcr-pull-secret`. Either make all four GHCR
packages public, or create a GitHub token with `read:packages` and create this
secret in `movie-cloud`:

```sh
kubectl create secret docker-registry ghcr-pull-secret -n movie-cloud \
  --docker-server=ghcr.io \
  --docker-username=<github-username> \
  --docker-password="$GHCR_READ_TOKEN"
```

Set `GHCR_READ_TOKEN` in your shell without putting the token in shell history.
This read token is separate from the `GITOPS_TOKEN` Actions secret used by the
service repositories to notify GitOps.

### 4. Install an ingress controller

The chart currently uses the `nginx` ingress class, and the cluster previously
had no IngressClass. Install ingress-nginx before enabling the Application. Its
LoadBalancer Service will ask AWS to provision an external load balancer:

```sh
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --set controller.service.type=LoadBalancer
kubectl get services -n ingress-nginx
```

Set `ingress.host` in `values-production.yaml` to a domain you control. Once
the controller Service has an AWS load balancer hostname, create a DNS record
pointing your domain at it. For a production EKS setup, AWS Load Balancer
Controller/ALB is another option, but the chart's ingress class and annotations
must then be changed from `nginx` to match.

### 5. Install Argo CD and connect GitOps

Install the upstream Argo CD manifests for a playground cluster:

```sh
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd
```

For a private GitHub GitOps repository, add a read-only deploy key or token in
the Argo CD UI under **Settings → Repositories**. This is not the `GITOPS_TOKEN`;
Argo CD needs read access, while the Actions token is used only for cross-repo
dispatch. For a temporary local UI session:

```sh
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

The initial admin password is in `argocd-initial-admin-secret`; rotate it after
logging in. In the UI, verify the GitOps repo connection, then bootstrap the
Application from this repository checkout:

```sh
kubectl apply -f argocd/movie-cloud.yaml
kubectl get applications -n argocd
```

The Application tracks the GitOps repo's default branch (`HEAD`) as two Argo CD
sources: the Helm chart under `charts/movie-cloud`, and the root-level
`values-production.yaml` file referenced through `$values`. It has automated
sync, prune, and self-heal enabled. Subsequent successful default-branch image
publishes update the values file, and Argo CD reconciles the new image tags.

### 6. Verify deployment

```sh
kubectl get pods,services,ingress -n movie-cloud
kubectl get ingress -n movie-cloud
```

Check the Argo CD Application's sync/health status and the pod events if a
workload is not ready. Common causes are missing database Secrets, RDS network
access, or GHCR pull permissions.

The chart uses TCP probes because Spring Security protects HTTP endpoints by
default. The API images read `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD` from the corresponding Secrets. The ingress currently routes to
the frontend only, and the frontend is not yet connected to the API services.
