"""Sample views for AIPS fixture project."""
from django.http import JsonResponse
from django.views import View
from .models import Article


class ArticleListView(View):
    def get(self, request):
        articles = list(Article.objects.values("id", "title", "created_at"))
        return JsonResponse({"articles": articles})
