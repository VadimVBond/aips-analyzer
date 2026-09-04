"""
Sample Django models for AIPS Analyzer fixture project.
"""
from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Author(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    articles = models.ManyToManyField(Article, blank=True)

    def __str__(self):
        return self.name
