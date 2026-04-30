"""Unit tests for ``BookService``.

These exercise the service-layer contract that the scaffold encodes for every
generated entity:

- the service commits on success and rolls back on repository errors,
- ``update`` raises a domain-level ``BookNotFoundError`` (not an
  ``HTTPException``) when the entity is missing,
- read methods are side-effect-free.

Routers and the persistence model aren't under test here — the repository is
a Mock with the right shape.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from sqlmodel import Session

from src.app.entities.service.book.entity import Book
from src.app.entities.service.book.repository import BookRepository
from src.app.entities.service.book.schemas import (
    BookCreate,
    BookRead,
    BookUpdate,
)
from src.app.entities.service.book.service import (
    BookNotFoundError,
    BookService,
)


@pytest.fixture
def repo() -> Mock:
    return Mock(spec=BookRepository)


@pytest.fixture
def session() -> Mock:
    return Mock(spec=Session)


@pytest.fixture
def service(session: Mock, repo: Mock) -> BookService:
    return BookService(session, repo)


class TestCreate:
    def test_commits_on_success(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.create.side_effect = lambda book: book  # echo back

        result = service.create(BookCreate(name="The Pragmatic Programmer"))

        assert isinstance(result, BookRead)
        assert result.name == "The Pragmatic Programmer"
        repo.create.assert_called_once()
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    def test_rolls_back_when_repository_raises(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.create.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError):
            service.create(BookCreate(name="x"))

        session.commit.assert_not_called()
        session.rollback.assert_called_once()


class TestUpdate:
    def test_raises_not_found_when_missing(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        """The service raises a domain exception — translation to HTTP 404 is
        the router's job."""
        repo.get.return_value = None

        with pytest.raises(BookNotFoundError):
            service.update("missing-id", BookUpdate(name="x"))

        repo.update.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_partial_update_only_touches_supplied_fields(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        existing = Book(name="Original")
        repo.get.return_value = existing
        repo.update.side_effect = lambda book: book

        # No `name` supplied — Update is empty; existing fields preserved.
        result = service.update(existing.id, BookUpdate())

        assert result.name == "Original"
        session.commit.assert_called_once()

    def test_commits_on_success(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        existing = Book(name="Old")
        repo.get.return_value = existing
        repo.update.side_effect = lambda book: book

        result = service.update(existing.id, BookUpdate(name="New"))

        assert result.name == "New"
        session.commit.assert_called_once()
        session.rollback.assert_not_called()

    def test_rolls_back_when_repository_raises(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        existing = Book(name="Old")
        repo.get.return_value = existing
        repo.update.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError):
            service.update(existing.id, BookUpdate(name="New"))

        session.commit.assert_not_called()
        session.rollback.assert_called_once()


class TestDelete:
    def test_returns_repository_result_and_commits(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.delete.return_value = True

        assert service.delete("some-id") is True
        session.commit.assert_called_once()

    def test_returns_false_when_not_found(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.delete.return_value = False

        assert service.delete("missing-id") is False
        # Even a no-op delete commits — the repo returned cleanly.
        session.commit.assert_called_once()

    def test_rolls_back_when_repository_raises(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.delete.side_effect = RuntimeError("constraint violation")

        with pytest.raises(RuntimeError):
            service.delete("some-id")

        session.commit.assert_not_called()
        session.rollback.assert_called_once()


class TestRead:
    def test_get_returns_none_when_missing(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.get.return_value = None

        assert service.get("missing") is None
        # Reads must not touch the transaction.
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_list_maps_to_read_dtos(
        self, service: BookService, session: Mock, repo: Mock
    ) -> None:
        repo.list_all.return_value = [Book(name="A"), Book(name="B")]

        result = service.list()

        assert [b.name for b in result] == ["A", "B"]
        assert all(isinstance(b, BookRead) for b in result)
        session.commit.assert_not_called()
