"""Unit tests for fly_db._select_cluster."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from src.cli.commands.fly_db.select import SelectedCluster, _select_cluster
from src.infra.flyio.controller import ManagedPostgresInfo


def _mpg(id: str, name: str, region: str = "iad") -> ManagedPostgresInfo:
    return ManagedPostgresInfo(
        id=id, name=name, region=region, plan="basic", status="running"
    )


def _controller(
    *,
    mpg_list=None,
    legacy_list=None,
    mpg_status=None,
) -> MagicMock:
    ctrl = MagicMock()
    ctrl.mpg_list.return_value = mpg_list or []
    ctrl.postgres_list.return_value = legacy_list or []
    ctrl.mpg_status.return_value = mpg_status
    return ctrl


class TestSelectCluster:
    """Tests for _select_cluster."""

    def test_select_by_id_exact_match(self) -> None:
        """When cluster arg matches, mpg_status lookup returns that cluster."""
        info = _mpg("abc123", "my-postgres")
        ctrl = _controller(mpg_status=info)

        result = _select_cluster(ctrl, "abc123")

        assert isinstance(result, SelectedCluster)
        assert result.id == "abc123"
        assert result.name == "my-postgres"
        assert result.is_legacy is False

    def test_select_by_name_exact_match(self) -> None:
        """When mpg_status returns a cluster, its name is used."""
        info = _mpg("id-1", "prod-db", region="lhr")
        ctrl = _controller(mpg_status=info)

        result = _select_cluster(ctrl, "prod-db")

        assert result.name == "prod-db"
        assert result.region == "lhr"

    def test_select_single_result_auto_selected(self) -> None:
        """Single cluster with no cluster arg is auto-selected."""
        info = _mpg("solo-id", "solo-db")
        ctrl = _controller(mpg_list=[info], mpg_status=None)

        mock_settings = MagicMock()
        mock_settings.name = None  # no cluster configured in settings
        with patch(
            "src.cli.commands.fly_db.select._load_fly_db_settings",
            return_value=mock_settings,
        ):
            result = _select_cluster(ctrl, None)

        assert result.id == "solo-id"
        assert result.name == "solo-db"

    def test_select_no_clusters_exits(self) -> None:
        """Empty cluster list raises typer.Exit."""
        ctrl = _controller(mpg_status=None)

        mock_settings = MagicMock()
        mock_settings.name = None
        with patch(
            "src.cli.commands.fly_db.select._load_fly_db_settings",
            return_value=mock_settings,
        ):
            with pytest.raises(typer.Exit):
                _select_cluster(ctrl, None)

    def test_select_ambiguous_no_cluster_arg_exits(self) -> None:
        """Multiple clusters with no cluster arg and no interactive → exit."""
        clusters = [_mpg("id-1", "db-one"), _mpg("id-2", "db-two")]
        ctrl = _controller(mpg_list=clusters, mpg_status=None)

        mock_settings = MagicMock()
        mock_settings.name = None
        with (
            patch(
                "src.cli.commands.fly_db.select._load_fly_db_settings",
                return_value=mock_settings,
            ),
            patch("typer.prompt", side_effect=KeyboardInterrupt),
        ):
            with pytest.raises(typer.Exit):
                _select_cluster(ctrl, None)
