"""Deployment-level observability configuration regressions."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DEPLOYMENT_TEMPLATE = (
    REPO_ROOT / "k8s" / "application" / "backend-deployment.yaml.template"
)


def test_backend_uses_supported_explicit_trace_sampler():
    template = BACKEND_DEPLOYMENT_TEMPLATE.read_text()

    assert (
        '- name: OTEL_TRACES_SAMPLER\n          value: "parentbased_always_on"'
        in template
    )
