from pathlib import Path

import yaml

from simulation.tools import marker_registry


def _catalog_actions() -> list[dict]:
    data = yaml.safe_load(Path('.github/action-templates/catalog.yml').read_text())
    return data['actions']


def test_every_catalog_action_has_marker_spec():
    action_ids = {action['id'] for action in _catalog_actions()}

    assert marker_registry.validate_catalog_coverage(action_ids) == []


def test_every_catalog_action_has_template_file_and_marker_contract():
    for action in _catalog_actions():
        template = Path('.github/action-templates') / action['template']
        assert template.exists(), f"missing template for {action['id']}: {template}"
        spec = marker_registry.get_marker_spec(action['id'])
        assert spec is not None
        text = template.read_text()
        assert f"{spec.marker}:" in text, f"{action['id']} template omits marker {spec.marker}:"


def test_marker_table_is_renderable():
    table = marker_registry.format_marker_table()

    assert '| Action | Marker | Values | Terminal | Meaning |' in table
    assert '`review_pr`' in table
    assert '`REVIEW-VERDICT:`' in table


def test_action_coverage_audit_passes():
    from simulation.tools import action_coverage

    report = action_coverage.audit_coverage()

    assert report.ok, report.errors
    assert "review_pr" in report.actions
    assert "001-suspend-cookie" in report.scenarios
