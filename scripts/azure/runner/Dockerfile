# scripts/azure/runner/Dockerfile
#
# Ephemeral, repo-scoped GitHub Actions runner for the intake-agent Container
# Apps Job. Built and pushed via scripts/azure/bootstrap-runner.sh (ACR
# Tasks — `az acr build` — not a local Docker daemon, so this works from any
# operator machine or CI runner with `az` access, regardless of the target
# registry's network restrictions; only the final push needs a network path
# to the registry, see runner-acr.bicep).
#
# Tools baked in ahead of time (rather than installed at job runtime) so the
# ~1-hour ephemeral lifecycle spends its time on the actual azd
# provision/deploy work, not on repeated internet-dependent installs:
#   - Azure CLI (installed from Microsoft's apt repository, then asserted to
#     meet AZURE_CLI_MIN_VERSION — see the install step below)
#   - GitHub Actions runner binary (--ephemeral mode; deregisters itself
#     after exactly one job — see entrypoint.sh), integrity-checked against a
#     digest defaulting to the published v2.336.0 release checksum
#   - jq, git, curl — general workflow-step dependencies
#
# Two runtime scripts and one runner hook are baked in read-only, owned by
# root, outside the runner user's home and outside the runner application
# directory, so that a workflow step (which runs as `runner`) cannot rewrite
# the code that isolates the PAT or the hook that admits the job:
#   /opt/runner-bin/entrypoint.sh    bootstrap stage — holds the PAT, execs away
#   /opt/runner-bin/job-stage.sh     clean stage — configures and runs the runner
#   /opt/runner-hooks/job-started.sh ACTIONS_RUNNER_HOOK_JOB_STARTED admission hook
#
# To prove that isolation holds at the kernel level (PID 1's /proc environ),
# run: bash scripts/azure/runner/verify-pat-isolation.sh
#
# azd itself and the microsoft.foundry extension are deliberately installed
# by the deploy.yml workflow at job start (Azure/setup-azd@v2 +
# `azd ext install microsoft.foundry`), not baked in here — see the note
# above the Azure CLI install step below.

FROM ubuntu:22.04

ARG RUNNER_VERSION=2.336.0
# Official SHA-256 of actions-runner-linux-x64-2.336.0.tar.gz, exactly as
# published in the actions/runner v2.336.0 release notes. Defaulted here so a
# routine bootstrap carries no manual checksum burden; an operator can still
# override it with --build-arg RUNNER_SHA256=... after reviewing a different
# digest (bootstrap-runner.sh forwards RUNNER_SHA256 only when it is set).
ARG RUNNER_SHA256=04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d
# Minimum acceptable Azure CLI version. This is a floor that is *verified*
# after installation, not a pin: the aka.ms/InstallAzureCLIDeb script installs
# the current package from Microsoft's apt repository and offers no version
# selection.
ARG AZURE_CLI_MIN_VERSION=2.89.1

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       curl ca-certificates jq git tar unzip lsb-release \
    && rm -rf /var/lib/apt/lists/*

# GitHub's runner refuses to self-configure as root; runtime uses a dedicated
# non-root user and has no sudo capability.
RUN useradd -m -s /bin/bash runner

# Azure CLI is a stable, foundational dependency — baked into the image.
# azd itself and the microsoft.foundry extension are installed by the
# deploy.yml workflow instead (Azure/setup-azd@v2 + azd ext install), not
# here — that keeps the "setup-azd v2 fix" and "Foundry extension install"
# visible and auditable in workflow logs, and avoids the image needing a
# rebuild every time azd/the extension ships a new version.
#
# The installer accepts no version argument, so this step asserts the
# resulting version against AZURE_CLI_MIN_VERSION rather than claiming a pin
# it cannot enforce. A build that lands a CLI older than the floor fails here
# instead of at deploy time.
RUN curl --fail --silent --show-error --location https://aka.ms/InstallAzureCLIDeb | bash \
    && installed="$(az version --output tsv --query '"azure-cli"')" \
    && oldest="$(printf '%s\n%s\n' "$installed" "${AZURE_CLI_MIN_VERSION}" | sort -V | head -n1)" \
    && if [ "$oldest" != "${AZURE_CLI_MIN_VERSION}" ]; then \
         echo "Azure CLI ${installed} is older than the required minimum ${AZURE_CLI_MIN_VERSION}" >&2; exit 1; \
       fi \
    && echo "Azure CLI ${installed} satisfies the ${AZURE_CLI_MIN_VERSION} minimum"

WORKDIR /home/runner/actions-runner
RUN test -n "${RUNNER_SHA256}" \
    && curl --fail --silent --show-error --location -o actions-runner.tar.gz \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz" \
    && echo "${RUNNER_SHA256}  actions-runner.tar.gz" | sha256sum --check --status \
    && tar xzf actions-runner.tar.gz \
    && rm actions-runner.tar.gz \
    && ./bin/installdependencies.sh \
    && chown -R runner:runner /home/runner/actions-runner

# Deliberately NOT --chown=runner: these stay root-owned and non-writable by
# the runtime user. entrypoint.sh refuses to start if the hook (or its
# directory) is writable by the runner user, so the permissions below are part
# of the security contract, not cosmetics. The hook also lives outside
# /home/runner/actions-runner, per GitHub's runner-hook guidance.
COPY entrypoint.sh job-stage.sh /opt/runner-bin/
COPY hooks/job-started.sh /opt/runner-hooks/
RUN chmod 0555 /opt/runner-bin/entrypoint.sh /opt/runner-bin/job-stage.sh \
      /opt/runner-hooks/job-started.sh \
    && chmod 0555 /opt/runner-bin /opt/runner-hooks

USER runner
WORKDIR /home/runner
ENTRYPOINT ["/opt/runner-bin/entrypoint.sh"]
