"""Sample test file for AIPS fixture project."""
import pytest
from blog.models import Article


def test_article_creation():
    """Test that an Article can be created."""
    article = Article(title="Test", content="Content")
    assert article.title == "Test"


def test_article_str():
    article = Article(title="Hello World", content="...")
    assert str(article) == "Hello World"


class TestAuthorModel:
    def test_author_email_required(self):
        """Author requires an email field."""
        pass
